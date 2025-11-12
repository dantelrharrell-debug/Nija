import os
import sys
from loguru import logger
from app.nija_client import CoinbaseClient  # must exist

def main():
    logger.info("Starting Nija loader (robust)...")

    # Diagnostic: show env presence
    logger.info("ENV DIAGNOSTIC: COINBASE_AUTH_MODE=%s", os.getenv("COINBASE_AUTH_MODE"))
    logger.info("ENV DIAGNOSTIC: COINBASE_API_KEY=%s", "<present>" if os.getenv("COINBASE_API_KEY") else "<missing>")
    logger.info("ENV DIAGNOSTIC: COINBASE_PEM_CONTENT=%s", "<present>" if os.getenv("COINBASE_PEM_CONTENT") else "<missing>")

    try:
        client = CoinbaseClient()  # automatically reads env
        logger.info("CoinbaseClient initialized.")

        accounts = client.get_accounts()
        if not accounts:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            sys.exit(1)

        logger.info("✅ Connection test succeeded!")
        logger.debug("Accounts (truncated): %s", repr(accounts)[:400])
        logger.info("Nija loader ready to trade...")

    except Exception:
        logger.exception("❌ Failed to initialize CoinbaseClient or connect.")
        sys.exit(1)

if __name__ == "__main__":
    main()
