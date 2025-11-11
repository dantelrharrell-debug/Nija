# start_bot.py
import os
from dotenv import load_dotenv
from nija_client import CoinbaseClient
from loguru import logger

# Load environment variables from .env
load_dotenv()

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional, only if required

def main():
    logger.info("Starting Nija loader (robust).")

    # Initialize CoinbaseClient with CDP (advanced mode)
    try:
        client = CoinbaseClient(advanced=True)
        logger.info("✅ CoinbaseClient initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to init CoinbaseClient: {e}")
        return

    # Fetch accounts
    try:
        accounts = client.fetch_advanced_accounts()
        if not accounts:
            logger.warning("No accounts found.")
        else:
            logger.info(f"Accounts fetched: {accounts}")
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")

if __name__ == "__main__":
    main()
