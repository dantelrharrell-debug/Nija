#!/usr/bin/env python3
import os
import time
import logging
from decimal import Decimal
from coinbase_advanced_py import CoinbaseClient  # Updated import

# Load API keys from environment
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# Initialize client
client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Example trading loop
def start_trading():
    logger.info("🚀 Nija bot live trading started!")
    try:
        while True:
            accounts = client.get_accounts()
            logger.info(f"Accounts fetched: {accounts}")

            # Placeholder for real trading logic
            logger.info("Trading logic running...")

            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("🛑 Nija bot stopped manually.")
    except Exception as e:
        logger.exception(f"⚠️ Error in trading loop: {e}")
