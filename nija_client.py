# nija_client.py
import os
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Try import once — fail gracefully if not installed
try:
    # repo exposes package name coinbase_advanced_py per our pip egg
    from coinbase_advanced.client import Client
    COINBASE_CLIENT_AVAILABLE = True
    logger.info("coinbase_advanced_py module imported successfully.")
except Exception as e:
    Client = None
    COINBASE_CLIENT_AVAILABLE = False
    logger.warning("coinbase_advanced_py module not installed or failed to import: %s", e)


def test_coinbase_connection() -> bool:
    """Run a single connection test. Returns True if successful, False otherwise."""
    if not COINBASE_CLIENT_AVAILABLE or Client is None:
        logger.warning("No Coinbase client available for connection test.")
        return False

    # read credentials FROM environment (don't hardcode)
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")  # optional, if you use sub-account or similar

    if not api_key or not api_secret:
        logger.warning("Coinbase API credentials are not present in environment.")
        return False

    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        # run a light API call — choose a safe, low-cost call (e.g., get products or ping)
        # adjust to actual client method names; using try/except is defensive.
        try:
            # example: client.ping() or client.get_system_status() depending on library
            # Using attribute checks to be robust to library variations:
            if hasattr(client, "ping"):
                client.ping()
            elif hasattr(client, "get_system_status"):
                client.get_system_status()
            else:
                # fallback: attempt to list accounts or products if available
                if hasattr(client, "list_products"):
                    client.list_products(limit=1)
                elif hasattr(client, "list_accounts"):
                    client.list_accounts(limit=1)
            logger.info("Coinbase connection test: success")
            return True
        except Exception as inner_ex:
            logger.warning("Coinbase client instantiated but test call failed: %s", inner_ex)
            return False
    except Exception as ex:
        logger.warning("Failed to instantiate Coinbase client: %s", ex)
        return False
