import os
import time
from flask import Flask, request, jsonify
from loguru import logger

# --------------------------------
# Environment
# --------------------------------
PEM = os.environ.get("COINBASE_PEM_CONTENT")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")  # secure TradingView webhook key

# --------------------------------
# Coinbase Advanced SDK
# --------------------------------
COINBASE_AVAILABLE = False
try:
    from coinbase_advanced_py.client import AdvancedClient
    COINBASE_AVAILABLE = True
    logger.info("✅ Coinbase Advanced SDK import succeeded")
except ImportError:
    COINBASE_AVAILABLE = False
    logger.warning("⚠️ Coinbase Advanced SDK not installed, using MockClient")

# --------------------------------
# MockClient
# --------------------------------
class MockClient:
    def get_accounts(self):
        logger.info("MockClient.get_accounts() called — returning simulated account")
        return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

    def place_order(self, *args, **kwargs):
        logger.info(f"MockClient.place_order() called with args={args}, kwargs={kwargs}")
        return {"status": "simulated"}

# --------------------------------
# Coinbase client
# --------------------------------
def get_coinbase_client(pem=None, org_id=None):
    if COINBASE_AVAILABLE and pem and org_id:
        try:
            client = AdvancedClient(pem=pem, org_id=org_id)
            logger.info("✅ Live Coinbase Advanced client instantiated")
            return client
        except Exception as e:
            logger.error(f"❌ Failed to instantiate AdvancedClient: {e}")
            return MockClient()
    else:
        logger.warning("⚠️ Coinbase Advanced client unavailable, using MockClient")
        return MockClient()

# --------------------------------
# Flask app for TradingView alerts
# --------------------------------
app = Flask(__name__)
client = get_coinbase_client(PEM, ORG_ID)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    secret = data.get("secret")
    if secret != WEBHOOK_SECRET:
        logger.warning("❌ Unauthorized webhook call")
        return jsonify({"error": "Unauthorized"}), 403

    try:
        symbol = data["symbol"]      # e.g., BTC-USD
        side = data["side"]          # buy or sell
        size = data["size"]          # e.g., 0.001
        price = data.get("price")    # optional limit price
    except KeyError:
        logger.error("❌ Malformed webhook payload")
        return jsonify({"error": "Malformed payload"}), 400

    try:
        order = client.place_order(
            product_id=symbol,
            side=side,
            size=size,
            price=price
        )
        logger.info(f"✅ Order executed: {order}")
        return jsonify({"status": "success", "order": order}), 200
    except Exception as e:
        logger.error(f"❌ Failed to place order: {e}")
        return jsonify({"error": str(e)}), 500

# --------------------------------
# Run bot & Flask server
# --------------------------------
if __name__ == "__main__":
    logger.info("🚀 Starting Nija bot with TradingView webhook...")
    # Run Flask server on port 5000 (Railway auto-maps to your app)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
