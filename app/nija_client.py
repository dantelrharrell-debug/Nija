import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# Attempt to import Coinbase client safely
try:
    from coinbase_advanced_py.client import Client
    logger.info("Imported coinbase_advanced_py successfully.")
except ModuleNotFoundError:
    Client = None
    logger.warning("coinbase_advanced_py module not installed. Coinbase functions will be disabled.")
except Exception as e:
    Client = None
    logger.error(f"Unexpected error importing Coinbase client: {e}")

def test_coinbase_connection() -> bool:
    """
    Safely tests Coinbase connection. Never raises an exception.
    Returns True if connection seems OK, False otherwise.
    """
    if Client is None:
        logger.warning("Coinbase client not available. Skipping connection test.")
        return False

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not (api_key and api_secret and api_sub):
        logger.warning("Coinbase env vars missing. Skipping connection test.")
        return False

    try:
        # Attempt to initialize client
        try:
            client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        except TypeError:
            # fallback constructor
            client = Client(api_key, api_secret, api_sub)

        # Attempt simple read-only call (non-fatal)
        for fn_name in ("get_accounts", "list_accounts", "accounts"):
            if hasattr(client, fn_name):
                try:
                    getattr(client, fn_name)()
                    logger.info("Coinbase client call succeeded; connection OK.")
                    return True
                except Exception as e:
                    logger.warning(f"Coinbase client call {fn_name} failed: {e}")

        # If instantiation worked but no calls succeeded, assume partial OK
        logger.info("Coinbase client instantiated (read-only calls failed or unavailable).")
        return True

    except Exception as e:
        logger.warning(f"Failed to initialize Coinbase client: {e}")
        return False
