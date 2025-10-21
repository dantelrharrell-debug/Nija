import os
import time
import threading
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

try:
    from coinbase_advanced_py import CoinbaseClient
except ImportError:
    raise ImportError("❌ coinbase_advanced_py not found in vendor folder.")

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    raise ValueError("API keys missing. Check your .env or environment variables.")

client = CoinbaseClient(API_KEY, API_SECRET)

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
            btc_price = client.get_price("BTC-USD")
            print(f"BTC Price: {btc_price}")

            if btc_price < 30000:
                client.buy("BTC", 0.001)
                print("✅ Bought BTC!")
            elif btc_price > 35000:
                client.sell("BTC", 0.001)
                print("✅ Sold BTC!")

            time.sleep(60)
        except Exception as e:
            print(f"⚠️ Error in trade_loop: {e}")
            time.sleep(30)
