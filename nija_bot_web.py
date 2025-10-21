import sys, os, time, threading, signal
from flask import Flask, jsonify, request
from dotenv import load_dotenv

# --- Load environment variables ---
load_dotenv()

# --- Add vendor folder for Coinbase client ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Coinbase client setup ---
try:
    from coinbase_advanced_py import CoinbaseClient
    API_KEY = os.getenv("COINBASE_API_KEY")
    API_SECRET = os.getenv("COINBASE_API_SECRET")
    
    if not API_KEY or not API_SECRET:
        raise ValueError("Missing COINBASE_API_KEY or COINBASE_API_SECRET")

    client = CoinbaseClient(API_KEY, API_SECRET)
    print("✅ CoinbaseClient loaded. Ready for live trading!")

except Exception as e:
    print(f"⚠️ CoinbaseClient import failed or keys missing: {e}")
    print("⚠️ Running in simulation mode.")
    
    class CoinbaseClient:
        def get_spot_price(self, currency_pair="BTC-USD"):
            return {"amount": 30000.0}

    client = CoinbaseClient()

# --- Flask app setup ---
app = Flask(__name__)

# --- Secrets ---
SECRET_KEY = os.getenv("BOT_SECRET_KEY", "changeme")          # For /start
TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET", "changeme") # For TradingView webhook

# --- Thread-safe trading loop ---
trade_thread = None
thread_lock = threading.Lock()
running = False

def shutdown(signum, frame):
    global running
    print("⚠️ Shutting down trade loop...")
    running = False
    os._exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

def trade_loop():
    """Main trading loop"""
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

            # Example trading logic
            if btc_price < 30000:
                print("✅ BUY BTC!")
            elif btc_price > 35000:
                print("✅ SELL BTC!")

            time.sleep(60)
        except Exception as e:
            print(f"⚠️ Error in trade_loop: {e}")
            time.sleep(30)

# --- Flask routes ---
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
            return jsonify({"status": "running", "message": "Trading loop already running"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    token = request.headers.get("X-Webhook-Token")
    if token != TV_WEBHOOK_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.json
    print("📡 TradingView alert received:", data)
    # You can implement custom trade execution here based on webhook
    return jsonify({"status": "ok", "message": "Webhook received"}), 200

# --- Run app ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🌐 Starting Flask API on port {port}")
    app.run(host="0.0.0.0", port=port)
