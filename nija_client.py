# nija_client.py

import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Try to import Coinbase client
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed.")


def test_coinbase_connection():
    """
    Safe Coinbase connection test.
    Never crashes the container.
    Always returns True or False.
    """
    if Client is None:
        logging.warning("Coinbase client is unavailable.")
        return False

    try:
        api_key = os.environ.get("COINBASE_API_KEY")
        api_secret = os.environ.get("COINBASE_API_SECRET")
        api_sub = os.environ.get("COINBASE_API_SUB")

        if not api_key or not api_secret or not api_sub:
            logging.error("Missing Coinbase API environment variables.")
            return False

        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)

        # Simple health check call
        client.get_accounts()
        logging.info("Coinbase API connection successful.")
        return True

    except Exception as e:
        logging.error(f"Coinbase API connection failed: {e}")
        return False
