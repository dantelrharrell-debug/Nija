import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

try:
    from coinbase_advanced_py import CoinbaseClient
except ImportError:
    class CoinbaseClient:
        def __init__(self, *args, **kwargs):
            print("⚠️ Dummy CoinbaseClient active (simulation mode)")

import os
import time
import threading
from coinbase.wallet.client import Client  # ✅ official SDK

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    raise ValueError("API keys missing in .env")

client = Client(API_KEY, API_SECRET)

running = False
lock = threading.Lock()

def trade_loop():
    global running
    with lock:
        if running:
            print("⚠️ Trade loop already running!")
            return
        running = True

    print("🔥 Nija Ultimate AI Trading Loop Started 🔥")
    while True:
        try:
            btc_price = float(client.get_spot_price(currency_pair='BTC-USD')['amount'])
            print(f"BTC Price: {btc_price}")

            # Example trading logic
            if btc_price < 30000:
                print("✅ BUY BTC!")
            elif btc_price > 35000:
                print("✅ SELL BTC!")

            time.sleep(60)
        except Exception as e:
            print(f"⚠️ Error in trade_loop: {e}")
            time.sleep(30)
