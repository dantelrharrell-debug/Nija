# nija_client.py
import os
import logging
from decimal import Decimal
import time

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Load environment variables ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# --- Coinbase import ---
CoinbaseClient = None
USE_DUMMY = True

try:
    from coinbase_advanced_py.client import CoinbaseClient as _CoinbaseClient
    logger.info("[NIJA] CoinbaseClient module imported successfully")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient module not found. DummyClient will be used.")
    _CoinbaseClient = None

# --- Attempt live client initialization ---
if _CoinbaseClient and COINBASE_API_KEY and COINBASE_API_SECRET:
    try:
        CoinbaseClient = _CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_API_PASSPHRASE
        )
        USE_DUMMY = False
        logger.info("[NIJA] CoinbaseClient initialized successfully. Live trading enabled!")
    except Exception as e:
        logger.error(f"[NIJA] CoinbaseClient failed to initialize: {e}")
        CoinbaseClient = None
        USE_DUMMY = True
else:
    logger.warning("[NIJA] Missing API keys or CoinbaseClient module — using DummyClient.")

# --- Dummy client for safe fallback ---
class DummyClient:
    def buy(self, *args, **kwargs):
        logger.info(f"[NIJA][DummyClient] Simulated BUY {args} {kwargs}")
        return {"status": "simulated"}

    def sell(self, *args, **kwargs):
        logger.info(f"[NIJA][DummyClient] Simulated SELL {args} {kwargs}")
        return {"status": "simulated"}

# --- Final client assignment ---
if USE_DUMMY:
    CoinbaseClient = DummyClient()
    logger.info("[NIJA] Using DummyClient (no live trades)")
else:
    logger.info("[NIJA] Live CoinbaseClient ready")

# --- Example function to test ---
def test_connection():
    global CoinbaseClient, USE_DUMMY  # <-- global declared here correctly
    if USE_DUMMY:
        logger.info("[NIJA] Running test on DummyClient")
    else:
        try:
            accounts = CoinbaseClient.get_accounts()  # example method
            logger.info(f"[NIJA] Coinbase accounts loaded: {accounts}")
        except Exception as e:
            logger.error(f"[NIJA] Error fetching accounts: {e}")
            logger.warning("[NIJA] Switching to DummyClient")
            CoinbaseClient = DummyClient()
            USE_DUMMY = True
