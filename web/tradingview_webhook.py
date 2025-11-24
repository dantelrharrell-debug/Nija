# web/tradingview_webhook.py
from flask import Blueprint, request, jsonify, current_app
import os
import logging
import hmac
import hashlib

bp = Blueprint("tradingview_webhook", __name__)
logger = logging.getLogger(__name__)

def verify_signature(secret: str, payload: bytes, signature_header: str) -> bool:
    """
    Expect signature_header to be hex HMAC-SHA256 of payload using secret.
    """
    if not signature_header:
        return False
    try:
        sig_bytes = bytes.fromhex(signature_header)
    except Exception:
        return False
    computed = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    # Use hmac.compare_digest to avoid timing attacks.
    return hmac.compare_digest(computed, sig_bytes)

@bp.route("/webhook", methods=["POST"])
def webhook():
    try:
        tv_secret = os.getenv("TV_WEBHOOK_SECRET", "")
        payload = request.get_data() or b""
        signature = request.headers.get("X-TV-Signature", "")

        if tv_secret:
            if not verify_signature(tv_secret, payload, signature):
                logger.warning("TradingView webhook signature verification failed.")
                return jsonify({"status": "error", "message": "bad signature"}), 401
        else:
            logger.info("No TV_WEBHOOK_SECRET set — skipping signature verification (dev mode).")

        data = request.get_json(silent=True) or {}
        logger.info("Received TradingView webhook", extra={"payload": data})
        # TODO: implement handling: validate fields, enqueue job, etc.
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.exception("Error handling TradingView webhook")
        return jsonify({"status": "error", "message": str(e)}), 500
