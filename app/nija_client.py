import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

try:
    from coinbase_advanced_py.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced_py module not installed. Live trading disabled.")

def test_coinbase_connection():
    if Client is None:
        logging.warning("No client class available. Skipping Coinbase connection test.")
        return False

    client = Client()
    result = client.get_accounts()
    if result:
        logging.info("Coinbase connection test passed.")
        return True
    else:
        logging.warning("Coinbase connection test failed.")
        return False
