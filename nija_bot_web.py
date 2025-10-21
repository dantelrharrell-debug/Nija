import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

import os
import threading
from flask import Flask, jsonify, request
from nija_bot import trade_loop

app = Flask(__name__)

# --- Secrets ---
SECRET_KEY = os.getenv("BOT_SECRET_KEY", "changeme")          # For /start
TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET", "changeme") # For TradingView webhook

# --- Thread-safe trading loop ---
trade_thread = None
thread_lock = threading.Lock()

# --- Root route ---
@app.route("/")
def index():
    return jsonify({"status": "ok", "bot": "Nija Ultimate AI"}), 200

# --- Start trading loop ---
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

# --- Optional TradingView webhook ---
@app.route("/webhook", methods=["POST"])
def webhook():
    token = request.headers.get("X-Webhook-Token")
    if token != TV_WEBHOOK_SECRET:
        return jsonify({"status":"error","message":"Unauthorized"}), 401

    data = request.json
    print("📡 TradingView alert received:", data)
    # Here you can call trade_loop or execute trades based on webhook
    return jsonify({"status":"ok","message":"Webhook received"}), 200

# --- Run app ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🌐 Starting Flask API on port {port}")
    app.run(host="0.0.0.0", port=port)
