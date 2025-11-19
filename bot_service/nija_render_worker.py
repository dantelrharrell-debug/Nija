import os
import logging
from coinbase_advanced.client import Client
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# Load environment variables
COINBASE_API_KEY = os.environ["COINBASE_API_KEY"]
COINBASE_API_SECRET = os.environ["COINBASE_API_SECRET"]
COINBASE_API_PASSPHRASE = os.environ["COINBASE_API_PASSPHRASE"]
COINBASE_ACCOUNT_ID = os.environ["COINBASE_ACCOUNT_ID"]

# Initialize Coinbase client
client = Client(
    api_key=COINBASE_API_KEY,
    api_secret=COINBASE_API_SECRET,
    api_passphrase=COINBASE_API_PASSPHRASE
)
logging.info("✅ Coinbase client initialized")

# Simple loop to demonstrate live trading
while True:
    try:
        accounts = client.get_accounts()
        funded = next((a for a in accounts if a["id"] == COINBASE_ACCOUNT_ID), None)
        if funded:
            logging.info(f"⚡ Funded account balance: {funded['balance']['amount']} {funded['currency']}")
            # TODO: Insert trading logic here
        else:
            logging.error("❌ Funded account not found")
        time.sleep(10)  # check every 10 seconds
    except Exception as e:
        logging.error(f"❌ Error in bot loop: {e}")
        time.sleep(10)
