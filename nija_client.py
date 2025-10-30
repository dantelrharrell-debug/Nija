# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Load environment variables ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    if COINBASE_API_KEY and COINBASE_API_SECRET and COINBASE_API_PASSPHRASE:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_API_PASSPHRASE,
        )
        logger.info("[NIJA] CoinbaseClient initialized. Live trading ENABLED ✅")
    else:
        logger.warning("[NIJA] Missing Coinbase API credentials — using DummyClient")
        client = None
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient module not found — using DummyClient")
    client = None

# --- Fallback DummyClient ---
class DummyClient:
    def buy(self, **kwargs):
        logger.info(f"[DummyClient] Simulated BUY {kwargs}")

    def sell(self, **kwargs):
        logger.info(f"[DummyClient] Simulated SELL {kwargs}")

    def get_account(self, **kwargs):
        logger.info(f"[DummyClient] Simulated GET_ACCOUNT {kwargs}")
        return {}

# --- Use live client if available, else DummyClient ---
nija_client = client if client else DummyClient()

logger.info(f"[NIJA] Module ready. DRY_RUN={os.getenv('DRY_RUN', False)}, Using Dummy={client is None}")
