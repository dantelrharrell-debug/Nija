from flask import Blueprint, request, jsonify
import hmac
import hashlib
import os

# Create the Blueprint
bp = Blueprint("tradingview", __name__, url_prefix="/tv")

# Load secret from env
TV_WEBHOOK_SECRET = os.environ.get("TV_WEBHOOK_SECRET", "")

@bp.route("/webhook", methods=["POST"])
def webhook():
    # Verify TradingView signature
    signature = request.headers.get("X-Signature", "")
    payload = request.get_data()

    if TV_WEBHOOK_SECRET:
        computed = hmac.new(
            TV_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed, signature):
            return jsonify({"error": "Invalid signature"}), 403

    data = request.json or {}
    # Here you can queue or trigger your trading logic
    return jsonify({"status": "received", "data": data})
