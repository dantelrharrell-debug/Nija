import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    logging.error("coinbase_advanced module not installed. Cannot check account.")
    exit(1)

# Load Coinbase credentials from environment
api_key = os.environ.get("COINBASE_API_KEY")
api_secret = os.environ.get("COINBASE_API_SECRET")
api_sub = os.environ.get("COINBASE_API_SUB")

if not api_key or not api_secret:
    logging.error("API key or secret not set in environment.")
    exit(1)

client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)

# Fetch accounts
try:
    accounts = client.get_accounts()  # Returns a list of dicts with balances
    funded_accounts = [a for a in accounts if float(a.get("balance", 0)) > 0]

    if funded_accounts:
        logging.info(f"Live trading ENABLED. Funded accounts: {len(funded_accounts)}")
        for acc in funded_accounts:
            logging.info(f"Account: {acc['currency']}, Balance: {acc['balance']}")
    else:
        logging.info("No funded accounts. Live trading disabled.")
except Exception as e:
    logging.error(f"Error fetching accounts: {e}")
