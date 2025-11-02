# nija_app.py
import threading
import time
import logging
from flask import Flask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_app")

# --- Import your client logic ---
try:
    from nija_client import CoinbaseClient, get_usd_balance
    LIVE_CLIENT_AVAILABLE = True
except Exception as e:
    logger.warning(f"[NIJA] CoinbaseClient unavailable, using DummyClient ⚠️ ({e})")
    from nija_client import DummyClient as CoinbaseClient, get_usd_balance
    LIVE_CLIENT_AVAILABLE = False

# --- Initialize Flask app for Gunicorn ---
app = Flask(__name__)

@app.route("/")
def home():
    balance = get_usd_balance()
    status = "LIVE" if LIVE_CLIENT_AVAILABLE else "DUMMY"
    return f"NIJA BOT {status}! USD Balance: {balance}"

# --- Background worker thread ---
def worker_loop():
    while True:
        try:
            bal = get_usd_balance()
            logger.info(f"[NIJA] Periodic USD balance: {bal}")
        except Exception as e:
            logger.error(f"[NIJA] Error fetching balance: {e}")
        time.sleep(10)  # adjust your polling interval

threading.Thread(target=worker_loop, daemon=True).start()
