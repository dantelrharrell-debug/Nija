from flask import Flask, jsonify
import os
import threading
import time
from nija_client import NijaCoinbaseClient

app = Flask(__name__)

# Initialize NIJA client
try:
    nija = NijaCoinbaseClient()
except Exception as e:
    print(f"[FATAL] Failed to initialize NIJA client: {e}")
    nija = None

# Example product to trade (BTC-USD)
PRODUCT_ID = os.getenv("NIJA_PRODUCT", "BTC-USD")
TRADE_SIZE = float(os.getenv("NIJA_SIZE", 0.001))  # default 0.001 BTC

def live_trading_loop():
    """
    Simple live trading loop.
    Buys if last price drops by >1%, sells if rises by >1%.
    This is just a placeholder; replace with your actual strategy.
    """
    if not nija:
        print("[ERROR] NIJA client not initialized.")
        return

    last_price = None

    while True:
        ticker = nija.get_product_ticker(PRODUCT_ID)
        if not ticker:
            time.sleep(1)
            continue

        price = float(ticker.get("price") or ticker.get("last") or 0)
        if last_price:
            change_pct = (price - last_price) / last_price * 100
            if change_pct <= -1:
                nija.place_order(PRODUCT_ID, side="buy", size=TRADE_SIZE)
            elif change_pct >= 1:
                nija.place_order(PRODUCT_ID, side="sell", size=TRADE_SIZE)
        last_price = price
        time.sleep(5)  # adjust frequency as needed

@app.route("/")
def index():
    return jsonify({"status": "NIJA bot running", "product": PRODUCT_ID, "size": TRADE_SIZE})

# Start trading in a separate thread to keep Flask responsive
if nija:
    t = threading.Thread(target=live_trading_loop, daemon=True)
    t.start()
    print("⚡ NIJA trading loop started in background.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
