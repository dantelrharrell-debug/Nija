# nija_client.py
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Try importing CoinbaseClient safely ---
try:
    from coinbase_advanced_py import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient imported successfully")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient unavailable, using DummyClient instead")
    class DummyClient:
        def __init__(self, *args, **kwargs):
            logger.info("[NIJA] DummyClient initialized (no real trading)")

        def place_order(self, *args, **kwargs):
            logger.info(f"[DummyClient] Simulated order: args={args}, kwargs={kwargs}")
            return {"status": "simulated"}

    CoinbaseClient = DummyClient

# --- Helper function ---
def get_usd_balance(client):
    """Fetch USD balance safely. Returns 0 if using DummyClient or on error."""
    try:
        return client.get_balance("USD")
    except Exception:
        logger.warning("[NIJA] Could not fetch real balance, returning 0")
        return 0
