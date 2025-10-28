# nija_bot_web.py - Fully Auto-Start, Hardcoded Keys

import sys
import os
import time
import threading
import signal
from flask import Flask, jsonify, request

# --- Add local vendor folder to Python path ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Import Coinbase client ---
from coinbase_advanced_py.client import CoinbaseClient

# --- Hardcoded API Keys and secrets ---
COINBASE_API_KEY = "f0e7ae67-cf8a-4aee-b3cd-17227a1b8267"
COINBASE_API_SECRET = "nMHcCAQEEIHVW3T1TLBFLjoNqDOsQjtPtny50auqVT1Y27fIyefOcoAoGCCqGSM49"
SECRET_KEY = "uclgFMvRlYiVOS/HlTihim5V/RYEfuNVClKm3NhdaF9OkZN1BoB/bzN1isZN5RJGBTF/VZBrAB6gPabnisoRtA"
TV_WEBHOOK_SECRET = "nija-trading-bot-v9xl.onrender.com/webhook"

# --- Initialize Coinbase client ---
client = CoinbaseClient(COINBASE_API_KEY, COINBASE_API_SECRET)
print("✅ CoinbaseClient initialized with API keys")

# --- Flask app setup ---
app = Flask(__name__)
running = False
lock = threading.Lock()
trade_thread = None

# --- Graceful shutdown ---
def shutdown(signum, frame):
    global running
    print("⚠️ Shutting down trade loop...")
    running = False
    exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# --- Trading loop ---
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
            btc_price_data = client.get_spot_price(currency_pair='BTC-USD')
            btc_price = float(btc_price_data['amount'])
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

# --- Flask Routes ---
@app.route("/health", methods=["GET"])
def health_check():
    trading_status = "live" if running else "stopped"
    try:
        btc_price_data = client.get_spot_price(currency_pair='BTC-USD')
        coinbase_status = {"BTC-USD": float(btc_price_data['amount']), "status": "connected"}
    except Exception as e:
        coinbase_status = {"status": f"error: {e}"}

    return jsonify({
        "status": "ok",
        "trading": trading_status,
        "coinbase": coinbase_status
    })

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "bot": "Nija Ultimate AI"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    token = request.headers.get("X-Webhook-Token")
    if token != TV_WEBHOOK_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.json
    print("📡 TradingView alert received:", data)
    return jsonify({"status": "ok", "message": "Webhook received"}), 200

# --- Auto-start trading loop on deploy ---
def auto_start():
    global trade_thread
    with lock:
        if trade_thread is None or not trade_thread.is_alive():
            trade_thread = threading.Thread(target=trade_loop, daemon=True)
            trade_thread.start()
            print("🚀 Trading loop auto-started!")

# --- Run Flask API ---
if __name__ == "__main__":
    auto_start()
    port = int(os.getenv("PORT", 8080))
    print(f"🌐 Starting Flask API on port {port}")
    app.run(host="0.0.0.0", port=port)
