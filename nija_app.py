# nija_app.py
import os
import time
import json
from flask import Flask, jsonify
from loguru import logger
from nija_client import CoinbaseClient

# -----------------------
# Flask App Setup
# -----------------------
app = Flask(__name__)

# -----------------------
# Initialize Coinbase Client
# -----------------------
try:
    client = CoinbaseClient()
except Exception as e:
    logger.error(f"Failed to initialize CoinbaseClient: {e}")
    raise

# -----------------------
# Trading Parameters
# -----------------------
PRODUCT_ID = os.getenv("TRADE_PRODUCT", "BTC-USD")
TRADE_SIZE = float(os.getenv("TRADE_SIZE", 0.001))  # Adjust for your risk

# -----------------------
# Trading Function
# -----------------------
def trade_live():
    try:
        accounts = client.get_accounts()
        logger.info(f"Accounts fetched: {accounts}")

        # Example: Simple buy market order logic
        order_response = client.place_order(
            product_id=PRODUCT_ID,
            side="buy",
            size=TRADE_SIZE,
            order_type="market"
        )
        logger.success(f"Live trade executed: {order_response}")
        return order_response

    except Exception as e:
        logger.error(f"Live trade failed: {e}")
        return {"error": str(e)}

# -----------------------
# Flask Routes
# -----------------------
@app.route("/")
def home():
    return jsonify({"status": "NIJA trading bot live ✅"})

@app.route("/trade")
def trade():
    result = trade_live()
    return jsonify(result)

# -----------------------
# Auto Start Trading on Deploy
# -----------------------
if __name__ == "__main__":
    logger.info("NIJA trading bot starting live...")
    
    # Optional: Start a single trade on deploy
    trade_live()

    # Run Flask app (Render expects this)
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
