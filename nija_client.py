# nija_client.py
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

try:
    from coinbase_advanced.client import Client
    logger.info("Imported coinbase_advanced successfully.")
except ModuleNotFoundError:
    Client = None
    logger.error("coinbase_advanced module not installed. Coinbase functions will be disabled.")

def test_coinbase_connection() -> bool:
    if Client is None:
        logger.warning("Coinbase client not available. Skipping connection test.")
        return False

    API_KEY = os.environ.get("COINBASE_API_KEY")
    API_SECRET = os.environ.get("COINBASE_API_SECRET")
    API_SUB = os.environ.get("COINBASE_API_SUB")

    if not (API_KEY and API_SECRET and API_SUB):
        logger.error("Missing Coinbase environment variables.")
        return False

    try:
        client = Client(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
        logger.info("Coinbase client instantiated successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to instantiate Coinbase client: {e}")
        return False
