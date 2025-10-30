# nija_client.py
import logging
import time
from decimal import Decimal

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Dummy client fallback ---
class DummyClient:
    def buy(self, **kwargs):
        logger.info(f"[DummyClient] Simulated BUY {kwargs}")
        return {"status": "simulated_buy", **kwargs}

    def sell(self, **kwargs):
        logger.info(f"[DummyClient] Simulated SELL {kwargs}")
        return {"status": "simulated_sell", **kwargs}

# --- Try importing CoinbaseClient ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient module found ✅")
except ModuleNotFoundError:
    CoinbaseClient = None
    logger.warning("[NIJA] CoinbaseClient module not found — using DummyClient")

# --- Direct live API keys ---
COINBASE_API_KEY = "YOUR_LIVE_API_KEY_HERE"
COINBASE_API_SECRET = "YOUR_LIVE_API_SECRET_HERE"
COINBASE_PASSPHRASE = "YOUR_LIVE_PASSPHRASE_HERE"

# --- Initialize client ---
if CoinbaseClient:
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_PASSPHRASE,
            sandbox=False  # True for sandbox mode
        )
        logger.info("[NIJA] CoinbaseClient initialized. Live trading ENABLED ✅")
    except Exception as e:
        logger.error(f"[NIJA] CoinbaseClient failed to initialize: {e}")
        logger.warning("[NIJA] Falling back to DummyClient ❌")
        client = DummyClient()
else:
    client = DummyClient()

# --- Example trade functions ---
def place_buy(amount, product_id):
    """Place a buy order."""
    try:
        response = client.buy(amount=amount, product_id=product_id)
        logger.info(f"[NIJA] BUY response: {response}")
        return response
    except Exception as e:
        logger.error(f"[NIJA] BUY failed: {e}")
        return None

def place_sell(amount, product_id):
    """Place a sell order."""
    try:
        response = client.sell(amount=amount, product_id=product_id)
        logger.info(f"[NIJA] SELL response: {response}")
        return response
    except Exception as e:
        logger.error(f"[NIJA] SELL failed: {e}")
        return None
