# nija_client.py
import os
import logging
from decimal import Decimal
import time

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- DummyClient as fallback ---
class DummyClient:
    def buy(self, **kwargs):
        logger.info(f"[DummyClient] Simulated BUY {kwargs}")
        return kwargs

    def sell(self, **kwargs):
        logger.info(f"[DummyClient] Simulated SELL {kwargs}")
        return kwargs

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient module not found")

# --- Load API credentials ---
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")

# --- Initialize client ---
if CoinbaseClient and API_KEY and API_SECRET and API_PASSPHRASE:
    try:
        client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)
        logger.info("[NIJA] CoinbaseClient initialized successfully. Live trading ENABLED ✅")
        USING_DUMMY = False
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
        logger.warning("[NIJA] Using DummyClient instead")
        client = DummyClient()
        USING_DUMMY = True
else:
    logger.warning("[NIJA] Missing API credentials or CoinbaseClient not available. Using DummyClient")
    client = DummyClient()
    USING_DUMMY = True

# --- Expose client ---
def get_client():
    return client

def is_dummy():
    return USING_DUMMY
