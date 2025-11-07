# nija_app.py

import os, time
from flask import Flask, jsonify, request
from loguru import logger
from nija_client import CoinbaseAdvancedClient

# -------------------------------------------------
# Initialize Flask app
# -------------------------------------------------
app = Flask(__name__)

# -------------------------------------------------
# Initialize Coinbase Advanced client
# -------------------------------------------------
try:
    client = CoinbaseAdvancedClient()
    logger.info("Coinbase Advanced client initialized")
except Exception as e:
    logger.error(f"Failed to initialize Coinbase client: {e}")
    raise

# -------------------------------------------------
# ROUTES
# -------------------------------------------------

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

        # Record timestamp of last order for internal status tracking
        os.environ["NIJA_LAST_ORDER_TS"] = str(int(time.time()))

        return jsonify(order)
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return jsonify({"error": str(e)}), 500

# -------------------------------------------------
# INTERNAL STATUS ROUTE (safe)
# -------------------------------------------------

def get_last_order_ts():
    return os.getenv("NIJA_LAST_ORDER_TS")

@app.route("/internal/trading-status", methods=["GET"])
def trading_status():
    """Return safe internal trading status (no secrets)."""
    return jsonify({
        "live_trading_enabled": bool(os.getenv("LIVE_TRADING") in ("1", "true", "True")),
        "coinbase_api_key_present": bool(os.getenv("COINBASE_API_KEY")),
        "coinbase_pem_present": bool(os.getenv("COINBASE_PEM_CONTENT")),
        "coinbase_base": os.getenv("COINBASE_API_BASE") or "default",
        "last_order_ts": get_last_order_ts() or None,
        "service_time_utc": int(time.time())
    })

# -------------------------------------------------
# MAIN ENTRY
# -------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
