# app/start_bot_main.py
from nija_client import CoinbaseClient
from loguru import logger
import os
import time
import asyncio

MIN_POSITION = 0.02
MAX_POSITION = 0.10

def main():
    logger.info("Starting Nija Bot (live-ready)...")

    # Initialize Coinbase client
    try:
        client = CoinbaseClient()
        logger.info("Coinbase client initialized successfully.")
    except Exception as e:
        logger.error("Cannot initialize Coinbase client: %s", e)
        return

    # Test connection to accounts
    try:
        accounts = client.get_accounts()
        data = accounts.get("data") if isinstance(accounts, dict) else None
        if not data:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            return
        logger.info("✅ Connected to Coinbase! Retrieved %d accounts.", len(data))
        for a in data[:5]:
            bal = a.get("balance", {})
            logger.info(" - %s: %s %s", a.get("name") or a.get("currency"), bal.get("amount"), bal.get("currency"))
    except Exception as e:
        logger.error("Failed to fetch accounts: %s", e)
        return

    # Ready to run live bot logic
    logger.info("Bot initialized. Entering persistent loop...")

    # Persistent loop to keep container alive
    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()
