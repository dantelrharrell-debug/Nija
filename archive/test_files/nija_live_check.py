# --- nija_live_trade_test.py ---
import os
import logging
from nija_client import CoinbaseClient

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- Environment Variables ---
LIVE_TRADING = os.getenv("LIVE_TRADING", "0") == "1"
TEST_ORDER_FUNDS = 1  # $1 test order

# --- Initialize Coinbase Client ---
try:
    client = CoinbaseClient()
    logging.info("✅ Coinbase client initialized successfully")
except Exception as e:
    logging.error(f"❌ Failed to initialize Coinbase client: {e}")
    exit(1)

# --- Fetch and print account balances ---
try:
    accounts = client.get_accounts()
    logging.info("⚡ Fetching account balances from funded account:")
    for acc in accounts:
        balance = float(acc['balance'])
        if balance > 0:
            logging.info(f"💰 {acc['currency']}: {balance}")
except Exception as e:
    logging.error(f"❌ Failed to fetch accounts: {e}")
    exit(1)

# --- Check live trading mode ---
if LIVE_TRADING:
    logging.info("⚡ Live trading mode is ACTIVE")
else:
    logging.warning("⚠️ LIVE_TRADING flag not set — bot is in PAPER mode")
    exit(1)  # Stop if not live

# --- Place a tiny live test order ---
try:
    test_order = {
        "product_id": "BTC-USD",  # BTC/USD pair
        "side": "buy",
        "type": "market",
        "funds": str(TEST_ORDER_FUNDS)
    }

    result = client.place_order(**test_order)
    logging.info(f"✅ Tiny live order executed successfully: {result}")
except Exception as e:
    logging.error(f"❌ Failed to execute live test order: {e}")

# --- Verify order filled ---
try:
    order_id = result.get('id')
    if order_id:
        order_status = client.get_order(order_id)
        logging.info(f"⚡ Order status: {order_status}")
except Exception as e:
    logging.warning(f"⚠️ Could not fetch order status: {e}")

logging.info("✅ Live trade test script completed successfully")
