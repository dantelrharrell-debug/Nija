#!/usr/bin/env python3
import os
import time
import logging
from decimal import Decimal

# Add vendor folder if you use a local clone (optional)
# import sys
# sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

from coinbase_advanced_py import CoinbaseClient  # Updated import

# Load API keys from environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# Initialize Coinbase client
client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Example: simple live trading loop
def start_trading():
    logger.info("🚀 Nija bot live trading started!")
    try:
        while True:
            # Fetch accounts
            accounts = client.get_accounts()
            logger.info(f"Accounts fetched: {accounts}")

            # Example: trading logic placeholder
            # TODO: Replace with your actual trading logic
            logger.info("Trading logic running...")

            time.sleep(10)  # Loop delay

    except KeyboardInterrupt:
        logger.info("🛑 Nija bot stopped manually.")
    except Exception as e:
        logger.exception(f"⚠️ Error in trading loop: {e}")
