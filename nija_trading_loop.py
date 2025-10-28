# nija_trading_loop.py
from coinbase_advanced_py.client import CoinbaseClient
import os
import threading
import time

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)

def trading_loop():
    print("🔥 Trading loop starting 🔥")
    while True:
        try:
            # Example: fetch prices and make decisions
            btc_account = client.get_account('BTC')
            print(f"[Trading Loop] BTC Balance: {btc_account['balance']}")
            time.sleep(5)  # Adjust interval as needed
        except Exception as e:
            print(f"[Trading Loop] Error: {e}")
            time.sleep(5)

# Run in a separate thread
thread = threading.Thread(target=trading_loop)
thread.start()
thread.join()
