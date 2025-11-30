# startup.py
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")

def check_coinbase_accounts():
    if not Client:
        return
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    if not api_key or not api_secret:
        logging.error("Missing Coinbase API credentials!")
        return
    try:
        client = Client(api_key=api_key, api_secret=api_secret)
        accounts = client.get_accounts()
        logging.info(f"✅ Connected to Coinbase. Found {len(accounts)} accounts.")
        for acc in accounts:
            bal = getattr(acc.balance, "amount", "N/A") if getattr(acc, "balance", None) else "N/A"
            logging.info(f"Account: {acc.currency} | Balance: {bal}")
    except Exception as e:
        logging.error(f"Failed to connect to Coinbase: {e}")

check_coinbase_accounts()
