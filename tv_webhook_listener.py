from flask import Flask, request, jsonify
import hmac, hashlib, logging
from nija_client import CoinbaseClient
from config import TV_WEBHOOK_SECRET, TV_WEBHOOK_PORT

logger = logging.getLogger("TVListener")
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
client = CoinbaseClient()

def verify_signature(data, signature):
    mac = hmac.new(TV_WEBHOOK_SECRET.encode(), data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, signature)

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Signature", "")
    if not verify_signature(request.data, signature):
        logger.warning("Invalid webhook signature")
        return "Unauthorized", 401

    payload = request.json
    ticker = payload.get("ticker")
    action = payload.get("action")

    try:
        if action == "buy":
            client.place_order("buy", ticker)
        elif action == "sell":
            client.place_order("sell", ticker)
        logger.info(f"Executed TV trade: {action} {ticker}")
    except Exception as e:
        logger.error(f"Failed TV trade: {e}")
    return jsonify({"status": "ok"}), 200

def run_webhook_server():
    app.run(host="0.0.0.0", port=TV_WEBHOOK_PORT)
