import os
import threading
from flask import Flask, request, jsonify
from loguru import logger

# Import your trading logic
from coinbase_trader import coinbase_loop
from tv_webhook_listener import handle_tv_webhook  # We'll define a route instead of a separate server

# Initialize Flask app
app = Flask(__name__)

# Initialize Coinbase client once
try:
    from nija_client import CoinbaseClient
    client = CoinbaseClient()
    logger.info("✅ CoinbaseClient initialized")
except Exception as e:
    client = None
    logger.exception("❌ Failed to initialize CoinbaseClient at startup")

# Register TradingView webhook blueprint
try:
    from tradingview_webhook import tradingview_bp
    app.register_blueprint(tradingview_bp)
    logger.info("✅ TradingView webhook blueprint registered")
except Exception as e:
    logger.warning(f"⚠️  Could not register TradingView webhook blueprint: {e}")

# --- Flask Routes ---

@app.route("/")
def index():
    status = {
        "service": "NIJA Bot",
        "coinbase_client": "initialized" if client else "not-initialized"
    }
    return jsonify(status)

@app.route("/accounts")
def accounts():
    if not client:
        return jsonify({"error": "coinbase client not initialized"}), 500
    try:
        accts = client.list_accounts()
        return jsonify({"accounts": accts})
    except Exception as e:
        logger.exception("Failed fetching accounts")
        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def tradingview_webhook():
    try:
        payload = request.json
        logger.info(f"Received TradingView webhook: {payload}")
        # Pass payload to your TradingView handler function
        handle_tv_webhook(payload)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.exception("Failed handling TradingView webhook")
        return jsonify({"error": str(e)}), 500

# --- Main Entrypoint ---

if __name__ == "__main__":
    # Start Coinbase trading loop in a daemon thread
    coinbase_thread = threading.Thread(target=coinbase_loop, daemon=True)
    coinbase_thread.start()
    logger.info("Started Coinbase trading thread")

    # Start Flask server for TradingView webhooks
    port = int(os.getenv("PORT", 5000))
    logger.info(f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
