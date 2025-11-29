import threading
import time
import logging
import os
import sys

# Add vendor folder to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../cd/vendor"))

# Attempt to import Coinbase client
try:
    from coinbase_advanced_py.client import Client
except ModuleNotFoundError:
    Client = None
    logging.warning("Coinbase module not installed or path incorrect.")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Load credentials from environment
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_SUB = os.environ.get("COINBASE_API_SUB")

# Initialize client
if Client and API_KEY and API_SECRET:
    client = Client(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
    logger.info("Coinbase client initialized successfully.")
else:
    client = None
    logger.warning("Coinbase client NOT initialized! Check environment variables or module.")

# Main trading loop
def trading_loop():
    logger.info("Trading loop started.")
    while True:
        try:
            if client:
                accounts = client.get_accounts()
                logger.info(f"Fetched {len(accounts)} account(s).")
            else:
                logger.warning("Skipping Coinbase actions: client not initialized.")
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
        time.sleep(5)

# Start trading loop in background thread
def start_trading_loop():
    logger.info("Starting trading loop thread...")
    thread = threading.Thread(target=trading_loop, daemon=True)
    thread.start()
    logger.info("Trading loop thread running.")
