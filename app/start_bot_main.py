# app/start_bot_main.py
import os, sys
from loguru import logger
from app.nija_client import CoinbaseClient  # package import (app must be a package)

def main():
    logger.info("Starting Nija loader (robust)...")
    client = CoinbaseClient()   # client reads env
    accounts = client.get_accounts()
    if not accounts:
        logger.error("❌ Connection test failed! /accounts returned no data.")
        sys.exit(1)
    logger.info("✅ Connection test succeeded! Accounts loaded.")
    # Continue with the rest of your startup logic...

if __name__ == "__main__":
    main()
