# nija_app.py
from flask import Flask, request, jsonify
import logging
from nija_client import CoinbaseClient  # your client class

# ------------------------
# Setup
# ------------------------
app = Flask(__name__)
LOG = logging.getLogger("nija_app")
LOG.setLevel(logging.INFO)
client = CoinbaseClient()  # initialize your Coinbase client

# ------------------------
# Existing routes
# ------------------------
@app.route("/")
def index():
    return "NIJA API is live!", 200

@app.route("/balances")
def balances():
    accounts = client.list_accounts()
    return jsonify(accounts)

@app.route("/buy", methods=["POST"])
def buy():
    # your existing buy route
    pass

# ------------------------
# NEW: Sell route
# ------------------------
@app.route("/sell", methods=["POST"])
def sell():
    """
    Place a market sell order by USD quote.
    JSON payload:
        {
            "product_id": "BTC-USD",
            "usd_quote": 10.0,
            "dry_run": true  # optional
        }
    """
    try:
        data = request.json
        product_id = data.get("product_id")
        usd_quote = float(data.get("usd_quote", 0))
        dry_run = data.get("dry_run")

        if not product_id or usd_quote <= 0:
            return jsonify({"error": "Invalid product_id or usd_quote"}), 400

        result = client.place_market_sell_by_quote(product_id, usd_quote, dry_run=dry_run)
        return jsonify(result)
    except Exception as e:
        LOG.exception("Error placing sell order")
        return jsonify({"error": str(e)}), 500

# ------------------------
# Run (if standalone)
# ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
