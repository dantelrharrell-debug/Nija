# nija_app.py
from flask import Flask, jsonify, request
from nija_client import CoinbaseClient  # Your existing Coinbase client
import os

# Initialize Flask app
app = Flask(__name__)

# Environment flags
LIVE_TRADING = os.getenv("LIVE_TRADING", "0") == "1"
NIJA_DRY_RUN = os.getenv("NIJA_DRY_RUN", None)

# --- ROUTE: Health check ---
@app.route("/", methods=["GET", "HEAD"])
def home():
    return "NIJA Trading Bot is live!", 200

# --- ROUTE: Check Coinbase account balances ---
@app.route("/check_accounts", methods=["GET"])
def check_accounts():
    """
    Returns Coinbase account balances.
    - JSON for API requests (default)
    - Simple HTML page if accessed via browser
    """
    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()
        balances = {acct['currency']: acct['balance'] for acct in accounts}

        # Detect if request is from browser
        user_agent = request.headers.get("User-Agent", "").lower()
        is_browser = any(browser in user_agent for browser in ["mozilla", "chrome", "safari", "edge"])

        if is_browser:
            # Simple HTML table for browsers
            html = "<h2>Coinbase Account Balances</h2><table border='1' style='border-collapse: collapse;'>"
            html += "<tr><th>Currency</th><th>Balance</th></tr>"
            for currency, balance in balances.items():
                html += f"<tr><td>{currency}</td><td>{balance}</td></tr>"
            html += "</table>"
            return html
        else:
            # JSON for API calls
            return jsonify({"status": "success", "balances": balances})

    except Exception as e:
        if request.headers.get("Accept", "").lower() == "application/json":
            return jsonify({"status": "error", "message": str(e)}), 500
        return f"<p>Error: {str(e)}</p>", 500

# --- Add your trading endpoints here ---
# Example: /place_order, /get_positions, etc. (use CoinbaseClient methods)

# Run the app (for local testing; in Render, gunicorn handles this)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
