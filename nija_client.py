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

# DummyClient for simulation
class DummyClient:
    def get_account_balance(self):
        return {"balance": 1000.0}  # placeholder USD balance

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
MIN_POSITION = Decimal("0.02")  # 2%
MAX_POSITION = Decimal("0.10")  # 10%
TRADE_INTERVAL = 10  # seconds

# Helper: Get USD balance
def get_usd_balance(client):
    try:
        if isinstance(client, DummyClient):
            return Decimal(client.get_account_balance()["balance"])
        accounts = client.get_accounts()
        for acct in accounts:
            if acct["currency"] == "USD":
                return Decimal(acct["available"])
        return Decimal("0")
    except Exception as e:
        logger.error(f"[NIJA] Failed to fetch balance: {e}")
        return Decimal("0")

# Calculate trade amount dynamically
def calculate_trade_amount(balance):
    # Randomly pick between MIN_POSITION and MAX_POSITION
    from random import uniform
    percent = Decimal(str(uniform(float(MIN_POSITION), float(MAX_POSITION))))
    return balance * percent

# Main trading loop
def start_trading():
    client = get_client()
    logger.info("[NIJA] Trading loop started...")

    while True:
        try:
            usd_balance = get_usd_balance(client)
            if usd_balance <= 0:
                logger.warning("[NIJA] USD balance zero, skipping trade")
                time.sleep(TRADE_INTERVAL)
                continue

            trade_usd = calculate_trade_amount(usd_balance)

            # Example BTC price; replace with real market price from CoinbaseClient if needed
            btc_price = Decimal("29500")
            btc_amount = (trade_usd / btc_price).quantize(Decimal("0.000001"))

            result = client.buy(PRODUCT_ID, float(btc_amount))
            logger.info(f"[NIJA] BUY executed: {btc_amount} BTC @ approx ${btc_price}")
        except Exception as e:
            logger.error(f"[NIJA] Trading error: {e}")

        time.sleep(TRADE_INTERVAL)
