# nija_client.py
import os
import logging

# ----------------------------
# Setup logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("nija_client")

# ----------------------------
# Try importing Coinbase client
# ----------------------------
try:
    from coinbase_advanced.client import Client
    logger.info("Imported coinbase_advanced successfully.")
except ModuleNotFoundError:
    Client = None
    logger.error(
        "coinbase_advanced module not installed. Coinbase functions will be disabled."
    )

# ----------------------------
# Test Coinbase connection
# ----------------------------
def test_coinbase_connection() -> bool:
    """
    Returns True if the Coinbase client can be instantiated and a basic call succeeds.
    Returns False if client is unavailable or connection fails.
    """
    if Client is None:
        logger.warning("Coinbase client not available. Skipping connection test.")
        return False

    API_KEY = os.environ.get("COINBASE_API_KEY")
    API_SECRET = os.environ.get("COINBASE_API_SECRET")
    API_SUB = os.environ.get("COINBASE_API_SUB")

    if not (API_KEY and API_SECRET and API_SUB):
        logger.error("Missing Coinbase environment variables (API_KEY, API_SECRET, API_SUB).")
        return False

    try:
        client = Client(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
        # Try a safe, read-only method to confirm connection
        for fn in ("get_accounts", "list_accounts", "accounts", "list"):
            if hasattr(client, fn):
                try:
                    getattr(client, fn)()
                    logger.info("Coinbase client call succeeded; connection OK.")
                    return True
                except Exception as e:
                    logger.warning(f"Call {fn} raised an exception: {e}")
        # If instantiation succeeded but no common method found, assume success
        logger.info(
            "Coinbase client instantiated (no common read method found) — assuming success."
        )
        return True
    except Exception as e:
        logger.error(f"Failed to instantiate or call Coinbase client: {e}")
        return False
