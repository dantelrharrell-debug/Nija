import sys, os, threading, signal
from flask import Flask, jsonify, request
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add vendor folder removed, using pip-installed package
try:
    from coinbase_advanced_py import CoinbaseClient
    API_KEY = os.getenv("COINBASE_API_KEY")
    API_SECRET = os.getenv("COINBASE_API_SECRET")
    
    if not API_KEY or not API_SECRET:
        raise ValueError("Missing COINBASE_API_KEY or COINBASE_API_SECRET")

    client = CoinbaseClient(API_KEY, API_SECRET)
    print("✅ CoinbaseClient loaded. Live trading ready!")

except Exception as e:
    print(f"⚠️ CoinbaseClient import failed or keys missing: {e}")
    print("⚠️ Running in simulation mode.")
    
    class CoinbaseClient:
        def get_spot_price(self, currency_pair="BTC-USD"):
            return {"amount": 30000.0}

    client = CoinbaseClient()

# Flask app
app = Flask(__name__)

# Secrets
SECRET_KEY = os.getenv("BOT_SECRET_KEY", "changeme")
TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET", "changeme")

# Thread-safe trading loop
trade_thread = None
thread_lock = threading.Lock()
running = False

def shutdown(signum, frame):
    global running
    print("⚠️ Shutting down trade loop...")
    running = False
    exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

def trade_loop():
    global running
    with thread_lock:
        if running:
            print("⚠️ Trade loop already running!")
            return
        running = True

    print("🔥 Nija Ultimate AI Trading Loop Started 🔥")
    while running:
        try:
            btc_price = float(client.get_spot_price(currency_pair='BTC-USD')['amount'])
            print(f"BTC Price: {btc_price}")

            if btc_price < 30000:
                print("✅ BUY BTC!")
            elif btc_price > 35000:
                print("✅ SELL BTC!")

            import time
            time.sleep(60)
        except Exception as e:
            print(f"⚠️ Error in trade_loop: {e}")
            time.sleep(30)

# Routes
@app.route("/")
def index():
    return jsonify({"status": "ok", "bot": "Nija Ultimate AI"}), 200

@app.route("/start")
def start_bot():
    global trade_thread
    token = request.args.get("token", "")
    if token != SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    with thread_lock:
        if trade_thread is None or not trade_thread.is_alive():
            trade_thread = threading.Thread(target=trade_loop, daemon=True)
            trade_thread.start()
            return jsonify({"status": "started", "message": "Trading loop is now running"}), 200
        else:
            return jsonify({"status": "running", "message": "Trade loop already running"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    token = request.headers.get("X-Webhook-Token")
    if token != TV_WEBHOOK_SECRET:
        return jsonify({"status": "error","message":"Unauthorized"}), 401

    data = request.json
    print("📡 TradingView alert received:", data)
    return jsonify({"status":"ok","message":"Webhook received"}), 200

# Run Flask app
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🌐 Starting Flask API on port {port}")
    app.run(host="0.0.0.0", port=port)
