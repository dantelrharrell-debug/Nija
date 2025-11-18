import time
import logging
from flask import Flask, request, abort
from nija_client import CoinbaseClient
import os
import hmac
import hashlib

# ----------------------
# Configuration
# ----------------------
TRADING_ACCOUNT_ID = "14f3af21-7544-412c-8409-98dc92cd2eec"
LIVE_TRADING = True
CHECK_INTERVAL = 10  # seconds for fallback checks if needed

TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET")  # your TradingView webhook secret

# Initialize Coinbase client
coinbase_client = CoinbaseClient(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret_path=os.getenv("COINBASE_API_SECRET_PATH"),
    api_passphrase=os.getenv("COINBASE_API_PASSPHRASE", ""),
    api_sub=os.getenv("COINBASE_API_SUB"),
)

# Flask app for webhook
app = Flask(__name__)

# ----------------------
# Functions
# ----------------------
def verify_webhook(request):
    """
    Verifies TradingView webhook using HMAC secret.
    """
    signature = request.headers.get("X-Signature")
    if not signature:
        return False

    body = request.get_data()
    computed_hmac = hmac.new(TV_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_hmac, signature)


def place_order(symbol: str, side: str, size: float):
    """
    Executes a market order on Coinbase.
    """
    if not LIVE_TRADING:
        logging.info(f"Dry run: would place {side} order for {size} {symbol}")
        return None

    try:
        order = coinbase_client.create_order(
            account_id=TRADING_ACCOUNT_ID,
            product_id=symbol,
            side=side,
            type="market",
            size=str(size)
        )
        logging.info(f"✅ Order executed: {order}")
        return order
    except Exception as e:
        logging.error(f"❌ Failed to place order for {symbol} ({side} {size}): {e}")
        return None


# ----------------------
# Webhook Endpoint
# ----------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    if TV_WEBHOOK_SECRET and not verify_webhook(request):
        logging.warning("❌ Invalid webhook signature")
        return abort(403)

    data = request.json
    symbol = data.get("symbol")
    side = data.get("side")
    size = data.get("size")

    if not (symbol and side and size):
        logging.warning(f"Incomplete signal received: {data}")
        return "Missing fields", 400

    place_order(symbol, side, size)
    return "Order received", 200


# ----------------------
# Main
# ----------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logging.info("🚀 Starting Coinbase Trading Bot with TradingView Webhook")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
