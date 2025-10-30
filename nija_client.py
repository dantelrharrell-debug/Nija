import os
import logging
import threading
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Load environment variables ---
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")
TRADING_MODE = os.environ.get("TRADING_MODE", "dry_run").lower()

# --- Coinbase Client Initialization ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    if all([API_KEY, API_SECRET, API_PASSPHRASE]) and TRADING_MODE == "live":
        client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
        logger.info("[NIJA] Coinbase client initialized -> LIVE trading active")
    else:
        raise ValueError("API keys missing or TRADING_MODE not live")
except Exception as e:
    logger.warning(f"[NIJA] Coinbase client not available ({e}). Using DummyClient.")
    class DummyClient:
        def buy(self, *args, **kwargs):
            logger.info(f"[DummyClient] Simulated BUY {kwargs}")
        def sell(self, *args, **kwargs):
            logger.info(f"[DummyClient] Simulated SELL {kwargs}")
    client = DummyClient()

# --- Simple Nija trading strategy ---
def trading_loop():
    """
    Example live trading loop.
    Replace the placeholder logic below with your actual Nija strategy.
    """
    logger.info("[NIJA] Trading loop started...")
    while True:
        try:
            # Example placeholders — replace with VWAP, RSI, or Nija signals
            market_signal = "buy" if datetime.now().second % 2 == 0 else "sell"
            amount = 0.01  # BTC or ETH, adjust per your strategy

            if market_signal == "buy":
                client.buy(amount=amount, product_id="BTC-USD")
                logger.info(f"[NIJA] BUY executed: {amount} BTC")
            else:
                client.sell(amount=amount, product_id="BTC-USD")
                logger.info(f"[NIJA] SELL executed: {amount} BTC")

            time.sleep(10)  # Wait 10 seconds between signals (adjust as needed)
        except Exception as e:
            logger.error(f"[NIJA] Trading error: {e}")
            time.sleep(5)

# --- Start trading in background thread ---
threading.Thread(target=trading_loop, daemon=True).start()
