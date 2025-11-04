#!/usr/bin/env python3
"""
NIJA Debug Script: Verify Coinbase Advanced API credentials and USD Spot balance
"""

import os
import logging
from nija_client import get_usd_spot_balance, get_all_accounts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_debug")

# ----------------------------
# Print environment variables (masked)
# ----------------------------
def mask(val):
    if not val:
        return None
    return val[:4] + "****"

logger.info("COINBASE_API_KEY: %s", mask(os.getenv("COINBASE_API_KEY")))
logger.info("COINBASE_API_SECRET: %s", mask(os.getenv("COINBASE_API_SECRET")))
logger.info("COINBASE_API_PASSPHRASE: %s", mask(os.getenv("COINBASE_API_PASSPHRASE")))

# ----------------------------
# Test USD Spot Balance
# ----------------------------
try:
    usd_balance = get_usd_spot_balance()
    logger.info("✅ USD Spot Balance: %s", usd_balance)
except Exception as e:
    logger.exception("❌ Failed to fetch USD Spot balance: %s", e)

# ----------------------------
# Test fetching all accounts
# ----------------------------
try:
    accounts = get_all_accounts()
    logger.info("✅ Fetched %d accounts", len(accounts))
    for acct in accounts:
        logger.info("Account: %s | Currency: %s | Balance: %s", 
                    acct.get("name"), 
                    acct.get("balance", {}).get("currency"), 
                    acct.get("balance", {}).get("amount"))
except Exception as e:
    logger.exception("❌ Failed to fetch all accounts: %s", e)
