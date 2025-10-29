# nija_client.py
import os
import logging
import time

logger = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
coinbase_available = False
try:
    from coinbase_advanced_py.client import CoinbaseClient
    coinbase_available = True
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available. Using DummyClient")

# --- Dummy client for dry-run or missing module ---
class DummyClient:
    def get_accounts(self):
        logger.info("[NIJA-DUMMY] get_accounts called")
        return [{"currency": "USD", "balance": "1000"}]

    def place_order(self, product_id, side, price, size):
        logger.info(f"[NIJA-DUMMY] place_order called: {side} {size} {product_id} at {price}")
        return {"id": "dummy_order", "status": "placed"}

# --- Initialize client ---
if coinbase_available:
    client = CoinbaseClient(
        api_key=os.getenv("COINBASE_API_KEY", ""),
        api_secret=os.getenv("COINBASE_API_SECRET", ""),
        api_passphrase=os.getenv("COINBASE_PASSPHRASE", ""),
        sandbox=os.getenv("DRY_RUN", "True").lower() == "true"
    )
else:
    client = DummyClient()

# --- Helper function to check if Coinbase is reachable ---
def check_live_status():
    if not coinbase_available:
        return False
    try:
        accounts = client.get_accounts()
        return True if accounts else False
    except Exception as e:
        logger.warning(f"[NIJA] Coinbase connection failed: {e}")
        return False
