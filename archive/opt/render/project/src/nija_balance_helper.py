# nija_balance_helper.py
import logging
from decimal import Decimal

logger = logging.getLogger("nija_balance_helper")
logger.setLevel(logging.INFO)

def get_usd_balance(client):
    """
    Fetch USD balance from Coinbase account.
    Returns Decimal(0) if fetch fails.
    """
    if client is None:
        logger.warning("[NIJA-BALANCE] Client is None, cannot fetch balance")
        return Decimal(0)

    try:
        accounts = client.get_accounts()  # adjust according to your client library
        for account in accounts:
            if account["currency"] == "USD":
                return Decimal(account["balance"])
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
        return Decimal(0)
