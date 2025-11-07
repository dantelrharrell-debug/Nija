#!/usr/bin/env python3
import sys
sys.path.append('./src')  # Only needed if nija_client.py is in src/

from nija_client import CoinbaseClient

def main():
    client = CoinbaseClient()
    accounts = client.get_accounts()  # Fetch real Coinbase balances
    print("Your Coinbase account balances:")
    for acct in accounts:
        print(f"{acct['currency']}: {acct['balance']}")

if __name__ == "__main__":
    main()
