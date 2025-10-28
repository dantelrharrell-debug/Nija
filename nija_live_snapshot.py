#!/usr/bin/env python3
import os
import logging
import time
from coinbase_advanced_py import CoinbaseClient

# ---------------------------
# CONFIG
# ---------------------------
LOG_FILE = "nija_bot.log"
LOG_LEVEL = logging.INFO

# Coinbase API keys (from environment variables)
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")

if not COINBASE_API_KEY or not COINBASE_API_SECRET:
    raise EnvironmentError(
        "COINBASE_API_KEY and COINBASE_API_SECRET must be set in your environment!"
    )

# ---------------------------
# LOGGING SETUP
# ---------------------------
logging.basicConfig(
    filename=LOG_FILE,
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------
# INITIALIZE COINBASE CLIENT
# ---------------------------
try:
    client = CoinbaseClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET)
    logger.info("✅ Coinbase client initialized with live keys")
except Exception as e:
    logger.error(f"❌ Failed to initialize Coinbase client: {e}")
    raise e

# ---------------------------
# SIMPLE TRADING LOOP
# ---------------------------
def trading_loop():
    logger.info("🔥 Trading loop starting 🔥")
    while True:
        try:
            # Example: get account balances
            accounts = client.get_accounts()
            for acc in accounts:
                logger.info(f"Account: {acc['currency']} | Balance: {acc['balance']['amount']}")
            # Here you add your real trading strategy
            time.sleep(10)  # adjust frequency as needed
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            time.sleep(5)

# ---------------------------
# START
# ---------------------------
if __name__ == "__main__":
    logger.info("🌟 Nija bot started")
    trading_loop()
