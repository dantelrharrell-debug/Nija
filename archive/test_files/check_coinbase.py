#!/usr/bin/env python3
import os
import logging
from coinbase.rest import RESTClient

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Load API credentials from environment
api_key = os.environ.get("COINBASE_API_KEY")
api_secret = os.environ.get("COINBASE_API_SECRET")

if not api_key or not api_secret:
    logging.error("Coinbase API credentials missing. Set COINBASE_API_KEY and COINBASE_API_SECRET.")
    exit(1)

try:
    # Initialize the REST client
    client = RESTClient(api_key=api_key, api_secret=api_secret)

    # Fetch accounts
    accounts = client.get_accounts()
    logging.info(f"✅ Connected to Coinbase. Found {len(accounts.accounts)} accounts.")

    for acc in accounts.accounts:
        # Some accounts have available_balance, some just balance
        balance = getattr(acc, "available_balance", getattr(acc, "balance", None))
        balance_value = balance["value"] if balance else "N/A"
        logging.info(f"Account: {acc.currency}, Balance: {balance_value}")

except Exception as e:
    logging.error("Failed to fetch Coinbase accounts: %s", e)
    exit(1)
