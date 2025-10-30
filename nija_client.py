import os
import logging
from decimal import Decimal
import time

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

LIVE_MODE = os.getenv("TRADING_MODE", "simulation") == "live"

if LIVE_MODE:
    try:
        from coinbase_advanced_py.client import CoinbaseClient
        client = CoinbaseClient(
            api_key=os.getenv("COINBASE_API_KEY"),
            api_secret=os.getenv("COINBASE_API_SECRET"),
            passphrase=os.getenv("COINBASE_API_PASSPHRASE"),
            sandbox=False
        )
        logger.info("[NIJA] CoinbaseClient loaded, LIVE trading enabled")
    except ModuleNotFoundError:
        logger.error("[NIJA] CoinbaseClient not found, fallback to DummyClient")
        from dummy_client import DummyClient
        client = DummyClient()
else:
    from dummy_client import DummyClient
    client = DummyClient()
    logger.warning("[NIJA] Trading in simulation mode")

# --- Trading loop ---
def run_trading_loop():
    logger.info("[NIJA] Trading loop started...")
    while True:
        # Example: buy 0.001 BTC every 10 seconds
        amount = Decimal("0.001")
        product_id = "BTC-USD"
        result = client.buy(amount=amount, product_id=product_id)
        logger.info(f"[NIJA] BUY executed: {amount} BTC @ ${result.get('price', 'unknown')}")
        time.sleep(10)

if __name__ == "__main__":
    run_trading_loop()
