# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
USE_DUMMY = False

try:
    from coinbase_advanced_py.client import CoinbaseClient as LiveCoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    LiveCoinbaseClient = None
    logger.warning("[NIJA] CoinbaseClient module not found. DummyClient will be used.")

# --- Define DummyClient fallback ---
class DummyClient:
    def __init__(self):
        logger.info("[NIJA] Initialized DummyClient (no live trades)")

    def buy(self, *args, **kwargs):
        logger.info(f"[DummyClient] Simulated BUY {args} {kwargs}")
        return {"status": "simulated_buy"}

    def sell(self, *args, **kwargs):
        logger.info(f"[DummyClient] Simulated SELL {args} {kwargs}")
        return {"status": "simulated_sell"}

# --- Check for API keys ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_SANDBOX = os.getenv("COINBASE_SANDBOX", "true").lower() == "true"

if not API_KEY or not API_SECRET or not API_PASSPHRASE or not LiveCoinbaseClient:
    logger.warning("[NIJA] Missing API keys or CoinbaseClient module — using DummyClient")
    USE_DUMMY = True

# --- Initialize client ---
if USE_DUMMY:
    CoinbaseClient = DummyClient()
    logger.info("[NIJA] Using DummyClient (no live trades)")
else:
    CoinbaseClient = LiveCoinbaseClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        passphrase=API_PASSPHRASE,
        sandbox=API_SANDBOX
    )
    logger.info("[NIJA] Live CoinbaseClient ready for trading")

# --- Expose client for imports ---
client = CoinbaseClient
