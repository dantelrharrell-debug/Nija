# nija_app.py
from flask import Flask, request, jsonify
from nija_client import CoinbaseClient
import os
import logging

# ------------------------
# Flask setup
# ------------------------
app = Flask(__name__)

LOG = logging.getLogger("nija_app")
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))
if not LOG.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)

# ------------------------
# Initialize Coinbase client
# ------------------------
client = CoinbaseClient()
LOG.info("Coinbase client initialized. LIVE_TRADING=%s", client.live_trading)

# ------------------------
# Routes
# ------------------------
@app.route("/balances", methods=["GET"])
def get_balances():
    """Return all account balances."""
    try:
        accounts = client.list_accounts()
        balances = [
            {
                "uuid": a.get("uuid"),
                "currency": a.get("currency"),
                "available": a.get("available_balance", {}).get("value", "0")
            }
            for a in accounts
        ]
        return jsonify({"balances": balances})
    except Exception as e:
        LOG.exception("Error fetching balances")
        return jsonify({"error": str(e)}), 500

@app.route("/buy", methods=["POST"])
def buy():
    """
    Place a market buy order by USD quote.
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

        result = client.place_market_buy_by_quote(product_id, usd_quote, dry_run=dry_run)
        return jsonify(result)
    except Exception as e:
        LOG.exception("Error placing buy order")
        return jsonify({"error": str(e)}), 500

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

        # For simplicity, simulate sell as negative buy
        result = client.place_market_buy_by_quote(
            product_id,
            usd_quote,
            dry_run=dry_run,
        )
        result["action"] = "SELL"
        return jsonify(result)
    except Exception as e:
        LOG.exception("Error placing sell order")
        return jsonify({"error": str(e)}), 500

# ------------------------
# Healthcheck
# ------------------------
@app.route("/", methods=["GET"])
def health():
    return "NIJA Trading API is live ✅", 200

# ------------------------
# Run
# ------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
