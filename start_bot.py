# start_bot.py
import sys
from loguru import logger
from nija_client import CoinbaseClient
from dotenv import load_dotenv
import os

# Load local .env if present (optional for Railway)
load_dotenv()

def main():
    logger.info("Starting Nija loader (robust)...")

    try:
        # Initialize CoinbaseClient using JWT credentials from environment variables
        # Make sure Railway environment variables are set:
        # COINBASE_JWT_ISS and COINBASE_JWT_PEM
        client = CoinbaseClient()  # no arguments needed

        logger.info("CoinbaseClient initialized successfully (Advanced/JWT).")

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
