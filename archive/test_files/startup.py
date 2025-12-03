# startup.py
import os
import logging
import sys
from typing import List, Dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")
    # We intentionally do NOT sys.exit here so other dev tasks can run.
    # But later we will choose to exit in the trading startup if required.

def load_credentials():
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")  # optional
    return api_key, api_secret, api_sub

def check_coinbase_connection(require_live: bool = True) -> Client:
    """
    Returns a instantiated Client if connection succeeds.
    If require_live is True and connection fails, exits the process.
    """
    api_key, api_secret, api_sub = load_credentials()
    if not Client:
        logging.error("coinbase_advanced client not available in environment.")
        if require_live:
            logging.error("Exiting due to missing client library.")
            sys.exit(1)
        return None

    if not api_key or not api_secret:
        logging.error("Missing Coinbase API credentials (COINBASE_API_KEY/COINBASE_API_SECRET).")
        if require_live:
            logging.error("Exiting due to missing credentials.")
            sys.exit(1)
        return None

    try:
        logging.info("Attempting Coinbase connection...")
        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        # call a light-weight endpoint (adjust to real client method)
        accounts = client.get_accounts()  # expects a list/dict of accounts
        logging.info(f"✅ Coinbase connection successful. Found {len(accounts)} accounts.")
        for a in accounts:
            # adapt to returned object structure (dict or object)
            try:
                cur = a.get("currency", getattr(a, "currency", "N/A"))
                bal = a.get("balance", getattr(a, "balance", "N/A"))
                # if balance is object/dict:
                if isinstance(bal, dict) and "amount" in bal:
                    bal_str = f"{bal['amount']} {cur}"
                else:
                    bal_str = str(bal)
                logging.info(f"Account: {cur} | Balance: {bal_str}")
            except Exception:
                logging.info(f"Account raw: {a}")
        return client
    except Exception as exc:
        logging.error(f"Failed to connect to Coinbase API: {exc}")
        if require_live:
            logging.error("Exiting due to failed Coinbase connection.")
            sys.exit(1)
        return None
