#!/usr/bin/env python3
import sys
import traceback
from loguru import logger
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

def load_from_app():
    try:
        # preferred import (when running from project root and app is a package)
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

    # 1) try app package import
    CoinbaseClient = load_from_app()
    # 2) fallback to root nija_client.py
    if CoinbaseClient is None:
        CoinbaseClient = load_from_root()

    if CoinbaseClient is None:
        logger.error("FATAL: Cannot import CoinbaseClient from either app.nija_client nor nija_client.")
        logger.error("Check: 1) app/__init__.py exists, 2) app/nija_client.py exists, 3) you're running from project root.")
        sys.exit(1)

    # instantiate and run a quick accounts check
    try:
        client = CoinbaseClient(advanced=True)
        accounts = []
        if hasattr(client, "fetch_advanced_accounts"):
            accounts = client.fetch_advanced_accounts()
        else:
            # attempt a generic request if class uses different API
            try:
                status, data = client.request("GET", "/v3/accounts")
                if status == 200 and data:
                    accounts = data.get("data", []) if isinstance(data, dict) else []
            except Exception:
                accounts = []

        if not accounts:
            logger.error("No accounts returned. Verify COINBASE env vars, key permissions, and COINBASE_BASE.")
            sys.exit(1)

        logger.info("Accounts:")
        for a in accounts:
            logger.info(f" - {a.get('name', a.get('id', '<unknown>'))}")
        logger.info("✅ HMAC/Advanced account check passed. Ready to start trading loop (not included here).")

    except Exception as e:
        logger.exception(f"Error during client init / account check: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
