# nija_client.py
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Attempt to import Coinbase client dynamically
Client = None
try:
    import coinbase_advanced_py
    logging.info("Imported module candidate: coinbase_advanced_py")

    # Try common locations for the Client class
    if hasattr(coinbase_advanced_py, "Client"):
        Client = coinbase_advanced_py.Client
    elif hasattr(coinbase_advanced_py, "client") and hasattr(coinbase_advanced_py.client, "Client"):
        Client = coinbase_advanced_py.client.Client
    else:
        logging.warning("coinbase client not found among candidates.")

except ModuleNotFoundError:
    logging.error("coinbase_advanced_py module not installed.")
except Exception as e:
    logging.error(f"Unexpected error importing Coinbase client: {e}")


def test_coinbase_connection():
    """Run a single test connection to Coinbase. Returns True/False."""
    if not Client:
        logging.warning("No client class available for connection test.")
        return False

    try:
        # Load credentials from environment
        api_key = os.environ.get("COINBASE_API_KEY")
        api_secret = os.environ.get("COINBASE_API_SECRET")
        api_sub = os.environ.get("COINBASE_API_SUB")

        if not api_key or not api_secret or not api_sub:
            logging.warning("Coinbase credentials not fully set in environment.")
            return False

        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        # Example call to verify connection (adjust depending on API)
        accounts = client.get_accounts()  # or client.list_accounts(), depending on module
        logging.info(f"Coinbase connection successful. Accounts retrieved: {len(accounts)}")
        return True

    except Exception as e:
        logging.warning(f"Coinbase connection test failed: {e}")
        return False


if __name__ == "__main__":
    logging.info("Running standalone Coinbase connection test...")
    result = test_coinbase_connection()
    logging.info(f"Connection test result: {result}")
