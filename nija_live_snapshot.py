#!/usr/bin/env python3
import os
import sys
import logging
import time

# Coinbase import for v1.8.2
try:
    from coinbase_advanced_py.client.client import CoinbaseClient
except ImportError as e:
    print("❌ ERROR: Could not import CoinbaseClient. Check coinbase-advanced-py version.")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("NijaBot")

# Load Coinbase API credentials from environment
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")  # optional

if not COINBASE_API_KEY or not COINBASE_API_SECRET:
    logger.error(
        "❌ Coinbase API key/secret not set! Set COINBASE_API_KEY and COINBASE_API_SECRET."
    )
    sys.exit(1)

# Initialize Coinbase client
client = CoinbaseClient(
    api_key=COINBASE_API_KEY,
    api_secret=COINBASE_API_SECRET,
    passphrase=COINBASE_API_PASSPHRASE,
    sandbox=False,  # True if testing, False for live trading
)

logger.info("✅ Coinbase client initialized. Starting trading loop...")

# Dummy trading loop for example
def trading_loop():
    while True:
        try:
            # Replace with your actual trading logic
            accounts = client.get_accounts()
            logger.info(f"Current balances: {accounts}")
            # Example: sleep 10 seconds between cycles
            time.sleep(10)
        except Exception as e:
            logger.error(f"⚠️ Trading loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    logger.info("🔥 Trading loop starting 🔥")
    trading_loop()
