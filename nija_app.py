# nija_app.py
import threading
import time
import logging
from flask import Flask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_app")

# --- Force dummy client mode ---
from nija_client import DummyClient as CoinbaseClient, get_usd_balance

# --- Flask app ---
app = Flask(__name__)

@app.route("/")
def home():
    balance = get_usd_balance()
    return f"NIJA BOT DUMMY! USD Balance: {balance}"

# --- Background worker ---
def worker_loop():
    while True:
        try:
            bal = get_usd_balance()
            logger.info(f"[NIJA] Periodic USD balance: {bal}")
        except Exception as e:
            logger.error(f"[NIJA] Error fetching balance: {e}")
        time.sleep(10)

threading.Thread(target=worker_loop, daemon=True).start()
