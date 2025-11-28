#!/usr/bin/env python3
import os
import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout
)

# Attempt to import Coinbase client
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    logging.error("coinbase_advanced module not installed. Live trading disabled.")
    Client = None

def check_funded_account():
    if Client is None:
        logging.error("Cannot check accounts: Coinbase client not available.")
        return

    # Load API credentials from environment
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not api_key or not api_secret:
        logging.error("Coinbase API key or secret not set in environment variables.")
        return

    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        accounts = client.get_accounts()  # returns list of accounts
        funded_accounts = [acc for acc in accounts if float(acc['balance']['amount']) > 0]

        if not funded_accounts:
            logging.warning("No funded accounts found. Live trading cannot proceed.")
        else:
            logging.info("Funded account(s) found:")
            for acc in funded_accounts:
                logging.info(f"  - {acc['name']} | Balance: {acc['balance']['amount']} {acc['balance']['currency']}")
            logging.info("✅ Live trading is ENABLED for these accounts.")

    except Exception as e:
        logging.error(f"Error connecting to Coinbase: {e}")

if __name__ == "__main__":
    logging.info("=== Checking Coinbase funded account ===")
    check_funded_account()
