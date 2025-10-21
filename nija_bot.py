import sys, os, time, threading, signal
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

from coinbase_advanced_py import CoinbaseClient
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

try:
    if not API_KEY or not API_SECRET:
        raise ValueError("Missing COINBASE_API_KEY or COINBASE_API_SECRET")
    client = CoinbaseClient(API_KEY, API_SECRET)
    print("✅ CoinbaseClient loaded. Live trading ready.")
except Exception as e:
    print(f"⚠️ CoinbaseClient failed: {e}. Simulation mode.")
    class CoinbaseClient:
        def get_spot_price(self, currency_pair="BTC-USD"):
            return {"amount": 30000.0}
    client = CoinbaseClient()

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

            # Example logic
            if btc_price < 30000:
                print("✅ BUY BTC!")
            elif btc_price > 35000:
                print("✅ SELL BTC!")

            time.sleep(60)
        except Exception as e:
            print(f"⚠️ Error in trade_loop: {e}")
            time.sleep(30)

if __name__ == "__main__":
    trade_loop()
