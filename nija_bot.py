#!/usr/bin/env python3
# nija_bot.py

# --- Add vendored libraries to Python path ---
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Imports ---
from coinbase_advanced_py.client import CoinbaseClient
import pandas as pd
import numpy as np
import matplotlib
import requests

# --- Main bot logic ---
def main():
    print("🟢 Nija AI Trading Bot is running!")

    # Replace with your real Coinbase keys
    api_key = "YOUR_API_KEY"
    api_secret = "YOUR_API_SECRET"
    api_passphrase = "YOUR_API_PASSPHRASE"

    client = CoinbaseClient(api_key, api_secret, api_passphrase)
    print("✅ CoinbaseClient initialized")

    # Example: fetch accounts
    try:
        accounts = client.get_accounts()
        print("Accounts fetched:", accounts)
    except Exception as e:
        print("Error fetching accounts:", e)

if __name__ == "__main__":
    main()
