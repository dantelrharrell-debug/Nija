# nija_balance_endpoint.py
from flask import Flask, jsonify
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Attempt to import Coinbase client
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed.")

app = Flask(__name__)

# Initialize Coinbase client
client = None
if Client:
    client = Client(
        api_key=os.environ.get("COINBASE_API_KEY"),
        api_secret=os.environ.get("COINBASE_API_SECRET"),
        api_sub=os.environ.get("COINBASE_API_SUB")  # optional
    )

@app.route("/balance")
def balance():
    if not client:
        return jsonify({"error": "Coinbase client not initialized"}), 500
    try:
        accounts = client.get_accounts()
        # Only return accounts with non-zero balance
        funded_accounts = [acct for acct in accounts if float(acct.get('balance', 0)) > 0]
        return jsonify(funded_accounts)
    except Exception as e:
        logging.error(f"Error fetching accounts: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
