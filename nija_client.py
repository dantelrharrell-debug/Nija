# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Try importing CoinbaseClient correctly ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not found; using DummyClient fallback")
    CoinbaseClient = None

# --- Read environment variables (Render Dashboard -> Environment tab) ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
PEM_PATH = os.getenv("COINBASE_PEM_PATH")  # optional if you’re using a PEM file
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# --- Initialize the Coinbase or Dummy client ---
class DummyClient:
    def place_order(self, **kwargs):
        logger.info(f"[DummyClient] Simulated order: {kwargs}")
        return {"status": "simulated", "order": kwargs}

client = None

if CoinbaseClient and API_KEY and API_SECRET and PASSPHRASE:
    try:
        client = CoinbaseClient(
            api_key=API_KEY,
            api_secret=API_SECRET,
            passphrase=PASSPHRASE,
            pem_path=PEM_PATH,
        )
        logger.info("[NIJA] CoinbaseClient initialized ✅ Live trading ready")
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
        client = DummyClient()
else:
    logger.warning("[NIJA] Missing API credentials — using DummyClient")
    client = DummyClient()

logger.info(f"[NIJA] Module ready. DRY_RUN={DRY_RUN}, Using Dummy={isinstance(client, DummyClient)}")
