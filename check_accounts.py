#!/usr/bin/env python3
import os
import sys
import logging

# If nija_client.py is in src/, add it to path
sys.path.append('./src')  # remove this if nija_client.py is in the same folder

from nija_client import CoinbaseClient

# Optional: logging setup
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("check_accounts")

def main():
    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()  # Pull real balances
        log.info("Your Coinbase account balances:")
        for acct in accounts:
            print(f"{acct['currency']}: {acct['balance']}")
    except Exception as e:
        log.error(f"Error fetching accounts: {e}")

if __name__ == "__main__":
    main()
