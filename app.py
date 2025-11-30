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
    logging.error("coinbase_advanced module not installed. Make sure it's in your requirements.txt")

app = Flask(__name__)

def get_coinbase_balance():
    """Fetch the funded account balance from Coinbase"""
    if not Client:
        return {"error": "Coinbase client not installed"}

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")  # Optional

    if not api_key or not api_secret:
        return {"error": "API key/secret not set"}

    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        accounts = client.get_accounts()  # Returns list of account dicts
        # Find the funded account (USD/USDC or primary)
        for acct in accounts:
            if acct["currency"] in ["USD", "USDC"]:
                return {
                    "currency": acct["currency"],
                    "balance": acct["balance"]
                }
        return {"error": "No funded account found"}
    except Exception as e:
        logging.exception("Error fetching Coinbase balance")
        return {"error": str(e)}

@app.route("/accounts")
def accounts():
    balance_data = get_coinbase_balance()
    return jsonify(balance_data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
