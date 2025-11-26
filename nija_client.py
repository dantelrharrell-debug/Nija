# nija_client.py
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Try to import Coinbase client
try:
    from coinbase_advanced.client import Client
    COINBASE_AVAILABLE = True
except ModuleNotFoundError:
    Client = None
    COINBASE_AVAILABLE = False
    logging.warning("coinbase_advanced module not installed. Live trading disabled.")

# Load credentials from environment variables
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_SUB = os.environ.get("COINBASE_API_SUB")

def test_coinbase_connection():
    if not COINBASE_AVAILABLE:
        logging.warning("No Coinbase client available for connection test.")
        return False
    if not API_KEY or not API_SECRET or not API_SUB:
        logging.warning("Coinbase API credentials missing. Live trading disabled.")
        return False
    try:
        client = Client(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
        # Optionally test a simple API call
        info = client.get_account()  # Example; adjust based on actual method
        logging.info("Coinbase connection successful.")
        return True
    except Exception as e:
        logging.warning(f"Coinbase connection test failed: {e}")
        return False
