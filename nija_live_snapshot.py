#!/usr/bin/env python3
# nija_live_snapshot.py

import os
import time
import logging
from decimal import Decimal

# ✅ Updated import for coinbase-advanced-py v1.8.2
from coinbase_advanced_py.rest.client import RESTClient as CoinbaseClient

# Optional: Load environment variables if using .env
from dotenv import load_dotenv
load_dotenv()

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load API keys from environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    logger.error("COINBASE_API_KEY and COINBASE_API_SECRET must be set in environment.")
    exit(1)

# Initialize Coinbase client
client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)
logger.info("✅ CoinbaseClient initialized successfully!")

# Example function to list accounts
def list_accounts():
    try:
        accounts = client.get_accounts()
        for acct in accounts:
            logger.info(f"Account: {acct['id']}, Balance: {acct['balance']['amount']} {acct['balance']['currency']}")
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")

# Example main loop
if __name__ == "__main__":
    logger.info("🌟 Starting Nija bot main loop...")
    while True:
        try:
            list_accounts()
            # Insert your trading logic here
            time.sleep(60)  # run every 60 seconds
        except KeyboardInterrupt:
            logger.info("⏹ Nija bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(10)
