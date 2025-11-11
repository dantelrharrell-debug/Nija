# start_bot.py
import os
from dotenv import load_dotenv

load_dotenv()  # loads .env in the project root

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

from nija_client import CoinbaseClient
from loguru import logger

def main():
    logger.info("Starting Nija loader (robust).")
    
    # Initialize Coinbase client (no base argument)
    client = CoinbaseClient()
    logger.info("✅ CoinbaseClient initialized successfully.")

    try:
        # Use the updated method to fetch accounts
        accounts = client.get_accounts()
        if accounts:
            logger.info(f"Fetched {len(accounts)} account(s): {accounts}")
        else:
            logger.warning("No accounts found.")
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")

if __name__ == "__main__":
    main()
