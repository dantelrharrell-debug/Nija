# nija_bot_web.py - Render & Railway Ready with Coinbase Health Check

import sys
import os
import time
import threading
import signal
from flask import Flask, jsonify, request
from dotenv import load_dotenv

# --- Add local vendor folder to Python path ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Import Coinbase client ---
from coinbase_advanced_py.client import CoinbaseClient

# --- Load environment variables ---
load_dotenv()
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY")
TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET")

if not API_KEY or not API_SECRET:
    raise ValueError("Coinbase API key and secret must be set in environment variables.")

# --- Initialize Coinbase client ---
client = CoinbaseClient(API_KEY, API_SECRET)
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

# --- Trading loop (background thread) ---
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

# --- Flask Routes ---

@app.route("/health", methods=["GET"])
def health_check():
    """
    Returns:
    - status: Flask alive
    - trading: whether the bot thread is running
    - coinbase: whether Coinbase API is reachable
    """
    trading_status = "live" if running else "stopped"

    # Coinbase connectivity check
    try:
        accounts = client.get_accounts_list()  # <-- correct method for current library
        if accounts and len(accounts) > 0:
            sample_accounts = []
            for a in accounts[:3]:
                sample_accounts.append({
                    "id": a.get("id"),
                    "currency": a.get("currency"),
                    "balance": a.get("balance")
                })
            coinbase_status = {"status": "connected", "sample_accounts": sample_accounts}
        else:
            coinbase_status = {"status": "no accounts returned"}
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

@app.route("/start", methods=["GET"])
def start_bot():
    global trade_thread
    token = request.args.get("token", "")
    if token != SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    with lock:
        if trade_thread is None or not trade_thread.is_alive():
            trade_thread = threading.Thread(target=trade_loop, daemon=True)
            trade_thread.start()
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

# --- Run Flask API ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🌐 Starting Flask dev server on port {port}")
    app.run(host="0.0.0.0", port=port)
else:
    # Running under gunicorn (production)
    print("🔁 Running under a WSGI server (gunicorn) — app ready")
