# nija_client.py
import os
import sys
import logging
import time
from decimal import Decimal

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Environment Variables ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
SANDBOX = os.getenv("SANDBOX", "True").lower() == "true"

# --- DummyClient fallback ---
class DummyClient:
    def get_accounts(self):
        logger.warning("[NIJA] Using DummyClient: returning empty account list")
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("[NIJA] Using DummyClient: pretend order placed")
        return {"status": "dummy"}

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available. Using DummyClient")
    CoinbaseClient = None

# --- Initialize client ---
if CoinbaseClient and COINBASE_API_KEY and COINBASE_PEM_PATH:
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            pem_path=COINBASE_PEM_PATH,
            sandbox=SANDBOX
        )
        logger.info("[NIJA] CoinbaseClient initialized successfully")
    except Exception as e:
        logger.exception("[NIJA] Failed to initialize CoinbaseClient. Using DummyClient instead.")
        client = DummyClient()
else:
    client = DummyClient()
    if not CoinbaseClient:
        logger.warning("[NIJA] CoinbaseClient not imported, using DummyClient")
    elif not COINBASE_API_KEY or not COINBASE_PEM_PATH:
        logger.warning("[NIJA] Coinbase API credentials missing, using DummyClient")

# --- Health check utility ---
def check_live_status():
    """
    Returns True if Coinbase client is live and accounts can be fetched.
    """
    try:
        accounts = client.get_accounts()
        if accounts:
            logger.info("[NIJA] Coinbase client live with accounts available")
        else:
            logger.info("[NIJA] Coinbase client live but no accounts found")
        return True
    except Exception as e:
        logger.exception("[NIJA] Coinbase client not live")
        return False
