import sys
import os
import time
import threading
import signal
from dotenv import load_dotenv

# --- Step 1: Add vendor folder to Python path ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Step 2: Import CoinbaseClient ---
try:
    from coinbase_advanced_py import CoinbaseClient
except ImportError as e:
    print(f"⚠️ CoinbaseClient import failed: {e}. Running in simulation mode.")
    class CoinbaseClient:
        def get_spot_price(self, currency_pair="BTC-USD"):
            return {"amount": 30000.0}  # Dummy price

# --- Step 3: Load environment variables ---
load_dotenv()
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# --- Step 4: Initialize client ---
try:
    if API_KEY and API_SECRET:
        client = CoinbaseClient(API_KEY, API_SECRET)
        print("✅ CoinbaseClient loaded. Live trading ready.")
    else:
        raise ValueError("Missing API keys, using simulation mode.")
except Exception:
    client = CoinbaseClient()
    print("⚠️ Simulation mode active.")

# --- Step 5: Setup trading loop ---
running = False
lock = threading.Lock()

def shutdown(signum, frame):
    global running
    print("⚠️ Shutting down trade loop...")
    running = False
    exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

def trade_loop():
    global running
    with lock:
        if running:
            print("⚠️ Trade loop already running!")
            return
        running = True

    print("🔥 Nija Ultimate AI Trading Loop Started 🔥")
    while running:
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

# --- Run the bot ---
if __name__ == "__main__":
    trade_loop()
