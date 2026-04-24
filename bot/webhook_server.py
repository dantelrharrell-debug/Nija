"""
NIJA TradingView Webhook Server
================================

Flask HTTP server that receives TradingView alert webhooks and routes them
to the NIJA trading engine for instant trade execution.

Endpoint:
    POST /webhook/tradingview  — Receive and execute TradingView alerts

Usage:
    Run standalone:
        python -m bot.webhook_server

    Or import and mount on an existing Flask app:
        from bot.webhook_server import create_webhook_blueprint
        app.register_blueprint(create_webhook_blueprint(broker), url_prefix='/api')

Environment Variables:
    TRADINGVIEW_WEBHOOK_SECRET  — Required.  Shared secret to authenticate alerts.
    WEBHOOK_PORT                — Optional.  Port for standalone server (default 5001).
    WEBHOOK_HOST                — Optional.  Host for standalone server (default 0.0.0.0).

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import sys

from flask import Blueprint, Flask, Response, jsonify, request

# ---------------------------------------------------------------------------
# Import the core TradingView webhook handler.
# This will raise ValueError at startup if TRADINGVIEW_WEBHOOK_SECRET is missing.
# ---------------------------------------------------------------------------
try:
    from tradingview_webhook import (
        get_webhook_stats,
        parse_webhook_payload,
        process_webhook_signal,
    )
    _TV_WEBHOOK_AVAILABLE = True
except ImportError:
    try:
        from bot.tradingview_webhook import (
            get_webhook_stats,
            parse_webhook_payload,
            process_webhook_signal,
        )
        _TV_WEBHOOK_AVAILABLE = True
    except ImportError:
        _TV_WEBHOOK_AVAILABLE = False
        parse_webhook_payload = None  # type: ignore[assignment]
        process_webhook_signal = None  # type: ignore[assignment]
        get_webhook_stats = None  # type: ignore[assignment]

logger = logging.getLogger("nija.webhook_server")

# ---------------------------------------------------------------------------
# Broker singleton (used when running standalone)
# ---------------------------------------------------------------------------
_broker = None


def _get_broker():
    """Return the cached broker instance, creating it on first call."""
    global _broker
    if _broker is not None:
        return _broker
    try:
        from broker_integration import CoinbaseBrokerAdapter
    except ImportError:
        from bot.broker_integration import CoinbaseBrokerAdapter

    adapter = CoinbaseBrokerAdapter()
    ok = adapter.connect()
    if not ok:
        logger.error("[WebhookServer] Failed to connect to Coinbase broker")
        return None
    _broker = adapter
    return _broker


# ---------------------------------------------------------------------------
# Blueprint factory
# ---------------------------------------------------------------------------

def create_webhook_blueprint(broker=None) -> Blueprint:
    """Create and return the TradingView webhook Flask Blueprint.

    Args:
        broker: Optional pre-connected broker instance.  If omitted the
                server attempts to connect to Coinbase automatically using
                environment credentials.

    Returns:
        Flask Blueprint with the ``/webhook/tradingview`` POST endpoint
        and a ``/webhook/health`` GET endpoint registered.
    """
    bp = Blueprint("nija_webhook", __name__)
    _bp_broker = broker  # allow override per blueprint instance

    def _resolve_broker():
        return _bp_broker if _bp_broker is not None else _get_broker()

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    @bp.route("/webhook/health", methods=["GET"])
    def webhook_health() -> Response:
        """Return the webhook server status and processing statistics."""
        stats = get_webhook_stats() if _TV_WEBHOOK_AVAILABLE and get_webhook_stats else {}
        return jsonify({
            "status": "ok" if _TV_WEBHOOK_AVAILABLE else "degraded",
            "tradingview_webhook_available": _TV_WEBHOOK_AVAILABLE,
            "stats": stats,
        })

    # ------------------------------------------------------------------
    # TradingView webhook endpoint
    # ------------------------------------------------------------------
    @bp.route("/webhook/tradingview", methods=["POST"])
    def tradingview_webhook() -> Response:
        """Receive a TradingView alert and execute the corresponding trade.

        Expected JSON payload::

            {
                "secret": "<TRADINGVIEW_WEBHOOK_SECRET>",
                "symbol": "BTC-USD",
                "action": "buy" | "sell" | "close",
                "position_size": 100.0
            }

        Batch orders are also supported via an ``orders`` list key.

        Returns:
            200  — One or more orders were processed (see ``results`` list).
            400  — Invalid payload structure or symbol.
            401  — Incorrect webhook secret.
            503  — Webhook handler module unavailable.
        """
        if not _TV_WEBHOOK_AVAILABLE:
            logger.error("[WebhookServer] tradingview_webhook module not available")
            return jsonify({"error": "Webhook handler unavailable"}), 503

        # -- Parse JSON body --
        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception as exc:
            logger.warning(f"[WebhookServer] Failed to parse JSON body: {exc}")
            return jsonify({"error": "Invalid JSON body"}), 400

        if not payload:
            return jsonify({"error": "Empty or non-JSON request body"}), 400

        # -- Validate payload (includes secret check) --
        is_valid, err_msg, orders = parse_webhook_payload(payload)

        if not is_valid:
            status_code = 401 if "Unauthorized" in err_msg else 400
            logger.warning(f"[WebhookServer] Rejected webhook: {err_msg}")
            return jsonify({"error": err_msg}), status_code

        if not orders:
            return jsonify({"message": "No orders to process"}), 200

        # -- Resolve broker and get balance --
        active_broker = _resolve_broker()
        available_balance = 0.0
        if active_broker:
            try:
                balance_info = active_broker.get_account_balance()
                available_balance = float(balance_info.get("available_usd", 0) or 0)
            except Exception as bal_err:
                logger.warning(f"[WebhookServer] Could not fetch balance: {bal_err}")
        else:
            logger.warning("[WebhookServer] No broker available — orders may be skipped")

        # -- Execute orders --
        results = process_webhook_signal(orders, active_broker, available_balance)

        executed = sum(1 for r in results if r.get("status") == "executed")
        logger.info(
            f"[WebhookServer] Processed {len(results)} order(s), "
            f"{executed} executed"
        )

        return jsonify({
            "received": len(orders),
            "executed": executed,
            "results": results,
        })

    return bp


# ---------------------------------------------------------------------------
# Standalone Flask app
# ---------------------------------------------------------------------------

def create_app(broker=None) -> Flask:
    """Create the standalone webhook Flask application."""
    app = Flask(__name__)
    app.register_blueprint(create_webhook_blueprint(broker))

    @app.route("/healthz")
    def healthz() -> Response:
        return jsonify({"status": "ok", "service": "nija-webhook-server"})

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.getenv("WEBHOOK_PORT", "5001"))

    logger.info("=" * 60)
    logger.info("  NIJA TradingView Webhook Server")
    logger.info(f"  Listening on {host}:{port}")
    logger.info("  POST /webhook/tradingview — Receive TradingView alerts")
    logger.info("  GET  /webhook/health      — Health check")
    logger.info("=" * 60)

    flask_app = create_app()
    flask_app.run(host=host, port=port, debug=False, threaded=True)
