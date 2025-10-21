import sys, os
import time
import threading
import signal
from flask import Flask, jsonify, request

# --- Step 1: Add vendor folder for CoinbaseClient ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Step 2: Import CoinbaseClient ---
from coinbase_advanced_py.client import CoinbaseClient

# --- Step 3: Direct API keys ---
API_KEY = "f0e7ae67-cf8a-4aee-b3cd-17227a1b8267"
API_SECRET = "nMHcCAQEEIHVW3T1TLBFLjoNqDOsQjtPtny50auqVT1Y27fIyefOcoAoGCCqGSM49"
SECRET_KEY = "uclgFMvRlYiVOS/HlTihim5V/RYEfuNVClKm3NhdaF9OkZN1BoB/bzN1isZN5RJGBTF/VZBrAB6gPabnisoRtA"
TV_WEBHOOK_SECRET = "your_webhook_secret_here"

# --- Step 4: Initialize Coinbase client ---
client = CoinbaseClient(API_KEY, API_SECRET)
print("✅ CoinbaseClient loaded. Live trading ready.")

# --- Step 5: Setup Flask app ---
app = Flask(__name__)

# --- Step 6: Trading loop ---
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

# --- Step 7: Flask routes ---
@app.route("/")
def index():
    return jsonify({"status": "ok", "bot": "Nija Ultimate AI"}), 200

@app.route("/start")
def start_bot():
    global trade_thread
    token = request.args.get("token", "")
    if token != SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    with lock:
        if 'trade_thread' not in globals() or not trade_thread.is_alive():
            globals()['trade_thread'] = threading.Thread(target=trade_loop, daemon=True)
            globals()['trade_thread'].start()
            return jsonify({"status": "started", "message": "Trading loop is now running"}), 200
        else:
            return jsonify({"status": "running", "message": "Trading loop already running"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    token = request.headers.get("X-Webhook-Token")
    if token != TV_WEBHOOK_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.json
    print("📡 TradingView alert received:", data)
    return jsonify({"status": "ok", "message": "Webhook received"}), 200

# --- Step 8: Run Flask API ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🌐 Starting Flask API on port {port}")
    app.run(host="0.0.0.0", port=port)
