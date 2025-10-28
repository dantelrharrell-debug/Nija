#!/usr/bin/env python3
import os
import time
from coinbase_advanced_py.client import CoinbaseClient  # Live client
from nija_client import run_trader  # Your trading loop module

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")  # optional

# Initialize Coinbase client
client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)

def live_snapshot():
    print("\n===== NIJA BOT LIVE SNAPSHOT =====")
    try:
        accounts = client.get_accounts()
        print(f"Number of Accounts: {len(accounts)}")
        for acc in accounts:
            print(f"- {acc['currency']}: {acc['balance']['amount']}")
    except Exception as e:
        print(f"Coinbase API error: {e}")
    print("=================================\n")

if __name__ == "__main__":
    live_snapshot()
    run_trader(client)  # Start live trading
