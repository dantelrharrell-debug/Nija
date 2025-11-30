# app.py
import os
import logging
from flask import Flask, jsonify

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Attempt to import Coinbase Advanced client
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed. Install it via pip install git+https://github.com/coinbase/coinbase-advanced-py.git")

# Load API credentials from environment
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_SUB = os.environ.get("COINBASE_API_SUB")  # optional, leave blank if not used

if not all([API_KEY, API_SECRET]):
    logging.error("Missing Coinbase API credentials. Set COINBASE_API_KEY and COINBASE_API_SECRET")
    raise RuntimeError("Missing Coinbase API credentials")

# Initialize Coinbase client
client = Client(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
logging.info("Coinbase client initialized successfully")

# Initialize Flask app
app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA Bot is running!"

@app.route("/balance")
def get_balance():
    try:
        accounts = client.get_accounts()
        balances = {}
        for acct in accounts["data"]:
            balances[acct["currency"]] = acct["available"]["amount"]
        return jsonify({"status": "success", "balances": balances})
    except Exception as e:
        logging.error(f"Error fetching balances: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    # For local development
    app.run(host="0.0.0.0", port=8080, debug=True)
