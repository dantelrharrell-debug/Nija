# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Attempt to import CoinbaseClient ---
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

# --- Initialize client ---
client = None
if API_KEY and API_SECRET and PASSPHRASE and CoinbaseClient:
    try:
        client = CoinbaseClient(API_KEY, API_SECRET, PASSPHRASE)
        logger.info("[NIJA] CoinbaseClient initialized using Render env variables ✅ Live trading enabled")
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
        client = None

# --- Fallback to DummyClient only if live client failed ---
class DummyClient:
    def place_order(self, **kwargs):
        logger.info(f"[DummyClient] Simulated order: {kwargs}")
        return kwargs

if client is None:
    logger.warning("[NIJA] CoinbaseClient not initialized or keys missing. Using DummyClient (simulated orders)")
    client = DummyClient()

# --- Sanity check: prevent silent DummyClient if keys exist but import failed ---
if isinstance(client, DummyClient) and (API_KEY and API_SECRET and PASSPHRASE):
    logger.error("[NIJA] WARNING: Keys detected but CoinbaseClient could not be imported! Check package version and import path.")
