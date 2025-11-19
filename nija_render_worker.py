import os
import logging
from time import sleep
from coinbase_advanced.client import Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Load credentials
api_key = os.environ.get("COINBASE_API_KEY")
api_secret = os.environ.get("COINBASE_API_SECRET")
api_passphrase = os.environ.get("COINBASE_API_PASSPHRASE")
account_id = os.environ.get("COINBASE_ACCOUNT_ID")

if not all([api_key, api_secret, account_id]):
    logging.error("❌ Missing Coinbase credentials")
    exit(1)

client = Client(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
logging.info("✅ Coinbase client initialized")

# Simple trading loop
logging.info("⚡ Starting trading loop...")
while True:
    try:
        accounts = client.get_accounts()
        for acct in accounts:
            logging.info(f"Account: {acct['currency']} | Balance: {acct['balance']['amount']}")
        # Placeholder for trading logic
        sleep(10)
    except Exception as e:
        logging.error(f"❌ Error in trading loop: {e}")
        sleep(5)
