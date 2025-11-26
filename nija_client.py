import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Try to import Coinbase module safely
try:
    import coinbase_advanced_py as coinbase_module
except ModuleNotFoundError:
    coinbase_module = None
    logging.error("coinbase_advanced_py module not installed.")

def _import_client_class():
    """
    Tries to find a callable client class inside the imported module.
    """
    if not coinbase_module:
        return None

    # Common names to try
    candidates = ["Client", "RESTClient", "APIClient", "CoinbaseClient"]
    for attr in candidates:
        client_cls = getattr(coinbase_module, attr, None)
        if callable(client_cls):
            logging.info(f"Using Coinbase client class: {attr}")
            return client_cls

    logging.warning("coinbase client not found among candidates.")
    return None

def test_coinbase_connection():
    ClientClass = _import_client_class()
    if not ClientClass:
        logging.warning("Coinbase connection test failed: no client class available")
        return False

    try:
        client = ClientClass(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB")
        )
        # Optional quick test call
        accounts = getattr(client, "list_accounts", lambda: [])()
        logging.info(f"Coinbase connection test succeeded. Accounts found: {len(accounts)}")
        return True
    except Exception as e:
        logging.warning(f"Coinbase connection test failed: {e}")
        return False
