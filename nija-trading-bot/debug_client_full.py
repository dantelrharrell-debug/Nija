#!/usr/bin/env python3
import sys
import os
import traceback

# Ensure the vendor folder is in the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

try:
    from coinbase_advanced_py.client import CoinbaseClient
except Exception as e:
    print("⚠️ CoinbaseClient import failed:", e)
    traceback.print_exc()
    sys.exit(1)

def main():
    print("=== DEBUG CLIENT FULL ===")
    
    # Replace these with your actual API keys if you want to test live
    API_KEY = "YOUR_API_KEY"
    API_SECRET = "YOUR_API_SECRET"
    API_PASSPHRASE = "YOUR_API_PASSPHRASE"

    try:
        client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)
        accounts = client.get_accounts()
        if accounts:
            print("✅ Coinbase client connected successfully. Accounts:")
            for acc in accounts:
                print(f" - {acc['currency']}: {acc['balance']}")
        else:
            print("⚠️ Connected but no accounts found.")
    except Exception as e:
        print("⚠️ Error connecting to Coinbase:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
