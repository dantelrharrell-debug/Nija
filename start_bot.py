#!/usr/bin/env python3
import sys
import traceback
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

def load_from_app():
    try:
        from app.nija_client import CoinbaseClient
        logger.info("Imported CoinbaseClient from app.nija_client")
        return CoinbaseClient
    except Exception:
        logger.warning("Could not import from app.nija_client:\n" + traceback.format_exc())
        return None

def load_from_root():
    try:
        from nija_client import CoinbaseClient
        logger.info("Imported CoinbaseClient from root nija_client.py")
        return CoinbaseClient
    except Exception:
        logger.warning("Could not import from root nija_client.py:\n" + traceback.format_exc())
        return None

def main():
    logger.info("Starting Nija loader (robust).")

    CoinbaseClient = load_from_app() or load_from_root()
    if CoinbaseClient is None:
        logger.error("FATAL: Cannot import CoinbaseClient. Check app/__init__.py and file locations.")
        sys.exit(1)

    try:
        client = CoinbaseClient(advanced=True)
        accounts = client.fetch_advanced_accounts()
        if not accounts:
            logger.error("No accounts returned. Verify COINBASE env vars and key permissions.")
            sys.exit(1)

        logger.info("Accounts:")
        for a in accounts:
            name = a.get("name", "<unknown>")
            bal = a.get("balance", {})
            logger.info(f" - {name}: {bal.get('amount', '0')} {bal.get('currency', '?')}")
        logger.info("✅ Advanced account check passed.")

    except Exception as e:
        logger.exception(f"Error during client init / account check: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
