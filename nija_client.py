import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

try:
    from coinbase_advanced.client import Client
    COINBASE_INSTALLED = True
except ModuleNotFoundError:
    logging.warning("coinbase_advanced module not installed. Live trading disabled.")
    Client = None
    COINBASE_INSTALLED = False

def test_coinbase_connection():
    if not COINBASE_INSTALLED:
        logging.warning("No Coinbase client available for connection test.")
        return False

    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB")
        )
        # Try a lightweight request to validate connection
        client.accounts.list()
        logging.info("Coinbase connection successful.")
        return True
    except Exception as e:
        logging.warning(f"Coinbase connection test failed: {e}")
        return False
