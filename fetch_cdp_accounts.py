#!/usr/bin/env python3
# fetch_cdp_accounts.py
import os
import json
from coinbase_advanced_py.advanced import CoinbaseAdvanced

def main():
    # Ensure COINBASE_API_SECRET has proper line breaks if using PEM/JWT
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # Optional for CDP

    if not api_key or not api_secret:
        print("❌ Missing required Coinbase API credentials.")
        return

    # Fix line breaks for PEM if needed
    api_secret_fixed = api_secret.replace("\\n", "\n")

    # Initialize the Coinbase Advanced client
    client = CoinbaseAdvanced(
        api_key=api_key,
        api_secret=api_secret_fixed,
        api_passphrase=api_passphrase,  # None is fine for CDP
        base_url=os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com"),
    )

    try:
        # Fetch accounts (CDP-compatible)
        accounts = client.get_accounts()
        print("✅ Accounts fetched successfully:")
        print(json.dumps(accounts, indent=2))
    except Exception as e:
        print("❌ Error fetching accounts:", str(e))

if __name__ == "__main__":
    main()
