import os
from loguru import logger
from app.nija_client import CoinbaseClient  # import from app package

def main():
    logger.info("Starting Nija loader (robust)...")

    client = CoinbaseClient()
    logger.info("CoinbaseClient initialized. base=%s", client.base_url)

    accounts = client.get_accounts()
    if not accounts:
        logger.error("❌ Connection test failed! /accounts returned no data.")
        return

    logger.info("✅ Connection test succeeded! Accounts: %s", accounts)
