# nija_app.py
from flask import Flask, jsonify
import threading
import time
from nija_preflight_check import run_preflight
from nija_trader import start_trading_loop  # your main trading function

app = Flask(__name__)

# ----------------------------
# Background Thread: Bot Runner
# ----------------------------
def bot_runner():
    print("ℹ️ Starting preflight check for Coinbase Advanced API...")
    accounts = run_preflight()
    if accounts:
        print("✅ Preflight passed. Starting trading loop...")
        start_trading_loop()  # this should run your live trading logic
    else:
        print("❌ Preflight failed. Bot will not start. Fix API keys/permissions.")

threading.Thread(target=bot_runner, daemon=True).start()

# ----------------------------
# Health Check Endpoint
# ----------------------------
@app.route("/", methods=["GET", "HEAD"])
def health():
    return jsonify({"status": "OK", "message": "Nija Bot is running"}), 200

# ----------------------------
# Optional: Status Endpoint
# ----------------------------
@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "status": "running",
        "bot": "Nija Trading Bot",
        "version": "Advanced API"
    }), 200

# ----------------------------
# App Runner
# ----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
