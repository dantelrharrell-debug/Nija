# wsgi.py or app_startup.py

import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Attempt to import Coinbase client
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed. Live trading will be disabled.")

def connect_coinbase():
    if not Client:
        logging.warning("Coinbase client not available. Skipping account fetch.")
        return
    
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    
    if not api_key or not api_secret:
        logging.error("Coinbase API keys are missing! Set COINBASE_API_KEY and COINBASE_API_SECRET.")
        return
    
    try:
        client = Client(api_key=api_key, api_secret=api_secret)
        accounts = client.get_accounts()
        logging.info(f"✅ Connected to Coinbase. Found {len(accounts)} accounts.")
        for acc in accounts:
            # Some accounts may not have balance field
            balance = getattr(acc, "balance", None)
            available = getattr(balance, "amount", "N/A") if balance else "N/A"
            logging.info(f"Account: {acc.currency} | Balance: {available}")
    except Exception as e:
        logging.error(f"Failed to connect to Coinbase: {e}")

# Run connection check on startup
connect_coinbase()

# --- Below is your normal WSGI app import ---
from app import create_app  # or however your app is structured
app = create_app()
