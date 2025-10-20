import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

#!/usr/bin/env python3
# nija_bot.py

import sys
import os

# --- Add the vendored libraries to Python path ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Import Coinbase Advanced Py ---
try:
    import coinbase_advanced_py
    print("✅ Coinbase Advanced Py ready!")
except ModuleNotFoundError:
    print("❌ coinbase_advanced_py not found. Check vendor folder.")

# --- Main bot logic placeholder ---
def main():
    print("🟢 Nija AI Trading Bot is running!")
    # Example: initialize Coinbase client (replace with your keys)
    api_key = "YOUR_API_KEY"
    api_secret = "YOUR_API_SECRET"
    api_passphrase = "YOUR_API_PASSPHRASE"

    try:
        client = coinbase_advanced_py.CoinbaseClient(api_key, api_secret, api_passphrase)
        print("Client initialized ✅")
    except Exception as e:
        print("Error initializing Coinbase client:", e)

if __name__ == "__main__":
    main()
