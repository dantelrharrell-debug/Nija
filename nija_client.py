import os
import logging
import importlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# List of module candidates (your repo)
MODULE_CANDIDATES = [
    "coinbase_advanced",
    "coinbase_advanced_py"
]

def find_coinbase_client():
    """
    Dynamically searches module candidates for a Client class.
    Returns the Client class if found, else None.
    """
    for module_name in MODULE_CANDIDATES:
        try:
            mod = importlib.import_module(module_name)
            logging.info(f"Imported module candidate: {module_name}")

            # Check for Client class in module
            if hasattr(mod, "Client"):
                logging.info(f"Found Client in {module_name}")
                return getattr(mod, "Client")
            # Check for submodule 'client'
            if hasattr(mod, "client"):
                client_mod = getattr(mod, "client")
                if hasattr(client_mod, "Client"):
                    logging.info(f"Found Client in {module_name}.client")
                    return getattr(client_mod, "Client")
        except ModuleNotFoundError:
            logging.warning(f"Module {module_name} not found")
    logging.warning("coinbase client not found among candidates.")
    return None

def test_coinbase_connection():
    ClientClass = find_coinbase_client()
    if not ClientClass:
        logging.warning("No client class available for connection test.")
        return False

    # Load credentials from environment
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not api_key or not api_secret or not api_sub:
        logging.warning("Coinbase API credentials not set in environment.")
        return False

    try:
        client = ClientClass(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        # Optionally: perform a small test call
        # result = client.get_accounts()  # If method exists
        logging.info("Coinbase client instantiated successfully.")
        return True
    except Exception as e:
        logging.warning(f"Coinbase connection test failed: {e}")
        return False
