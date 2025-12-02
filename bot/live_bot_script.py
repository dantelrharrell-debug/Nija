import os
import logging
from flask import Flask, jsonify

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
PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# ----------------------------
# Initialize Coinbase client only if credentials exist
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
    logger.warning("Coinbase client not initialized. Missing credentials. Live trading disabled.")

# ----------------------------
# Flask app setup
# ----------------------------
app = Flask(__name__)

@app.route("/")
def index():
    status = "Live trading enabled" if client else "Live trading disabled"
    return jsonify({"status": status})

# ----------------------------
# Example bot logic (safe check for client)
# ----------------------------
def run_bot():
    if not client:
        logger.warning("Bot skipped execution: Coinbase client not initialized.")
        return

    # Example trading logic (replace with your actual bot)
    logger.info("Bot is running...")
    # Example: fetch accounts
    try:
        accounts = client.get_accounts()
        logger.info(f"Accounts fetched: {accounts}")
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")

# ----------------------------
# Entrypoint for script
# ----------------------------
if __name__ == "__main__":
    logger.info("Starting bot and Flask app...")
    run_bot()
    app.run(host="0.0.0.0", port=5000)
