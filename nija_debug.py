"""
nija_debug.py

Simple debug runner for preflight. Drops into logs similar to previous behavior.
"""

import os
import logging
from loguru import logger

# use loguru + fallback to stdout formatting
logger.add(lambda msg: print(msg, end=""))

from nija_client import CoinbaseClient, calculate_position_size, get_usd_spot_balance, get_all_accounts

def mask(s: str, keep_front: int = 4, keep_back: int = 0):
    if not s:
        return str(s)
    return s[:keep_front] + "*" * max(4, len(s) - keep_front - keep_back) + (s[-keep_back:] if keep_back else "")

def main():
    logger.info("✅ Starting Nija preflight check...")
    logger.info("ℹ️ Masked env values for debug:")
    logger.info("COINBASE_API_KEY: %s", mask(os.getenv("COINBASE_API_KEY", "")))
    # Do NOT print secret PEM or secret in logs
    logger.info("COINBASE_API_PASSPHRASE: %s", mask(os.getenv("COINBASE_API_PASSPHRASE", "")))

    try:
        client = CoinbaseClient(preflight=True)
    except Exception as e:
        logger.error("❌ Error creating CoinbaseClient: %s", e)
        client = CoinbaseClient(preflight=False)  # try non-preflight instance

    # Try fetching usd balance (wrapped with try/except so preflight won't crash deploy)
    try:
        usd = client.get_usd_spot_balance()
        logger.info("✅ USD Spot Balance: $%.2f", usd)
    except Exception as e:
        logger.error("❌ Failed to fetch USD Spot balance: %s", e)
        usd = 0.0

    # Position sizing demo
    try:
        if usd > 0:
            pos = calculate_position_size(usd, risk_factor=1.0, min_percent=2, max_percent=10)
            logger.info("✅ Suggested trade size (based on $%.2f equity): $%.2f", usd, pos)
        else:
            logger.warning("⚠️ USD balance zero or unavailable; cannot calculate position size.")
    except Exception as e:
        logger.error("❌ Failed to calculate position size: %s", e)

    # Print available accounts list length
    try:
        accounts = client.get_all_accounts()
        logger.info("ℹ️ Accounts fetched: %s", len(accounts) if isinstance(accounts, list) else "unknown")
    except Exception as e:
        logger.error("❌ Failed to fetch all accounts: %s", e)


if __name__ == "__main__":
    main()
