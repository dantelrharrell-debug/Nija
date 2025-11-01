import os
import logging
from decimal import Decimal
from coinbase.rest import RESTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

# --- Load environment variables ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")

if not COINBASE_API_KEY or not COINBASE_API_SECRET:
    raise ValueError("Set COINBASE_API_KEY and COINBASE_API_SECRET in Render environment variables")

# --- Initialize Coinbase client ---
try:
    client = RESTClient(
        api_key=COINBASE_API_KEY,
        api_secret=COINBASE_API_SECRET
    )
    logger.info("[NIJA-BALANCE] Coinbase RESTClient initialized successfully")
except Exception as e:
    logger.error(f"[NIJA-BALANCE] Failed to init Coinbase client: {e}")
    client = None  # Fallback to None, handle gracefully in balance function

# --- Helper function to fetch USD balance ---
def get_usd_balance():
    """
    Fetch USD balance from Coinbase account.
    Returns Decimal(0) if fetch fails.
    """
    if client is None:
        logger.warning("[NIJA-BALANCE] Coinbase client not initialized, returning 0")
        return Decimal(0)

    try:
        accounts = client.list_accounts()
        for account in accounts.data:
            if account.currency == "USD":
                return Decimal(account.balance)
        logger.warning("[NIJA-BALANCE] USD account not found, returning 0")
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
        return Decimal(0)
