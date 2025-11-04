#!/usr/bin/env python3
"""
NIJA Debug Script: Verify Coinbase API credentials and USD Spot balance
"""

import os
import logging
from nija_client import get_coinbase_client, get_usd_spot_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_debug")

# --- Masked environment variable check ---
logger.info("COINBASE_API_KEY: %s", (os.getenv("COINBASE_API_KEY") or "")[:4] + "****")
logger.info("COINBASE_API_SECRET: %s", (os.getenv("COINBASE_API_SECRET") or "")[:4] + "****")
logger.info("COINBASE_API_PASSPHRASE: %s", (os.getenv("COINBASE_API_PASSPHRASE") or "")[:4] + "****")

# --- Initialize client and fetch balance ---
try:
    client = get_coinbase_client()
    usd_balance = get_usd_spot_balance(client)
    if usd_balance > 0:
        logger.info("✅ Detected USD Spot balance: %s", usd_balance)
    else:
        logger.warning("⚠️ No USD Spot balance detected.")
except Exception as e:
    logger.exception("Failed to fetch USD Spot balance: %s", e)
