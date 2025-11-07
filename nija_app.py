# nija_app.py

import os, time, json
from flask import Flask, jsonify, request
from loguru import logger

# Optional: import your Coinbase client if implemented
# from nija_client import CoinbaseAdvancedClient

# -------------------------
# Initialize Flask app
# -------------------------
app = Flask(__name__)

# -------------------------
# Initialize Coinbase client (optional)
# -------------------------
client = None
try:
    # Uncomment if you have implemented the CoinbaseAdvancedClient
    # client = CoinbaseAdvancedClient()
    logger.info("Coinbase client initialized")
except Exception as e:
    logger.error(f"Failed to initialize Coinbase client: {e}")
    client = None

# -------------------------
# Last order timestamp persistence
# -------------------------
LAST_ORDER_FILE = "/tmp/nija_last_order.json"

def write_last_order_ts(ts):
    try:
        with open(LAST_ORDER_FILE, "w") as f:
            json.dump({"last_order_ts": int(ts)}, f)
    except Exception as e:
        logger.error(f"Failed to write last order file: {e}")

def read_last_order_ts():
    try:
        if os.path.exists(LAST_ORDER_FILE):
            with open(LAST_ORDER_FILE, "r") as f:
                data = json.load(f)
                return data.get("last_order_ts")
    except Exception as e:
        logger.error(f"Failed to read last order file: {e}")
    return None

# -------------------------
# Safe order wrapper (dry-run)
# -------------------------
def safe_place_order(side, product_id, size, price=None, order_type="market"):
    live = os.getenv("LIVE_TRADING") in ("1","true","True")
    dry = os.getenv("NIJA_DRY_RUN") in ("1","true","True")
    logger.info("Order request", side=side, product_id=product_id, size=size, order_type=order_type, live=live, dry=dry)

    if not live or dry or client is None:
        resp = {
            "id": f"dryrun-{int(time.time())}",
            "status": "simulated",
            "side": side,
            "product_id": product_id,
            "size": size,
            "order_type": order_type,
            "created_at": int(time.time())
        }
        write_last_order_ts(resp["created_at"])
        return resp

    # Real order path
    try:
        resp = client.place_order(side=side, product_id=product_id, size=size, price=price, order_type=order_type)
        write_last_order_ts(int(time.time()))
        return resp
    except Exception as e:
        logger.error(f"Error placing live order: {e}")
        raise

# -------------------------
# Routes
# -------------------------
@app.route("/")
def index():
    return "NIJA Trading Bot is live!"

@app.route("/accounts", methods=["GET"])
def accounts():
    if client is None:
        return jsonify({"error":"client not initialized"}), 500
    try:
        accounts_data = client.get_accounts()
        return jsonify(accounts_data)
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/trade", methods=["POST"])
def trade():
    """
    POST JSON example:
    {
      "side": "buy",
      "product_id": "BTC-USD",
      "size": "0.00001",
      "order_type": "market",
      "price": "30000"  # optional
    }
    """
    data = request.get_json(force=True, silent=True) or {}
    side = data.get("side")
    product_id = data.get("product_id")
    size = data.get("size")
    order_type = data.get("order_type", "market")
    price = data.get("price")

    if not all([side, product_id, size]):
        return jsonify({"error":"Missing required parameters: side, product_id, size"}), 400

    try:
        order_resp = safe_place_order(side, product_id, size, price, order_type)
        return jsonify(order_resp)
    except Exception as e:
        logger.exception("Failed to place order")
        return jsonify({"error": str(e)}), 500

@app.route("/internal/trading-status", methods=["GET"])
def trading_status():
    return jsonify({
        "live_trading_enabled": bool(os.getenv("LIVE_TRADING") in ("1","true","True")),
        "coinbase_api_key_present": bool(os.getenv("COINBASE_API_KEY")),
        "coinbase_pem_present": bool(os.getenv("COINBASE_PEM_CONTENT")),
        "coinbase_base": os.getenv("COINBASE_API_BASE") or "default",
        "last_order_ts": read_last_order_ts(),
        "service_time_utc": int(time.time())
    })

# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
