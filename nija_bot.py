import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

from coinbase_advanced_py import CoinbaseClient
from flask import Flask, jsonify
import os

app = Flask(__name__)

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

client = CoinbaseClient(API_KEY, API_SECRET)

@app.route("/")
def index():
    return jsonify({"status": "ok", "app": "Nija Trading Bot"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5050)))

# nija_bot.py
import sys
import os
import time
import threading

# Add vendor folder to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Load Coinbase client from vendor ---
try:
    from coinbase_advanced_py import CoinbaseClient
    API_KEY = os.getenv("COINBASE_API_KEY")
    API_SECRET = os.getenv("COINBASE_API_SECRET")
    
    if not API_KEY or not API_SECRET:
        raise ValueError("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET in .env")

    client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)
    print("✅ CoinbaseClient loaded from vendor folder. Ready for live trading!")

except Exception as e:
    # Fallback simulation mode
    print(f"⚠️ CoinbaseClient import failed or keys missing: {e}")
    print("⚠️ Running in simulation mode. No live trades will occur.")
    
    class CoinbaseClient:
        def get_spot_price(self, currency_pair="BTC-USD"):
            # Dummy value for simulation
            return {"amount": 30000.0}

    client = CoinbaseClient()

# --- Thread-safe trading loop ---
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
