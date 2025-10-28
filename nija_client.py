#!/usr/bin/env python3
import os
import time
import logging
from decimal import Decimal
from coinbase_advanced_py import CoinbaseClient
from dotenv import load_dotenv

load_dotenv()

# Get API keys from environment
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize client (passphrase optional)
if API_KEY and API_SECRET:
    if API_PASSPHRASE:
        client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)
    else:
        client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)
    logger.info("✅ Coinbase client initialized.")
else:
    client = None
    logger.warning("⚠️ Coinbase API keys not found. Bot will wait until keys are available.")

def start_trading():
    if not client:
        logger.error("❌ Cannot start trading: Coinbase client not initialized.")
        return

    logger.info("🚀 Nija bot live trading started!")
    try:
        while True:
            accounts = client.get_accounts()
            logger.info(f"Accounts fetched: {accounts}")

            # Placeholder for trading logic
            logger.info("Trading logic running...")
            time.sleep(10)

    except KeyboardInterrupt:
        logger.info("🛑 Nija bot stopped manually.")
    except Exception as e:
        logger.exception(f"⚠️ Error in trading loop: {e}")
