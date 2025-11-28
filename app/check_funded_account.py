import os
import sys
import logging

try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def check_funded_account():
    if Client is None:
        logging.error("Coinbase client unavailable.")
        return False

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not api_key or not api_secret:
        logging.error("Coinbase credentials missing.")
        return False

    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        accounts = client.get_accounts()
        funded_accounts = [acc for acc in accounts if float(acc['balance']['amount']) > 0]

        if not funded_accounts:
            logging.warning("No funded accounts found.")
            return False

        logging.info("✅ Funded account(s) detected:")
        for acc in funded_accounts:
            logging.info(f"  - {acc['name']} | Balance: {acc['balance']['amount']} {acc['balance']['currency']}")
        return True
    except Exception as e:
        logging.error(f"Error connecting to Coinbase: {e}")
        return False

if __name__ == "__main__":
    if check_funded_account():
        sys.exit(0)
    else:
        sys.exit(1)
