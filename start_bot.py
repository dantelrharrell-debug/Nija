#!/usr/bin/env python3
import os
from loguru import logger

# import from app package
from app.nija_client import CoinbaseClient

def main():
    logger.info("Starting Nija HMAC/Advanced startup (root entrypoint).")
    try:
        client = CoinbaseClient(advanced=True)
    except Exception as e:
        logger.exception("Failed to initialize CoinbaseClient")
        return

    accounts = client.fetch_advanced_accounts()
    if not accounts:
        logger.error("No HMAC/Advanced accounts found. Verify COINBASE_ISS, COINBASE_PEM_CONTENT, COINBASE_BASE and key permissions.")
        return

    logger.info("Accounts:")
    for a in accounts:
        name = a.get("name") or a.get("id") or "<unknown>"
        bal = a.get("balance") or a.get("available") or {}
        logger.info(f" - {name} : {bal}")

    logger.info("✅ HMAC/Advanced account check complete. Bot ready to start trading loop (implement next).")

if __name__ == "__main__":
    main()
