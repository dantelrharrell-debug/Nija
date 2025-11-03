#!/usr/bin/env python3
"""
NIJA Debug Script: Verify Coinbase API credentials and USD Spot balance
"""

import os
import logging
from nija_client import get_usd_spot_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_debug")

# Print environment variables (masked partially)
logger.info("COINBASE_API_KEY: %s", os.getenv("COINBASE_API_KEY")[:4] + "****" if os.getenv("COINBASE_API_KEY") else None)
logger.info("COINBASE_API_SECRET: %s", os.getenv("COINBASE_API_SECRET")[:4] + "****" if os.getenv("COINBASE_API_SECRET") else None)
logger.info("COINBASE_API_PASSPHRASE: %s", os.getenv("COINBASE_API_PASSPHRASE")[:4] + "****" if os.getenv("COINBASE_API_PASSPHRASE") else None)

try:
    usd_amount, account = get_usd_spot_balance()
    if account:
        logger.info("✅ Detected USD Spot balance: %s in account: %s (id: %s)", usd_amount, account.get("name"), account.get("id"))
    else:
        logger.warning("⚠️ No USD Spot balance detected.")
except Exception as e:
    logger.exception("Failed to fetch USD Spot balance: %s", e)
