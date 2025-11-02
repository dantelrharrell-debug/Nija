from flask import Flask
import logging
import time
from decimal import Decimal
from nija_client import client, get_usd_balance
from threading import Thread

# -----------------------------
# Flask app
# -----------------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija is live"

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_app")

# -----------------------------
# Worker loop
# -----------------------------
def nija_worker():
    logger.info("[NIJA-WORKER] Starting worker loop...")
    while True:
        try:
            balance = get_usd_balance()
            logger.info(f"[NIJA-WORKER] USD Balance: {balance}")

            # -----------------------------
            # Example live trade logic
            # -----------------------------
            if balance > 10:
                logger.info("[NIJA-WORKER] Ready to trade. Add your BUY/SELL logic here.")

            time.sleep(5)
        except Exception as e:
            logger.exception(f"[NIJA-WORKER] Error in worker loop: {e}")
            time.sleep(5)

# -----------------------------
# Start worker in background thread
# -----------------------------
worker_thread = Thread(target=nija_worker, daemon=True)
worker_thread.start()

# -----------------------------
# Preflight check
# -----------------------------
try:
    balance = get_usd_balance()
    logger.info(f"[NIJA-APP] Preflight check passed. USD Balance: {balance}")
    logger.info("[NIJA-APP] Nija bot is live")
except Exception as e:
    logger.error(f"[NIJA-APP] Cannot start bot: {e}")
    raise SystemExit("[NIJA] Fix Coinbase credentials or connection before running.")
