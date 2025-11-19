import os
import logging
from time import sleep
from nija_client import get_coinbase_client, test_coinbase_connection

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- Initialize Coinbase client ---
try:
    client = get_coinbase_client()
except Exception as e:
    logging.error(f"❌ Failed to initialize Coinbase client: {e}")
    raise SystemExit(e)

# --- Test connection ---
if not test_coinbase_connection(client):
    logging.error("❌ Coinbase connection failed. Exiting worker.")
    raise SystemExit("Fix Coinbase credentials first.")

logging.info("⚡ Starting live trading loop...")

# --- Main trading loop ---
while True:
    try:
        accounts = client.get_accounts()
        for acct in accounts:
            logging.info(f"Account: {acct['currency']} | Balance: {acct['balance']['amount']}")
        
        # TODO: Insert your live trading logic here
        # e.g., signals, buy/sell orders, risk management
        sleep(10)
    except Exception as e:
        logging.error(f"❌ Error in trading loop: {e}")
        sleep(5)
