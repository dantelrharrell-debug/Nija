# bot/tradingview_webhook/webhook_handler.py
import os
import logging
from flask import jsonify

LOGGER = logging.getLogger(__name__)

def handle_tradingview_webhook(request):
    # Optional header-secret check
    tv_secret = os.getenv("TV_WEBHOOK_SECRET") or os.getenv("TRADINGVIEW_WEBHOOK_SECRET")
    header_secret = request.headers.get("X-TV-Webhook-Secret") or request.headers.get("X-TradingView-Secret")
    if tv_secret and header_secret and header_secret != tv_secret:
        LOGGER.warning("TradingView webhook secret mismatch")
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not payload:
        LOGGER.warning("TradingView webhook: no json payload")
        return jsonify({"error": "no json"}), 400

    LOGGER.info("TradingView webhook received: %s", payload)
    # TODO: push payload into your trade queue / processing pipeline
    return jsonify({"status": "ok", "received": True})
