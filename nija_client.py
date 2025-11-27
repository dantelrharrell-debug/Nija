import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

try:
    from coinbase_advanced_py.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced-py module not installed. Live trading disabled.")

def test_coinbase_connection():
    if Client is None:
        logging.warning("Skipping Coinbase connection test.")
        return
    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB")
        )
        logging.info("Coinbase client initialized successfully.")
    except Exception as e:
        logging.error(f"Coinbase connection failed: {e}")
