import os
import logging
import inspect

# -----------------------
# Logging configuration
# -----------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# -----------------------
# Load environment variables
# -----------------------
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0") == "1"

# -----------------------
# Dynamic Client Import
# -----------------------
Client = None
IMPORT_MODULE = None

try:
    import vendor.coinbase_advanced_py.client as coinbase_module
    # Look for any class in client.py that looks like a Coinbase client
    for name, obj in inspect.getmembers(coinbase_module, inspect.isclass):
        if "client" in name.lower() or "coinbase" in name.lower():
            Client = obj
            IMPORT_MODULE = f"vendor.coinbase_advanced_py.client.{name}"
            logger.info(f"Detected Coinbase client class '{name}' in module.")
            break
except ModuleNotFoundError:
    logger.warning("coinbase_advanced_py module not installed. Coinbase functionality disabled.")

# -----------------------
# Create client function
# -----------------------
def create_coinbase_client():
    if not Client:
        logger.warning("No Coinbase client class detected. Running in simulation mode.")
        return None

    missing_keys = [
        k for k, v in [
            ("COINBASE_API_KEY", COINBASE_API_KEY),
            ("COINBASE_API_SECRET", COINBASE_API_SECRET),
            ("COINBASE_API_SUB", COINBASE_API_SUB),
            ("COINBASE_PEM_CONTENT", COINBASE_PEM_CONTENT),
        ] if not v
    ]
    if missing_keys:
        logger.warning(f"Missing required environment variables: {', '.join(missing_keys)}")
        return None

    try:
        client = Client(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            api_sub=COINBASE_API_SUB,
            pem_content=COINBASE_PEM_CONTENT
        )
        logger.info("Coinbase client created successfully.")
        return client
    except Exception as e:
        logger.error(f"Failed to create Coinbase client: {e}")
        return None

# -----------------------
# Initialize client
# -----------------------
coinbase_client = create_coinbase_client() if LIVE_TRADING else None
if coinbase_client is None:
    logger.info("Coinbase client not available. Bot will run in simulation mode.")
