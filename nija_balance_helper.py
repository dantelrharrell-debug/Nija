# nija_balance_helper.py

import os
import logging
from decimal import Decimal

from coinbase.rest import RESTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

# Fetch API keys from environment variables
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")

if not COINBASE_API_KEY or not COINBASE_API_SECRET:
    raise ValueError(
        "Set COINBASE_API_KEY and COINBASE_API_SECRET in Render environment variables"
    )

# Initialize Coinbase REST client
try:
    client = RESTClient(
        api_key=COINBASE_API_KEY,
        api_secret=COINBASE_API_SECRET
    )
    logger.info("[NIJA-BALANCE] Coinbase RESTClient initialized successfully")
except Exception as e:
    logger.error(f"[NIJA-BALANCE] Failed to initialize Coinbase client: {e}")
    raise

def get_usd_balance():
    """
    Fetch the USD balance from Coinbase account.
    Returns Decimal(0) if fetch fails.
    """
    try:
        accounts = client.get_accounts()  # Fetch all accounts
        for acct in accounts.data:
            if acct['currency'] == 'USD':
                balance = Decimal(acct['balance']['amount'])
                logger.info(f"[NIJA-BALANCE] USD Balance fetched: {balance}")
                return balance
        logger.warning("[NIJA-BALANCE] No USD account found, returning 0")
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
        return Decimal(0)
