# start_bot.py
from nija_client import CoinbaseClient
from loguru import logger
import sys, time

def main():
    logger.info("Starting Nija loader (robust).")

    try:
        # Simple initialization — no advanced/debug args
        client = CoinbaseClient()
        logger.info("✅ CoinbaseClient initialized successfully.")
    except Exception as e:
        logger.error(f"Unexpected error during CoinbaseClient init: {e}")
        sys.exit(1)

    # Test fetch accounts
    try:
        accounts = client.get_accounts()
        logger.info(f"Accounts fetched: {accounts}")
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
        sys.exit(1)

    logger.info("Entering main trading loop...")
    while True:
        try:
            # Place your trading logic here
            logger.info("Bot running... waiting for trading signals.")
            time.sleep(10)
        except KeyboardInterrupt:
            logger.info("Bot stopped manually.")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
