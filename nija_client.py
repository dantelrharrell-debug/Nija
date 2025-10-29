# nija_client.py
import os
import logging
import time
from decimal import Decimal

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Load API keys from environment variables ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# --- Define a DummyClient fallback ---
class DummyClient:
    def __init__(self):
        logger.warning("[NIJA] Using DummyClient — no live trading!")

    def get_account(self, *args, **kwargs):
        return {"balance": "0"}

    def place_order(self, *args, **kwargs):
        logger.info(f"[NIJA] Dummy order: {args}, {kwargs}")
        return {"id": "dummy_order"}

# --- Try importing and initializing CoinbaseClient ---
CoinbaseClient = None
client = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    if API_KEY and API_SECRET and API_PASSPHRASE:
        client = CoinbaseClient(
            api_key=API_KEY,
            api_secret=API_SECRET,
            passphrase=API_PASSPHRASE
        )
        logger.info("[NIJA] ✅ Live Coinbase client initialized — ready to trade!")
    else:
        logger.warning("[NIJA] Coinbase API keys missing. Falling back to DummyClient.")
        client = DummyClient()
except ModuleNotFoundError:
    logger.warning("[NIJA] coinbase_advanced_py not installed. Using DummyClient.")
    client = DummyClient()
except Exception as e:
    logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
    client = DummyClient()

# --- Optional helper functions ---
def get_balance():
    try:
        account = client.get_account()
        return Decimal(account.get("balance", 0))
    except Exception as e:
        logger.error(f"[NIJA] Failed to get balance: {e}")
        return Decimal(0)

def place_order(**kwargs):
    try:
        return client.place_order(**kwargs)
    except Exception as e:
        logger.error(f"[NIJA] Failed to place order: {e}")
        return {"error": str(e)}

logger.info("[NIJA] Client setup complete.")
