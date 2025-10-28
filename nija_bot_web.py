# nija_bot_web.py - LIVE TRADING VERSION

import sys
import os
import time
import threading
import signal
from flask import Flask, jsonify, request
from decimal import Decimal

# --- Add local vendor folder to Python path ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Coinbase client ---
from coinbase_advanced_py.client import CoinbaseClient

# --- Hardcoded Keys ---
COINBASE_API_KEY = "f0e7ae67-cf8a-4aee-b3cd-17227a1b8267"
COINBASE_API_SECRET = "nMHcCAQEEIHVW3T1TLBFLjoNqDOsQjtPtny50auqVT1Y27fIyefOcoAoGCCqGSM49"
SECRET_KEY = "uclgFMvRlYiVOS/HlTihim5V/RYEfuNVClKm3NhdaF9OkZN1BoB/bzN1isZN5RJGBTF/VZBrAB6gPabnisoRtA"
TV_WEBHOOK_SECRET = "nija-trading-bot-v9xl.onrender.com/webhook"

# --- Initialize client ---
client = CoinbaseClient(COINBASE_API_KEY, COINBASE_API_SECRET)
print("✅ CoinbaseClient initialized with API keys")

# --- Flask app ---
app = Flask(__name__)
running = False
lock = threading.Lock()
trade_thread = None

# --- Graceful shutdown ---
def shutdown(signum, frame):
    global running
    print("⚠️ Shutting down trading loop...")
    running = False
    exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# --- Position sizing ---
MIN_PERCENT = 0.02
MAX_PERCENT = 0.10

# --- Fetch BTC balance ---
def get_balance(currency="USD"):
    accounts = client.accounts()
    for acc in accounts:
        if acc['currency'] == currency:
            return Decimal(acc['balance'])
    return Decimal("0")

# --- Place order ---
def place_order(side="buy", amount_usd=10):
    try:
        amount_usd = Decimal(amount_usd)
        order = client.buy_sell(
            product_id="BTC-USD",
            side=side,
            type="market",
            funds=str(amount_usd)
        )
        print(f"💰 {side.upper()} order placed for ${amount_usd}: {order}")
        return order
    except Exception as e:
        print(f"⚠️ Failed to place {side} order: {e}")

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
            btc_price = Decimal(btc_price_data['amount'])
            usd_balance = get_balance("USD")
            trade_amount = max(MIN_PERCENT * usd_balance, min(MAX_PERCENT * usd_balance, usd_balance))

            print(f"BTC: {btc_price}, USD Balance: {usd_balance}, Trade Amount: {trade_amount}")

            # Simple logic example: BUY < 30k, SELL > 35k
            if btc_price < 30000 and usd_balance >= trade_amount:
                place_order("buy", trade_amount)
            elif btc_price > 35000:
                btc_balance = get_balance("BTC")
                if btc_balance > 0:
                    place_order("sell", btc_balance * btc_price)  # sell all

            time.sleep(60)
        except Exception as e:
            print(f"⚠️ Error in trade_loop: {e}")
            time.sleep(30)

# --- Flask routes ---
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

    # Example: Trigger buy/sell from TradingView webhook
    if data.get("action") == "buy":
        usd_balance = get_balance("USD")
        place_order("buy", usd_balance * 0.05)  # 5% of balance
    elif data.get("action") == "sell":
        btc_balance = get_balance("BTC")
        place_order("sell", btc_balance * btc_price)

    return jsonify({"status": "ok", "message": "Webhook received"}), 200

# --- Auto-start trading loop ---
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
