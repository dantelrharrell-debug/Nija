import os
import logging
from flask import Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = Flask(__name__)

# --- Coinbase Connection Check ---
def init_coinbase():
    try:
        from coinbase_advanced.client import Client
    except ModuleNotFoundError:
        logging.error("coinbase_advanced module not installed. Live trading disabled.")
        return None

    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB")
        )
        account = client.get_account()  # basic API test
        logging.info(f"Coinbase connection successful. Account ID: {account['id']}")
        return client
    except Exception as e:
        logging.error(f"Coinbase connection failed: {e}")
        return None

# Initialize Coinbase on startup
coinbase_client = init_coinbase()
if coinbase_client:
    logging.info("Bot is ready for live trading.")
else:
    logging.info("Bot is NOT connected. Check API keys or network.")

# --- Example route (optional) ---
@app.route("/")
def home():
    return "NIJA Bot running ✅"

# --- If running standalone (optional) ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
