# start_bot.py
import sys
from loguru import logger
from nija_client import CoinbaseClient

def main():
    logger.info("Starting Nija loader (robust)...")

    try:
        # Instantiate client (auto-detects JWT vs HMAC from env)
        client = CoinbaseClient()
        logger.info("CoinbaseClient initialized successfully.")

        # Test connection by fetching accounts
        logger.info("Testing Coinbase connection via get_accounts()...")
        accounts = client.get_accounts()
        if not accounts:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            sys.exit(1)

        logger.info("✅ Connection test succeeded!")
        logger.debug(f"Accounts (truncated): {repr(accounts)[:300]}")

        # Bot ready to continue
        logger.info("Nija loader ready to trade...")

    except Exception as e:
        logger.exception("❌ Failed to initialize CoinbaseClient or connect.")
        sys.exit(1)

if __name__ == "__main__":
    main()
