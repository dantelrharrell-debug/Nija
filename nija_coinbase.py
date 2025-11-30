import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    logging.error("coinbase_advanced module not installed.")
    Client = None

def test_coinbase_connection():
    if not Client:
        logging.error("Coinbase client not available.")
        return

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")

    if not api_key or not api_secret:
        logging.error("API key or secret not set in environment variables.")
        return

    try:
        client = Client(api_key=api_key, api_secret=api_secret)
        accounts = client.get_accounts()
        logging.info(f"Successfully connected to Coinbase. Found {len(accounts)} accounts.")
        for acc in accounts:
            logging.info(f"Account: {acc['currency']} | Balance: {acc['balance']}")
    except Exception as e:
        logging.error(f"Failed to connect to Coinbase API: {e}")
