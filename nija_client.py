# nija_client.py
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

try:
    from coinbase_advanced_py.client import CoinbaseClient
    COINBASE_AVAILABLE = True
    logger.info("[NIJA] CoinbaseClient loaded")
except ModuleNotFoundError:
    CoinbaseClient = None
    COINBASE_AVAILABLE = False
    logger.warning("[NIJA] coinbase_advanced_py not found, using DummyClient")

class DummyClient:
    def place_order(self, *args, **kwargs):
        logger.info("[NIJA] Dummy order executed")
        return {"status": "dummy"}

# Initialize client
client = CoinbaseClient() if COINBASE_AVAILABLE else DummyClient()
