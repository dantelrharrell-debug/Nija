import sys
import os
import time
import threading

# Add vendor folder to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Try importing your real CoinbaseClient from vendor ---
try:
    from coinbase_advanced_py import CoinbaseClient
    client = CoinbaseClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET")
    )
    print("✅ CoinbaseClient loaded from vendor folder.")
except ImportError:
    # Fallback to simulation mode
    print("⚠️ Dummy CoinbaseClient active (simulation mode)")
    class CoinbaseClient:
        def __init__(self, *args, **kwargs):
            pass
    client = CoinbaseClient()

# --- Trading loop ---
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
