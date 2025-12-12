import os
import logging
from coinbase_advanced_py.client import Client
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# Load environment variables
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")
ACCOUNT_ID = os.environ.get("COINBASE_ACCOUNT_ID")

client = Client(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
logging.info("✅ Coinbase client initialized")

def main_loop():
    logging.info("⚡ Bot is now running live!")
    while True:
        try:
            # Example: fetch account balance
            account = next(a for a in client.get_accounts() if a["id"] == ACCOUNT_ID)
            logging.info(f"Current balance: {account['balance']['amount']} {account['currency']}")
            # Add trading logic here
        except Exception as e:
            logging.error(f"Error in bot loop: {e}")
        time.sleep(10)  # adjust frequency as needed

if __name__ == "__main__":
    main_loop()
