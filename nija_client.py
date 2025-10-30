# nija_client.py
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# Default to None
CoinbaseClient = None

# Try importing the real Coinbase client
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient successfully imported.")
except ModuleNotFoundError:
    logger.warning("[NIJA] coinbase_advanced_py not installed in venv. DummyClient will be used.")
    CoinbaseClient = None

# Dummy client in case real client is unavailable
class DummyClient:
    def place_order(self, *args, **kwargs):
        logger.info(f"[NIJA] DummyClient.place_order called -> {kwargs}")
        return {"status": "simulated", "details": kwargs}

# Decide which client to attach
if CoinbaseClient:
    try:
        client = CoinbaseClient(
            api_key=os.getenv("COINBASE_API_KEY"),
            api_secret=os.getenv("COINBASE_API_SECRET"),
            api_passphrase=os.getenv("COINBASE_API_PASSPHRASE"),
        )
        logger.info("[NIJA] CoinbaseClient attached -> live trading active")
    except Exception as e:
        logger.error(f"[NIJA] Failed to attach CoinbaseClient, using DummyClient instead: {e}")
        client = DummyClient()
else:
    client = DummyClient()
    logger.info("[NIJA] DummyClient attached -> simulated trading active")
