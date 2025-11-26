import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Candidate modules for Coinbase client
MODULE_CANDIDATES = [
    "coinbase_advanced",  # Must match your cloned repo/module name
]

Client = None

# Try importing the client from each candidate
for module_name in MODULE_CANDIDATES:
    try:
        mod = __import__(module_name)
        if hasattr(mod, "Client"):
            Client = getattr(mod, "Client")
            logging.info(f"Coinbase Client class found in module: {module_name}")
            break
    except ModuleNotFoundError:
        logging.warning(f"Module {module_name} not found")

if Client is None:
    logging.warning("Coinbase client not found among candidates.")

def test_coinbase_connection():
    """
    Returns True if Coinbase connection works, False otherwise.
    """
    if Client is None:
        logging.warning("No client class available for connection test.")
        return False

    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB")  # optional
        )
        # Simple test call
        info = client.get_accounts()  # or equivalent function in your client
        logging.info("Coinbase connection successful.")
        return True
    except Exception as e:
        logging.warning(f"Coinbase connection test failed: {e}")
        return False
