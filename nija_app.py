# nija_app.py
from flask import Flask, jsonify, request
import os

# --- MOCK COINBASE CLIENT (temporary for live deploy) ---
class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

    def get_accounts(self):
        # Replace this with real Coinbase API call when ready
        return [
            {"currency": "BTC", "balance": "0.001"},
            {"currency": "USD", "balance": "1000"}
        ]

    def place_order(self, side, product_id, size, type="market"):
        # Simulated order for dry-run
        return {"side": side, "product_id": product_id, "size": size, "type": type, "status": "simulated"}

# --- FLASK APP ---
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
        if request.headers.get("Accept", "").lower() == "application/json":
            return jsonify({"status": "error", "message": str(e)}), 500
        return f"<p>Error: {str(e)}</p>", 500

# --- ROUTE: Place a trade ---
@app.route("/place_trade", methods=["POST"])
def place_trade():
    try:
        data = request.get_json()
        side = data.get("side")
        product_id = data.get("product_id")
        size = data.get("size")

        if not all([side, product_id, size]):
            return jsonify({"status": "error", "message": "Missing parameters"}), 400

        client = CoinbaseClient()

        if LIVE_TRADING:
            # Replace with real API call when ready
            order = client.place_order(side=side, product_id=product_id, size=size)
            return jsonify({"status": "success", "order": order})
        else:
            # Dry run mode
            return jsonify({
                "status": "dry_run",
                "message": f"Trade simulated: {side} {size} {product_id}"
            })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Run the app (for local testing)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
