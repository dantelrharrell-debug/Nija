# check_funded_account.py
import sys
from loguru import logger

# Import your Coinbase client from nija_client
try:
    from app.nija_client import CoinbaseClient
except ImportError:
    logger.error("Cannot import CoinbaseClient. Check your path.")
    sys.exit(1)

def main():
    logger.info("Initializing Coinbase client for account check...")
    client = CoinbaseClient()  # uses your current .env keys

    logger.info("Fetching accounts...")
    try:
        accounts = client.get_accounts()  # replace with your actual method
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
        sys.exit(1)

    funded_accounts = []
    for acct in accounts:
        logger.info(f"Account: {acct.id}, Currency: {acct.currency}, Balance: {acct.balance}")
        if float(acct.balance) > 0:
            funded_accounts.append(acct)

    if funded_accounts:
        logger.info("Funded account(s) detected!")
    else:
        logger.warning("No funded accounts detected.")

if __name__ == "__main__":
    main()
