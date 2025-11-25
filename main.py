import os
import logging
import threading
from flask import Flask, jsonify, request
from nija_client import CoinbaseClient

# --- Logging setup ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("nija")

# --- Check live mode ---
live_mode = os.getenv("LIVE_TRADING", "0") == "1"
logger.info(f"Live trading mode: {live_mode}")

# --- Initialize Coinbase client ---
client = CoinbaseClient()

# --- Flask app ---
app = Flask(__name__)

@app.route("/")
def index():
    status = {
        "service": "NIJA Bot",
        "coinbase_client": "initialized" if client.client else "not-initialized",
        "live_trading": live_mode
    }
    return jsonify(status)

@app.route("/accounts")
def accounts():
    if not client.client:
        return jsonify({"error": "Coinbase client not initialized"}), 500
    accounts = client.get_accounts()
    if accounts:
        return jsonify({"accounts": accounts})
    return jsonify({"error": "Failed to fetch accounts"}), 500

@app.route("/webhook", methods=["POST"])
def tradingview_webhook():
    payload = request.get_json(force=True, silent=True) or {}
    logger.info("Received TradingView webhook: %s", payload)
    try:
        from tv_webhook_listener import handle_tv_webhook
        threading.Thread(target=handle_tv_webhook, args=(payload,), daemon=True).start()
    except Exception as e:
        logger.exception("Failed to dispatch webhook: %s", e)
    return jsonify({"status": "received"}), 200

# --- Optional: start trading loop ---
def start_coinbase_loop_if_possible():
    try:
        from coinbase_trader import coinbase_loop
        if client.client:
            t = threading.Thread(target=coinbase_loop, args=(client.client,), daemon=True)
            t.start()
            logger.info("Started Coinbase trading loop thread.")
            return t
    except Exception as e:
        logger.warning("coinbase_trader.coinbase_loop not available: %s", e)
    return None

# --- Run Flask app if main ---
if __name__ == "__main__":
    start_coinbase_loop_if_possible()
    port = int(os.getenv("PORT", 5000))
    logger.info(f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=os.getenv("DEBUG", "0") == "1")
