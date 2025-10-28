import logging
from nija_client import start_trading, get_accounts

logging.basicConfig(level=logging.INFO)

try:
    accounts = get_accounts()
    for account in accounts:
        logging.info(f" - {account['currency']}: {account['balance']['amount']}")
except Exception as e:
    logging.error(f"❌ Failed to fetch accounts: {e}")

start_trading()
