# app/start_bot.py
import os
import sys
from loguru import logger
from nija_client import CoinbaseClient

def env_present(name):
    v = os.getenv(name)
    return "<present>" if v else "<missing>"

def main():
    logger.info("Starting Nija loader (robust)...")

    # Diagnostic: print presence of critical env vars (no PEM content shown)
    logger.info("ENV DIAGNOSTIC: COINBASE_AUTH_MODE=%s", os.getenv("COINBASE_AUTH_MODE"))
    logger.info("ENV DIAGNOSTIC: COINBASE_ADVANCED_BASE=%s", os.getenv("COINBASE_ADVANCED_BASE"))
    logger.info("ENV DIAGNOSTIC: COINBASE_ISS=%s", env_present("COINBASE_ISS"))
    logger.info("ENV DIAGNOSTIC: COINBASE_PEM_CONTENT=%s", env_present("COINBASE_PEM_CONTENT"))
    logger.info("ENV DIAGNOSTIC: COINBASE_API_KEY=%s", env_present("COINBASE_API_KEY"))
    logger.info("ENV DIAGNOSTIC: COINBASE_API_SECRET=%s", env_present("COINBASE_API_SECRET"))

    try:
        # CoinbaseClient MUST be instantiated with no kwargs (it reads env)
        client = CoinbaseClient()
        logger.info("CoinbaseClient initialized.")

        # Basic connection test
        accounts = client.get_accounts()
        if not accounts:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            # Helpful log: when 401 happens, nija_client prints the request failure
            # Exit non-zero so Railway marks deploy attempt; but you can inspect logs.
            sys.exit(1)

        logger.info("✅ Connection test succeeded!")
        logger.debug("Accounts (truncated): %s", repr(accounts)[:400])
        logger.info("Nija loader ready to trade...")

    except Exception:
        logger.exception("❌ Failed to initialize CoinbaseClient or connect.")
        sys.exit(1)

if __name__ == "__main__":
    main()
