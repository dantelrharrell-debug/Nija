# nija_client.py
import os
import logging
import time

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# Coinbase connection check
try:
    from coinbase_advanced.client import Client
    client = Client(
        api_key=os.environ.get("COINBASE_API_KEY"),
        api_secret=os.environ.get("COINBASE_API_SECRET"),
        api_sub=os.environ.get("COINBASE_API_SUB")
    )
    account = client.get_account()  # Basic API test
    logging.info(f"Coinbase connection successful. Account ID: {account['id']}")
except ModuleNotFoundError:
    client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")
except Exception as e:
    client = None
    logging.error(f"Coinbase connection failed: {e}")

# Your bot startup logic
def start_bot():
    if client is None:
        logging.warning("Bot running in offline/dry mode.")
    else:
        logging.info("Bot running with live Coinbase connection.")
    
    # Example loop (replace with your trading logic)
    while True:
        logging.info("Bot heartbeat...")  # shows bot is alive
        time.sleep(60)

if __name__ == "__main__":
    start_bot()
