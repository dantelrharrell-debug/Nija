import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Attempt to import Coinbase client safely
try:
    from coinbase_advanced_py.client import Client
    COINBASE_INSTALLED = True
except ModuleNotFoundError:
    logging.warning("coinbase_advanced_py module not installed. Live trading disabled.")
    Client = None
    COINBASE_INSTALLED = False

# Load Coinbase credentials from environment variables
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")

def test_coinbase_connection():
    if not COINBASE_INSTALLED:
        logging.warning("No Coinbase client available for connection test.")
        return False
    if not all([COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_SUB]):
        logging.warning("Coinbase API credentials missing. Live trading disabled.")
        return False

    try:
        client = Client(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, api_sub=COINBASE_API_SUB)
        # Example simple call
        account_info = client.get_accounts()
        logging.info("Coinbase connection test successful.")
        return True
    except Exception as e:
        logging.error(f"Coinbase connection test failed: {e}")
        return False
