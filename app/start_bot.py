import os
from loguru import logger
from nija_client import CoinbaseClient

def main():
    logger.info("Starting Nija loader (robust)...")

    try:
        # CoinbaseClient automatically reads env for JWT (Advanced API)
        client = CoinbaseClient(
            jwt_iss=os.getenv("COINBASE_ISS"),
            jwt_pem=os.getenv("COINBASE_PEM_CONTENT")
        )
        logger.info("CoinbaseClient initialized successfully (Advanced/JWT).")

        accounts = client.get_accounts()
        if not accounts:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            return

        logger.info("✅ Connection test succeeded!")
        logger.debug(f"Accounts (truncated): {repr(accounts)[:300]}")
        logger.info("Nija loader ready to trade...")

    except Exception:
        logger.exception("❌ Failed to initialize CoinbaseClient or connect.")
