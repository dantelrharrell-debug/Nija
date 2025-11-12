# app/start_bot_main.py
import os, sys
from loguru import logger
from app.nija_client import CoinbaseClient  # assuming nija_client.py inside app/

def main():
    logger.info("Starting Nija loader (robust)...")
    client = CoinbaseClient()   # reads env
    accounts = client.get_accounts()
    if not accounts:
        logger.error("❌ Connection test failed! /accounts returned no data.")
        sys.exit(1)
    logger.info("✅ Connection test succeeded! Accounts loaded.")
    # ... rest of your start logic ...

if __name__ == "__main__":
    main()
