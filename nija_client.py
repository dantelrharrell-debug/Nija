# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Attempt to initialize CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient module loaded")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient module not found. Falling back to DummyClient")

# --- Load keys from Render environment variables ---
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
PASSPHRASE = os.environ.get("COINBASE_PASSPHRASE")

if API_KEY and API_SECRET and PASSPHRASE and CoinbaseClient:
    try:
        client = CoinbaseClient(API_KEY, API_SECRET, PASSPHRASE)
        logger.info("[NIJA] CoinbaseClient initialized using Render env variables ✅ Live trading enabled")
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
        client = None
else:
    logger.warning("[NIJA] CoinbaseClient not initialized or keys missing. Using DummyClient (simulated orders)")
    client = None

# --- Fallback DummyClient ---
class DummyClient:
    def place_order(self, **kwargs):
        logger.info(f"[DummyClient] Simulated order: {kwargs}")
        return kwargs

if client is None:
    client = DummyClient()
