#!/usr/bin/env python3
import sys
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

# Try local root import first (many scripts use this), fallback to app package
try:
    from nija_client import CoinbaseClient
    logger.info("Imported CoinbaseClient from root nija_client.py")
except Exception:
    try:
        from app.nija_client import CoinbaseClient
        logger.info("Imported CoinbaseClient from app/nija_client.py")
    except Exception as e:
        logger.exception("Cannot import CoinbaseClient from nija_client or app.nija_client")
        sys.exit(1)

def main():
    logger.info("Starting Nija loader (robust).")

    try:
        client = CoinbaseClient(advanced=True, debug=False)
    except Exception as e:
        logger.exception(f"Error initializing CoinbaseClient: {e}")
        sys.exit(1)

    accounts = client.fetch_advanced_accounts()
    if not accounts:
        logger.warning("Advanced API failed; falling back to spot API.")
        accounts = client.fetch_spot_accounts()

    if not accounts:
        logger.error("No accounts returned. Check COINBASE env vars and key permissions.")
        sys.exit(1)

    logger.info(f"Successfully fetched {len(accounts)} accounts.")
    for a in accounts:
        logger.info(f"Account: {a.get('id', a.get('name', '<unknown>'))}")

if __name__ == "__main__":
    main()
