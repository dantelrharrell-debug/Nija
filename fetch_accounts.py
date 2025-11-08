#!/usr/bin/env python3
from coinbase_advanced_py.advanced import CoinbaseAdvanced
import os
import json

def main():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # optional

    if not api_key or not api_secret:
        print("❌ Missing required API credentials.")
        return

    # Fix PEM line breaks if needed
    api_secret = api_secret.replace("\\n", "\n")

    client = CoinbaseAdvanced(
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=api_passphrase,
        base_url="https://api.cdp.coinbase.com"  # CDP base URL
    )

    try:
        accounts = client.get_accounts()
        print("✅ Accounts fetched:")
        print(json.dumps(accounts, indent=2))
    except Exception as e:
        print("❌ Error fetching accounts:", str(e))

if __name__ == "__main__":
    main()
