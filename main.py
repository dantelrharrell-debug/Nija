import os
import subprocess
import logging
from nija_client import CoinbaseClient  # your existing client

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- Step 0: Verify live trading env var ---
live_mode = os.getenv("LIVE_TRADING", "0")
if live_mode == "1":
    logging.info("✅ LIVE_TRADING is ACTIVE")
else:
    logging.warning("⚠️ LIVE_TRADING is NOT active! Set LIVE_TRADING=1")

# --- Step 1: Print installed Python packages ---
logging.info("📦 Installed Python packages:")
subprocess.run(["pip", "list"])

# --- Step 2: Verify Coinbase connection ---
def test_coinbase_connection():
    try:
        client = CoinbaseClient()  # adjust if constructor requires args
        accounts = client.fetch_accounts()  # should return funded accounts
        logging.info(f"✅ Coinbase connection OK. Accounts fetched: {accounts}")
        # Optionally print balances
        for acc in accounts:
            logging.info(f"   {acc['currency']}: {acc['balance']['amount']}")
        return True
    except Exception as e:
        logging.error(f"❌ Coinbase connection failed: {e}")
        return False

if test_coinbase_connection():
    logging.info("🚀 Bot is live and ready to trade!")
else:
    logging.error("❌ Bot is NOT live! Fix connection before trading.")

import os
import threading
from flask import Flask, request, jsonify
from loguru import logger

# Import your trading logic
from coinbase_trader import coinbase_loop
from tv_webhook_listener import handle_tv_webhook  # We'll define a route instead of a separate server

# Initialize Flask app
app = Flask(__name__)

# Try to register TradingView webhook blueprint
# Register TradingView webhook blueprint (safe import/register)
try:
    from tradingview_webhook import tradingview_bp
    app.register_blueprint(tradingview_bp)
    logger.info("✅ TradingView webhook blueprint registered")
except Exception as e:
    logger.warning(f"⚠️  Could not register TradingView webhook blueprint: {e}")

# Initialize Coinbase client once
try:
    from nija_client import CoinbaseClient
    client = CoinbaseClient()
    logger.info("✅ CoinbaseClient initialized")
except Exception as e:
    client = None
    logger.exception("❌ Failed to initialize CoinbaseClient at startup")

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
