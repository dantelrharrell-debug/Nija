import threading
import logging
import time
import os
import sys

logging.basicConfig(level=logging.INFO)

# Add vendored Coinbase path
VENDORED_PATH = os.path.join(os.path.dirname(__file__), "cd/vendor/coinbase_advanced_py")
if VENDORED_PATH not in sys.path:
    sys.path.insert(0, VENDORED_PATH)
    logging.info(f"Added vendored path to sys.path: {VENDORED_PATH}")

# Attempt to import Client
try:
    from coinbase_advanced.client import Client
    logging.info("coinbase_advanced module loaded successfully ✅")
except ModuleNotFoundError as e:
    Client = None
    logging.error("coinbase_advanced module NOT installed ❌. Live trading disabled")
    logging.error(repr(e))


def trading_loop():
    """Dummy loop to simulate live trading"""
    logging.info("Trading thread started...")
    while True:
        logging.info("Trading loop running...")
        time.sleep(10)  # Replace with your actual trading logic


def start_trading_thread():
    if Client is None:
        logging.warning("Trading thread not started: Client unavailable")
        return

    thread = threading.Thread(target=trading_loop, daemon=True)
    thread.start()
    logging.info("Trading thread started in background ✅")
