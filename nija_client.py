import os
import time
import logging
import threading
from flask import Flask

# --------------------------
# Setup Logging
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# --------------------------
# Import Coinbase Client
# --------------------------
try:
    from coinbase_advanced.client import Client
    client = Client(
        api_key=os.environ.get("COINBASE_API_KEY"),
        api_secret=os.environ.get("COINBASE_API_SECRET"),
        api_sub=os.environ.get("COINBASE_API_SUB", None)
    )
    logging.info(f"Coinbase client ready (LIVE_TRADING={os.environ.get('LIVE_TRADING', True)})")
except ModuleNotFoundError:
    client = None
    logging.error("coinbase_advanced module not installed. Trading disabled.")

# --------------------------
# Trading Loop
# --------------------------
def trading_loop():
    if not client:
        logging.error("Trading loop not started: Coinbase client not available.")
        return

    logging.info("Starting trading loop...")
    while True:
        try:
            # Use the correct Coinbase client method
            accounts = client.get_accounts()
            for account in accounts:
                logging.info(f"Account: {account['currency']} | Balance: {account['balance']['amount']}")
            
            # TODO: Add your trading logic here
            
            time.sleep(5)  # pause 5 sec between loops
        except Exception as e:
            logging.error(f"Error in trading loop: {e}")
            time.sleep(5)

# --------------------------
# Flask App
# --------------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

# --------------------------
# Startup
# --------------------------
def start_background_loop():
    thread = threading.Thread(target=trading_loop, daemon=True)
    thread.start()

# Only run Flask dev server if executed directly
if __name__ == "__main__":
    start_background_loop()
    app.run(host="0.0.0.0", port=8080)
