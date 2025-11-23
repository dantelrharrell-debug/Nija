# bot/tradingview_webhook/webhook_handler.py
from flask import jsonify
import logging
import os

LOGGER = logging.getLogger(__name__)

def handle_tradingview_webhook(request):
    """
    Minimal secure TradingView webhook handler.
    Expects JSON with at least {"signal": "buy" | "sell"}.
    Uses TV_WEBHOOK_SECRET env var (or TRADINGVIEW_WEBHOOK_SECRET) to validate.
    """
    tv_secret = os.getenv("TV_WEBHOOK_SECRET") or os.getenv("TRADINGVIEW_WEBHOOK_SECRET")
    # Optional basic header secret check:
    header_secret = request.headers.get("X-TV-Webhook-Secret") or request.headers.get("X-TradingView-Secret")
    if tv_secret and header_secret != tv_secret:
        LOGGER.warning("TradingView webhook secret mismatch")
        return jsonify({"error": "unauthorized"}), 401

    data = None
    try:
        data = request.get_json(silent=True)
    except Exception:
        pass

    if not data:
        LOGGER.warning("TradingView webhook: no JSON body")
        return jsonify({"error": "no json"}), 400

    signal = data.get("signal") or data.get("action") or data.get("type")
    # Basic validation
    LOGGER.info("Received TradingView webhook: %s", data)
    # TODO: call into your trading logic here (e.g. enqueuing trade jobs)
    return jsonify({"status": "ok", "received": signal})
