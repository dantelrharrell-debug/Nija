# nija_app.py
import os
from flask import Flask, jsonify, request
from loguru import logger
from nija_client import CoinbaseAdvancedClient

# Initialize Flask app
app = Flask(__name__)

# Initialize Coinbase Advanced client
try:
    client = CoinbaseAdvancedClient()
except Exception as e:
    logger.error(f"Failed to initialize Coinbase client: {e}")
    raise

@app.route("/")
def index():
    return "NIJA Trading Bot is live!"

@app.route("/accounts", methods=["GET"])
def accounts():
    try:
        accounts_data = client.get_accounts()
        return jsonify(accounts_data)
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/trade", methods=["POST"])
def trade():
    """
    POST JSON body example:
    {
        "side": "buy",
        "product_id": "BTC-USD",
        "size": "0.001",
        "order_type": "market",
        "price": "30000"  # optional for market orders
    }
    """
    try:
        data = request.json
        side = data.get("side")
        product_id = data.get("product_id")
        size = data.get("size")
        order_type = data.get("order_type", "market")
        price = data.get("price")

        if not all([side, product_id, size]):
            return jsonify({"error": "Missing required parameters"}), 400

        order = client.place_order(side, product_id, size, price, order_type)
        return jsonify(order)
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
