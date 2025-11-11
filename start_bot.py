# start_bot.py
import time
from loguru import logger
from nija_client import CoinbaseClient

def main():
    try:
        logger.info("Starting Nija loader (robust).")
        # Initialize CoinbaseClient in advanced mode
        client = CoinbaseClient(advanced=True, debug=True)
        logger.info("✅ CoinbaseClient initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize CoinbaseClient: {e}")
        return

    # Main loop
    while True:
        try:
            accounts = client.fetch_advanced_accounts()  # Correct method
            if accounts:
                logger.info(f"Fetched {len(accounts)} account(s) successfully.")
            else:
                logger.warning("No accounts found.")
        except AttributeError as e:
            logger.error(f"Method error: {e}")
        except Exception as e:
            logger.error(f"Failed to fetch accounts: {e}")

        # Wait before next fetch (adjust timing as needed)
        time.sleep(5)

if __name__ == "__main__":
    main()
