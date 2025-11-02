# nija_app.py
from flask import Flask
import threading
import logging
from nija_client import client, get_usd_balance  # your existing client logic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_app")

# === THIS IS THE KEY: expose 'app' for Gunicorn ===
app = Flask(__name__)

@app.route("/")
def home():
    balance = get_usd_balance()
    return f"NIJA BOT LIVE! USD Balance: {balance}"

# Optional: start background worker thread
def worker_loop():
    import time
    while True:
        bal = get_usd_balance()
        logger.info(f"[NIJA] Periodic USD balance: {bal}")
        time.sleep(10)

threading.Thread(target=worker_loop, daemon=True).start()
