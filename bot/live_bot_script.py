import os
import logging

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ----------------------------
# Coinbase credentials
# ----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # Optional, can be None

# ----------------------------
# Initialize Coinbase client
# ----------------------------
client = None
if API_KEY and API_SECRET and PASSPHRASE:
    try:
        from coinbase_advanced_py.client import Client
        client = Client(api_key=API_KEY, api_secret=API_SECRET, api_sub=PASSPHRASE)
        logger.info("Coinbase client initialized. Live trading enabled.")
    except Exception as e:
        logger.error(f"Failed to initialize Coinbase client: {e}")
else:
    logger.warning(
        "Coinbase client not initialized. Missing credentials. "
        "Live trading disabled."
    )

# ----------------------------
# Example trading loop
# ----------------------------
def start_trading_loop():
    if not client:
        logger.warning("Trading loop skipped: Coinbase client not initialized.")
        return

    logger.info("Starting trading loop...")
    try:
        accounts = client.get_accounts()  # Example method
        logger.info(f"Accounts fetched: {accounts}")
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")

# ----------------------------
# Flask App
# ----------------------------
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"status": "Bot running", "live_trading": client is not None})

# Optional: endpoint to manually start trading loop
@app.route("/start")
def start():
    start_trading_loop()
    return jsonify({"status": "Trading loop triggered"})

if __name__ == "__main__":
    logger.info("Starting Flask app...")
    app.run(host="0.0.0.0", port=5000)
