import logging
import os

try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced.client module not found. Install coinbase-advanced-py.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def test_coinbase_connection():
    if Client is None:
        logging.error("Cannot test Coinbase connection: Client module missing.")
        return False

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not api_key or not api_secret or not api_sub:
        logging.error("One or more Coinbase environment variables are missing!")
        return False

    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        accounts = client.accounts.list()  # quick test call
        logging.info(f"Coinbase connection verified: {len(accounts)} accounts found")
        return True
    except Exception as e:
        logging.error(f"Coinbase connection failed: {e}")
        return False
