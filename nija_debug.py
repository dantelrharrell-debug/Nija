#!/usr/bin/env python3
"""
NIJA Debug Script: Verify Coinbase Advanced ECDSA API credentials and USD Spot balance
"""

import os
import logging
from nija_client import get_usd_spot_balance, get_all_accounts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_debug")

# --- Print environment variables (masked for safety) ---
logger.info("COINBASE_API_KEY: %s", os.getenv("COINBASE_API_KEY")[:4] + "****" if os.getenv("COINBASE_API_KEY") else None)
logger.info("COINBASE_API_SECRET: %s", os.getenv("COINBASE_API_SECRET")[:4] + "****" if os.getenv("COINBASE_API_SECRET") else None)
logger.info("COINBASE_API_PASSPHRASE: %s", os.getenv("COINBASE_API_PASSPHRASE")[:4] + "****" if os.getenv("COINBASE_API_PASSPHRASE") else None)

# --- Check USD Spot balance ---
try:
    usd_balance = get_usd_spot_balance()
    logger.info("✅ USD Spot Balance: %s", usd_balance)
except Exception as e:
    logger.exception("❌ Failed to fetch USD Spot balance: %s", e)

# --- List all accounts (for debugging) ---
try:
    accounts = get_all_accounts()
    logger.info("All accounts fetched:")
    for acct in accounts:
        logger.info(" - Name: %s, Currency: %s, Balance: %s", acct.get("name"), acct.get("balance", {}).get("currency"), acct.get("balance", {}).get("amount"))
except Exception as e:
    logger.exception("❌ Failed to fetch all accounts: %s", e)
