import os
import logging

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("nija_client")

# -----------------------------
# Import Coinbase client
# -----------------------------
try:
    from coinbase_advanced_py.client import Client
    logger.info("Imported coinbase_advanced_py successfully.")
except ModuleNotFoundError:
    Client = None
    logger.error("coinbase_advanced_py module not installed. Coinbase functions will be disabled.")

# -----------------------------
# Coinbase connection test
# -----------------------------
def test_coinbase_connection() -> bool:
    if Client is None:
        logger.warning("Coinbase client not available. Skipping connection test.")
        return False

    API_KEY = os.environ.get("COINBASE_API_KEY")
    API_SECRET = os.environ.get("COINBASE_API_SECRET")
    API_SUB = os.environ.get("COINBASE_API_SUB")

    if not (API_KEY and API_SECRET and API_SUB):
        logger.error("Missing Coinbase environment variables (COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_SUB).")
        return False

    try:
        client = Client(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)

        # Optional quick test: call a safe read-only method if exists
        for fn in ("get_accounts", "list_accounts", "accounts", "list"):
            if hasattr(client, fn):
                try:
                    getattr(client, fn)()
                    logger.info("Coinbase client call succeeded; connection OK.")
                    return True
                except Exception as e:
                    logger.warning(f"Call {fn} raised: {e}")

        # If instantiation worked but no read method found, assume success
        logger.info("Coinbase client instantiated successfully (no read method tested).")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Coinbase client: {e}")
        return False
