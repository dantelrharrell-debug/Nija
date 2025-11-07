# nija_app.py
from flask import Flask, request, jsonify
from nija_client import CoinbaseClient
import logging
import os

LOG = logging.getLogger("nija_app")
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
if not LOG.handlers:
    LOG.addHandler(handler)

app = Flask(__name__)
client = CoinbaseClient()

# ------------------------
# Routes
# ------------------------
@app.route("/")
def index():
    return "NIJA trading bot live!"

@app.route("/buy", methods=["POST"])
def buy():
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
