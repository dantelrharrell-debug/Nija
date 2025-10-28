#!/usr/bin/env python3
# nija_live_snapshot.py
import os
import sys
import logging
import base64

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s:%(message)s")

# --- Check Python path ---
logging.debug("Python executable: %s", sys.executable)
logging.debug("Python sys.path: %s", sys.path)

# --- Import CoinbaseClient safely ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logging.info("✅ CoinbaseClient found")
except ImportError:
    logging.warning("⚠️ coinbase_advanced_py.client not found. Real trading disabled.")
    CoinbaseClient = None

# --- Load environment variables ---
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")
API_PEM_B64 = os.environ.get("API_PEM_B64")  # optional PEM file as base64

# --- Decode PEM if provided ---
API_PEM_PATH = None
if API_PEM_B64:
    API_PEM_PATH = "/tmp/nija_coinbase.pem"
    with open(API_PEM_PATH, "wb") as f:
        f.write(base64.b64decode(API_PEM_B64))
    logging.info("🔑 PEM key decoded to %s", API_PEM_PATH)

# --- Initialize CoinbaseClient ---
client = None
if CoinbaseClient:
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_API_PASSPHRASE,
            pem_file=API_PEM_PATH
        )
        logging.info("🚀 CoinbaseClient initialized for real trading")
    except Exception as e:
        logging.error("❌ Failed to initialize CoinbaseClient: %s", e)
        client = None
else:
    logging.warning("⚠️ Using stub client. Trading disabled.")

# --- Main bot loop ---
import time

def main_loop():
    logging.info("🌟 Starting Nija bot main loop...")
    while True:
        try:
            if client:
                # Example: fetch accounts
                accounts = client.get_accounts()
                logging.debug("Accounts: %s", accounts)
            else:
                logging.debug("Stub mode: skipping real trades")
            time.sleep(10)  # adjust loop timing as needed
        except Exception as e:
            logging.error("Exception in main loop: %s", e)
            time.sleep(5)

if __name__ == "__main__":
    main_loop()
