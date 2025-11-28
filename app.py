# app.py (or main Flask file)
from flask import Flask, jsonify
import os
import logging

app = Flask(__name__)

# Optional: existing imports
try:
    from nija_client import test_coinbase_connection
except ModuleNotFoundError:
    logging.warning("nija_client module not found")

# --- PLACE THE LIVE CHECK ROUTE HERE ---
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed.")

@app.route("/check_coinbase_live")
def check_coinbase_live():
    if Client is None:
        return jsonify({"status": "error", "message": "coinbase_advanced module not installed."}), 500

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    live_trading_flag = os.environ.get("LIVE_TRADING", "0")  # expected "1" if live trading enabled

    if not api_key or not api_secret:
        return jsonify({"status": "error", "message": "Coinbase API key or secret not set."}), 500

    live_trading = live_trading_flag == "1"

    try:
        client = Client(api_key=api_key, api_secret=api_secret)
        accounts = client.get_accounts()  # fetch balances
        balances = {a['currency']: a['balance'] for a in accounts}
        return jsonify({
            "status": "success",
            "live_trading": live_trading,
            "balances": balances
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- END ROUTE ---

# Optional: run app directly (Gunicorn will handle this in production)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
