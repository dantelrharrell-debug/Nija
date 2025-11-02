import os
import logging
from decimal import Decimal
from coinbase.rest import RESTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

def get_rest_client():
    """
    Lazily initialize RESTClient only when needed.
    Returns None if environment variables are missing.
    """
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")

    if not api_key or not api_secret:
        logger.warning("[NIJA-BALANCE] Missing Coinbase API credentials in environment")
        return None

    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        logger.info("[NIJA-BALANCE] Coinbase RESTClient initialized successfully")
        return client
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to initialize Coinbase client: {e}")
        return None


def get_usd_balance():
    """
    Fetch the USD balance from Coinbase account.
    Returns Decimal(0) if fetch fails or credentials are missing.
    """
    client = get_rest_client()
    if not client:
        logger.warning("[NIJA-BALANCE] No client available, returning 0")
        return Decimal(0)

    try:
        accounts = client.get_accounts()
        for acct in accounts.data:
            if acct["currency"] == "USD":
                balance = Decimal(acct["balance"]["amount"])
                logger.info(f"[NIJA-BALANCE] USD Balance fetched: {balance}")
                return balance
        logger.warning("[NIJA-BALANCE] No USD account found, returning 0")
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
        return Decimal(0)
