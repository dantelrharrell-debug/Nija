# app/coinbase_client.py
import sys
import os
import logging
import threading
import time

logging.basicConfig(level=logging.INFO)

# Vendored Coinbase client path
VENDORED_PATH = os.path.join(os.path.dirname(__file__), "cd/vendor/coinbase_advanced_py")
if VENDORED_PATH not in sys.path:
    sys.path.insert(0, VENDORED_PATH)
    logging.info(f"Added vendored path to sys.path: {VENDORED_PATH}")

try:
    from coinbase_advanced.client import Client
    logging.info("coinbase_advanced module loaded successfully ✅")
except ModuleNotFoundError as e:
    Client = None
    logging.error("coinbase_advanced module NOT installed ❌. Live trading disabled!")
    logging.error(repr(e))


# Optional: Start trading thread
def trading_loop():
    if not Client:
        logging.warning("Client not available. Skipping trading loop.")
        return

    client = Client(api_key=os.environ.get("COINBASE_API_KEY"),
                    api_secret=os.environ.get("COINBASE_API_SECRET"))

    logging.info("Trading loop started.")
    while True:
        # Placeholder: your live trading logic here
        logging.info("Trading tick...")
        time.sleep(10)

def start_trading_thread():
    t = threading.Thread(target=trading_loop, daemon=True)
    t.start()
