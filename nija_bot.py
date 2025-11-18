import os
import json
from flask import Flask, request, jsonify
from loguru import logger
import threading
import time

# ------------------------------
# Coinbase Client Setup
# ------------------------------
COINBASE_AVAILABLE = False
try:
    from coinbase_advanced_py.client import AdvancedClient
    COINBASE_AVAILABLE = True
    logger.info("✅ Coinbase Advanced SDK import succeeded")
except ImportError:
    logger.warning("⚠️ Coinbase Advanced SDK not installed, using MockClient")

PEM = os.environ.get("COINBASE_PEM_CONTENT")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

# ------------------------------
# Mock client (dry-run fallback)
# ------------------------------
class MockClient:
    def get_accounts(self):
        logger.info("MockClient.get_accounts() called — returning simulated account")
        return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

    def place_order(self, *args, **kwargs):
        logger.info(f"MockClient.place_order() called with args={args}, kwargs={kwargs}")
        return {"status": "simulated"}

# ------------------------------
# Get Coinbase client
# ------------------------------
def get_coinbase_client(pem=None, org_id=None):
    """
    Returns a live AdvancedClient if SDK is available and PEM/org_id are provided,
    otherwise falls back to MockClient.
    """
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

# ------------------------------
# Bot Logic
# ------------------------------
client = get_coinbase_client(PEM, ORG_ID)

def fetch_accounts():
    try:
        accounts = client.get_accounts()
        logger.info(f"Accounts fetched: {accounts}")
        return accounts
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
        return []

def place_order(product_id, side, price, size):
    try:
        result = client.place_order(product_id=product_id, side=side, price=price, size=size)
        logger.info(f"Order result: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to place order: {e}")
        return {"status": "error", "error": str(e)}

# ------------------------------
# Flask Webhook Server
# ------------------------------
app = Flask(__name__)
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "mysecret")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data or data.get("secret") != WEBHOOK_SECRET:
        logger.warning("Unauthorized webhook attempt")
        return jsonify({"status": "unauthorized"}), 403

    symbol = data.get("symbol")
    side = data.get("side")
    price = data.get("price")
    risk_pct = data.get("risk_pct", 0.01)

    # Basic risk sizing logic
    accounts = fetch_accounts()
    usd_balance = float(accounts[0]["balance"]) if accounts else 1000
    size = usd_balance * risk_pct / price

    logger.info(f"Webhook received: {data}")
    order_result = place_order(symbol, side, price, round(size, 6))
    return jsonify(order_result)

# ------------------------------
# Background 24/7 Bot Loop
# ------------------------------
def run_bot_loop():
    while True:
        logger.info("Bot heartbeat: running 24/7...")
        fetch_accounts()
        time.sleep(60)  # Every minute

# ------------------------------
# Main
# ------------------------------
if __name__ == "__main__":
    logger.info("🚀 Starting Nija bot with TradingView webhook...")
    threading.Thread(target=run_bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
