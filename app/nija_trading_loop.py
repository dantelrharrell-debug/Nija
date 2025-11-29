# nija_trading_loop.py
import threading
import time
import logging
import os

# Attempt to import Coinbase client
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None

logger = logging.getLogger(__name__)

# Load Coinbase credentials
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_SUB = os.environ.get("COINBASE_API_SUB")  # optional

# Initialize client
if Client and API_KEY and API_SECRET:
    client = Client(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
    logger.info("Coinbase client initialized successfully.")
else:
    client = None
    logger.warning("Coinbase client NOT initialized! Check environment variables or module.")

# The main trading loop
def trading_loop():
    logger.info("Trading loop thread started.")
    while True:
        try:
            if client:
                # Example: Fetch account balances
                accounts = client.get_accounts()
                logger.info(f"Fetched {len(accounts)} account(s).")
            else:
                logger.warning("Skipping Coinbase actions: client not initialized.")
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")

        # Wait before next iteration
        time.sleep(5)  # change to your preferred frequency

# Function to start the loop in a separate thread
def start_trading_loop():
    logger.info("Preparing to start trading loop thread...")
    thread = threading.Thread(target=trading_loop, daemon=True)
    thread.start()
    logger.info("Trading loop thread started successfully.")
