# web/wsgi.py
import os
import threading
import logging
from flask import Flask, jsonify

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- Initialize Flask App ---
app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"status": "NIJA Trading Bot is running!"})

# --- Coinbase Bot Initialization ---
def start_nija_bot():
    try:
        from coinbase_advanced.client import Client
    except ModuleNotFoundError:
        logging.error("coinbase_advanced module not installed. Live trading disabled.")
        return

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")  # optional if using subaccount

    if not api_key or not api_secret:
        logging.error("Coinbase credentials missing. Live trading disabled.")
        return

    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        logging.info("✅ Coinbase client initialized. Bot starting...")
        # Example: start your trading loop here (non-blocking)
        # from nija_bot import run_bot
        # run_bot(client)
    except Exception as e:
        logging.error(f"Failed to start Coinbase bot: {e}")

# Start the bot in a separate thread so Flask/Gunicorn can serve requests
bot_thread = threading.Thread(target=start_nija_bot, daemon=True)
bot_thread.start()
