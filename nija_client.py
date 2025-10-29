# nija_client.py
import os
import logging
import time
from decimal import Decimal

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient imported successfully")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available. Using DummyClient")

# --- Dummy client for testing without live trades ---
class DummyClient:
    def get_accounts(self):
        logger.info("[NIJA-DUMMY] get_accounts called")
        # Returns a fake account balance
        return [{"currency": "USD", "balance": "1000"}]

    def place_order(self, product_id, side, price, size):
        logger.info(f"[NIJA-DUMMY] place_order called - {side} {size} {product_id} @ {price}")
        # Returns a fake order confirmation
        return {"id": "dummy_order_123", "status": "done"}

# --- Initialize client ---
if CoinbaseClient:
    try:
        COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
        COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
        COINBASE_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_PASSPHRASE,
            sandbox=False  # change to True for sandbox testing
        )
        logger.info("[NIJA] CoinbaseClient initialized. Live trading enabled.")
    except Exception as e:
        logger.exception("[NIJA] Failed to initialize CoinbaseClient. Falling back to DummyClient.")
        client = DummyClient()
else:
    client = DummyClient()

# --- Helper to check if client is live ---
def check_live_status():
    return isinstance(client, CoinbaseClient)
