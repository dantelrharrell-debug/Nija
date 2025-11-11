import os
import sys
from dotenv import load_dotenv
from loguru import logger
from nija_client import CoinbaseClient

# Load .env automatically
load_dotenv()

def main():
    logger.info("Starting Nija loader (robust)...")

    try:
        # Initialize CoinbaseClient using environment credentials
        # Or you can hardcode JWT here if you want, but usually env vars are safer
        client = CoinbaseClient()  # reads credentials from environment

        # Test connection
        accounts = client.get_accounts()
        if not accounts:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            sys.exit(1)

        logger.info("✅ Connection test succeeded!")
        logger.debug(f"Accounts (truncated): {repr(accounts)[:300]}")
        logger.info("Nija loader ready to trade...")

    except Exception:
        logger.exception("❌ Failed to initialize CoinbaseClient or connect.")
        sys.exit(1)

if __name__ == "__main__":
    main()
