# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Load environment variables for Coinbase ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
COINBASE_SANDBOX = os.getenv("COINBASE_SANDBOX", "False").lower() == "true"

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient module found")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient module not found")

# --- Dummy client as fallback ---
class DummyClient:
    def __init__(self, *args, **kwargs):
        logger.info("[NIJA] Using DummyClient (no live trades)")
    def place_order(self, *args, **kwargs):
        logger.info(f"[DummyClient] Simulated order: {args}, {kwargs}")
    def get_balance(self):
        return {"USD": 1000, "BTC": 0}

# --- Initialize client ---
client = None
if CoinbaseClient and COINBASE_API_KEY and COINBASE_API_SECRET and COINBASE_PASSPHRASE:
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_PASSPHRASE,
            sandbox=COINBASE_SANDBOX
        )
        logger.info("[NIJA] CoinbaseClient initialized. Live trading ENABLED ✅")
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
        client = DummyClient()
else:
    if not CoinbaseClient:
        logger.warning("[NIJA] CoinbaseClient module missing, using DummyClient")
    else:
        logger.warning("[NIJA] Missing API credentials, using DummyClient")
    client = DummyClient()

# --- Export client ---
__all__ = ["client"]
