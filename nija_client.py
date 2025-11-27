# nija_client.py
import os
import time
import threading
import logging
from flask import Flask

# -------------------------------
# Logging setup
LOG_LEVEL = logging.INFO
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")

# -------------------------------
# Flask app (callable for Gunicorn)
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

# -------------------------------
# Coinbase client setup
try:
    from vendor.coinbase_advanced_py.client import CoinbaseClient
except ModuleNotFoundError:
    CoinbaseClient = None
    logging.error("Coinbase client module not found.")

COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")

if CoinbaseClient and COINBASE_API_KEY and COINBASE_API_SECRET:
    client = CoinbaseClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET)
    logging.info("Coinbase client ready (LIVE_TRADING=True).")
else:
    client = None
    logging.warning("Coinbase client not instantiated. Check your API keys or module.")

# -------------------------------
# Trading loop (runs in background thread)
def trading_loop():
    if not client:
        logging.error("Cannot start trading loop without Coinbase client.")
        return

    logging.info("Starting trading loop (LIVE_TRADING=True)")
    while True:
        try:
            # Example: fetch account balance
            balances = client.get_account_balances()  # replace with your actual function
            logging.info(f"Balances: {balances}")

            # Your trading logic goes here...
            # e.g., check signals, execute trades, risk management

            time.sleep(5)  # loop interval
        except Exception as e:
            logging.error(f"Error in trading loop: {e}")
            time.sleep(5)

# -------------------------------
# Only start trading loop if run directly
if __name__ == "__main__":
    threading.Thread(target=trading_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
