import os
import sys
import time
import logging
from decimal import Decimal

# --- Vendor coinbase client ---
sys.path.insert(0, os.path.join(os.getcwd(), "vendor"))

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# Try importing CoinbaseClient
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Coinbase client module available")
except ModuleNotFoundError:
    logger.warning("[NIJA] Coinbase client not found, using DummyClient")

# DummyClient for simulation if CoinbaseClient not found
class DummyClient:
    def buy(self, product_id, amount):
        logger.info(f"[DummyClient] Simulated BUY {{'amount': {amount}, 'product_id': '{product_id}'}}")
        return {"status": "simulated"}

# Initialize client
def get_client():
    if CoinbaseClient and os.getenv("TRADING_MODE") == "live":
        client = CoinbaseClient(
            api_key=os.getenv("COINBASE_API_KEY"),
            api_secret=os.getenv("COINBASE_API_SECRET"),
            api_passphrase=os.getenv("COINBASE_API_PASSPHRASE")
        )
        logger.info("[NIJA] Live trading client initialized ✅")
        return client
    else:
        logger.warning("[NIJA] Trading in simulation mode ❌")
        return DummyClient()

# Trading parameters
PRODUCT_ID = "BTC-USD"
MIN_POSITION = Decimal("0.02")  # 2% of equity
MAX_POSITION = Decimal("0.10")  # 10% of equity

# Example get account balance function
def get_balance():
    # Replace with real API call if using CoinbaseClient
    return Decimal("1000")  # USD placeholder

# Start trading loop
def start_trading():
    client = get_client()
    logger.info("[NIJA] Trading loop started...")

    while True:
        try:
            balance = get_balance()
            trade_size = max(MIN_POSITION, min(MAX_POSITION, Decimal("0.05")))  # 5% example
            amount_to_buy = balance * trade_size
            amount_to_buy = round(amount_to_buy / 29500, 6)  # example BTC price

            result = client.buy(PRODUCT_ID, float(amount_to_buy))
            logger.info(f"[NIJA] BUY executed: {amount_to_buy} BTC")
        except Exception as e:
            logger.error(f"[NIJA] Trading error: {e}")

        time.sleep(10)  # Run every 10 seconds
