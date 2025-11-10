# nija_app.py
from loguru import logger
from nija_client import CoinbaseClient
import time
import sys

# --- Startup ---
logger.info("Starting Nija Trading Bot...")

try:
    # Initialize Coinbase client
    client = CoinbaseClient()
    logger.info(f"Coinbase client initialized using {client.client_type} API")
except Exception as e:
    logger.error(f"Failed to initialize CoinbaseClient: {e}")
    sys.exit(1)

# --- Example usage ---
try:
    accounts = client.get_accounts()
    logger.info(f"Accounts fetched successfully: {accounts}")
except Exception as e:
    logger.error(f"Failed to fetch accounts: {e}")
    sys.exit(1)

# --- Main Bot Loop ---
logger.info("Entering main trading loop...")
while True:
    try:
        # Here goes your trading logic, e.g., checking signals, placing orders
        logger.info("Bot running... waiting for trading signals.")
        time.sleep(10)  # Adjust as needed
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
        break
    except Exception as e:
        logger.error(f"Error in main loop: {e}")
        time.sleep(5)
