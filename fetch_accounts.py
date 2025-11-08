#!/usr/bin/env python3
# fetch_cdp_accounts.py

from coinbase_advanced_py.advanced import CoinbaseAdvanced
import os

client = CoinbaseAdvanced(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret=os.getenv("COINBASE_API_SECRET").replace("\\n","\n"),
    base_url="https://api.cdp.coinbase.com"
)

try:
    accounts = client.get_accounts()
    print(accounts)
except Exception as e:
    print("Error:", e)
