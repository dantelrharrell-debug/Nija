# nija_client.py
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Try importing real CoinbaseClient ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Using real CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available, using DummyClient instead")
    
    class DummyClient:
        def get_account_balance(self):
            return Decimal("0.0")
    
    CoinbaseClient = DummyClient

# --- USD balance helper ---
def get_usd_balance(client):
    try:
        return client.get_account_balance()
    except Exception as e:
        logger.warning(f"[NIJA] Failed to get USD balance: {e}")
        return Decimal("0.0")
