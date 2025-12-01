import os
import logging
import threading
import time
from flask import Flask, jsonify

# ---------------------------
# Logging Setup
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ---------------------------
# Coinbase Client Setup
# ---------------------------
try:
    from coinbase_advanced_py.client import Client  # <-- FIXED HERE
    logging.info("Imported coinbase_advanced_py.Client successfully")
    LIVE_TRADING_ENABLED = True
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced_py module not installed. Live trading disabled.")
    LIVE_TRADING_ENABLED = False

# Initialize Coinbase client if live trading is enabled
client = None
if LIVE_TRADING_ENABLED:
    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_passphrase=os.environ.get("COINBASE_API_PASSPHRASE")
        )
        logging.info("Coinbase client initialized successfully")
    except Exception as e:
        logging.error(f"Error initializing Coinbase client: {e}")
        LIVE_TRADING_ENABLED = False

# ---------------------------
# Flask App Setup
# ---------------------------
app = Flask(__name__)
logging.info("Flask app created successfully")

@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "live_trading": LIVE_TRADING_ENABLED
    })

# ---------------------------
# Bot Logic
# ---------------------------
def run_bot():
    if not LIVE_TRADING_ENABLED or client is None:
        logging.warning("Live trading disabled, skipping bot execution.")
        return

    try:
        # Example: fetch account balances
        accounts = client.get_accounts()
        for account in accounts:
            logging.info(f"Account: {account['currency']} | Balance: {account['balance']['amount']}")
        
        # --- Trading logic placeholder ---
        # if some_condition:
        #     client.place_order(...)
        logging.info("Bot executed successfully")
    except Exception as e:
        logging.error(f"Bot execution failed: {e}")

# ---------------------------
# Background Bot Loop
# ---------------------------
def bot_loop():
    interval = int(os.environ.get("BOT_INTERVAL", 60))  # seconds
    logging.info(f"Starting bot loop with interval {interval} seconds")
    while True:
        run_bot()
        time.sleep(interval)

# Start the bot loop in a separate thread
if LIVE_TRADING_ENABLED:
    thread = threading.Thread(target=bot_loop, daemon=True)
    thread.start()
    logging.info("Bot thread started")

# ---------------------------
# Run Flask App
# ---------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port)
