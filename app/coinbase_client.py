import sys
import os
import logging
import threading

logging.basicConfig(level=logging.INFO)

# Add vendored Coinbase client to sys.path at runtime
VENDORED_PATH = os.path.join(os.path.dirname(__file__), "cd/vendor/coinbase_advanced_py")
if VENDORED_PATH not in sys.path:
    sys.path.insert(0, VENDORED_PATH)
    logging.info(f"Added vendored path to sys.path: {VENDORED_PATH}")

try:
    from coinbase_advanced.client import Client
    logging.info("coinbase_advanced successfully imported.")
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")

def start_trading_thread():
    if Client is None:
        logging.warning("Trading thread not started because Client is None.")
        return

    def trading_loop():
        client = Client(api_key=os.environ.get("COINBASE_API_KEY"),
                        api_secret=os.environ.get("COINBASE_API_SECRET"))
        logging.info("Live trading thread started.")
        while True:
            # Example: fetch prices, make trades, etc.
            pass

    thread = threading.Thread(target=trading_loop, daemon=True)
    thread.start()
