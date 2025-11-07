# nija_app.py
from flask import Flask, jsonify, request
from nija_client import CoinbaseClient
import os

# Initialize Flask app
app = Flask(__name__)

# Environment flag for live trading
LIVE_TRADING = True  # Always live now, no dry runs

# --- ROUTE: Health check ---
@app.route("/", methods=["GET", "HEAD"])
def home():
    return "NIJA Trading Bot is live!", 200

# --- ROUTE: Check Coinbase account balances ---
@app.route("/check_accounts", methods=["GET"])
def check_accounts():
    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()
        balances = {acct['currency']: acct['balance'] for acct in accounts}

        # Detect if request is from browser
        user_agent = request.headers.get("User-Agent", "").lower()
        is_browser = any(browser in user_agent for browser in ["mozilla", "chrome", "safari", "edge"])

        if is_browser:
            html = "<h2>Coinbase Account Balances</h2><table border='1' style='border-collapse: collapse;'>"
            html += "<tr><th>Currency</th><th>Balance</th></tr>"
            for currency, balance in balances.items():
                html += f"<tr><td>{currency}</td><td>{balance}</td></tr>"
            html += "</table>"
            return html
        else:
            return jsonify({"status": "success", "balances": balances})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- ROUTE: Place a trade (LIVE ONLY) ---
@app.route("/place_trade", methods=["POST"])
def place_trade():
    """
    Place a trade via Coinbase.
    JSON payload example:
    {
        "side": "buy",          # "buy" or "sell"
        "product_id": "BTC-USD",
        "size": "0.001"         # amount in base currency
    }
    """
    try:
        data = request.get_json()
        side = data.get("side")
        product_id = data.get("product_id")
        size = data.get("size")

        if not all([side, product_id, size]):
            return jsonify({"status": "error", "message": "Missing parameters"}), 400

        client = CoinbaseClient()
        order = client.place_order(side=side, product_id=product_id, size=size)
        return jsonify({"status": "success", "order": order})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Run the app (for local testing)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
