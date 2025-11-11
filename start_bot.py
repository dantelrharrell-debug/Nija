import sys
from loguru import logger
from nija_client import CoinbaseClient
import os

def main():
    logger.info("Starting Nija loader (robust)...")

    try:
        # Load from environment variables
        iss = os.getenv("COINBASE_ISS")
        pem_content = os.getenv("COINBASE_PEM")

        client = CoinbaseClient(
            advanced_base="https://api.cdp.coinbase.com",
            iss=iss,
            pem_content=pem_content
        )
        logger.info("CoinbaseClient initialized successfully (Advanced/JWT).")

        accounts = client.get_accounts()
        if not accounts:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            sys.exit(1)

        logger.info("✅ Connection test succeeded!")
        logger.debug(f"Accounts (truncated): {repr(accounts)[:300]}")
        logger.info("Nija loader ready to trade...")

    except Exception as e:
        logger.exception("❌ Failed to initialize CoinbaseClient or connect.")
        sys.exit(1)

if __name__ == "__main__":
    main()
