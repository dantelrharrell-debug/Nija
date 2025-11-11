# start_bot.py
import os
import sys
from loguru import logger
from nija_client import CoinbaseClient
from dotenv import load_dotenv

# Load local .env in development only
load_dotenv()

def main():
    logger.info("Starting Nija loader (robust)...")

    try:
        # Read JWT credentials from environment
        jwt_iss = os.getenv("COINBASE_JWT_ISS")
        jwt_pem = os.getenv("COINBASE_JWT_PEM")

        if not jwt_iss or not jwt_pem:
            logger.error("❌ Environment variables COINBASE_JWT_ISS or COINBASE_JWT_PEM not set.")
            sys.exit(1)

        # Initialize CoinbaseClient (no extra arguments)
        client = CoinbaseClient()  # Your nija_client.py reads from env internally
        logger.info("CoinbaseClient initialized successfully.")

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
