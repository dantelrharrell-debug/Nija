# start_bot_main.py
import os
import time
from loguru import logger
from nija_client import CoinbaseClient

def main():
    logger.info("Starting NIJA trading bot...")

    # Initialize Coinbase client
    client = CoinbaseClient()

    # Get accounts
    accounts = client.get_accounts()
    if not accounts:
        logger.error("No accounts found or failed to fetch accounts.")
        return

    logger.info("Accounts fetched: %s", [a.get("name") for a in accounts])

    # Example: main loop (replace with your trading logic)
    try:
        while True:
            # Here you would poll signals, check balances, and place trades
            logger.info("Bot running... waiting 10 seconds before next check")
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.exception("Bot crashed: %s", e)

if __name__ == "__main__":
    main()
