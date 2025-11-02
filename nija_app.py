# -----------------------------
# nija_app.py — LIVE VERSION
# -----------------------------
import os
import time
import logging
from threading import Thread
from decimal import Decimal
from flask import Flask

from nija_client import init_client, get_usd_balance
from nija_write_pem import PEM_PATH  # this writes the PEM file before init_client

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_app")

# -----------------------------
# Initialize Coinbase client
# -----------------------------
try:
    client = init_client(pem_path=PEM_PATH)
    logger.info("[NIJA-APP] Coinbase client initialized successfully.")
except Exception as e:
    logger.error(f"[NIJA-APP] Failed to initialize Coinbase client: {e}")
    raise SystemExit("[NIJA] Fix PEM or Coinbase credentials before running.")

# -----------------------------
# Worker function
# -----------------------------
def nija_worker():
    logger.info("[NIJA-WORKER] Starting worker loop...")
    while True:
        try:
            balance = get_usd_balance(client)
            logger.info(f"[NIJA-WORKER] USD Balance: {balance}")

            # Example trading logic
            if balance > 10:
                logger.info("[NIJA-WORKER] Balance sufficient — trading logic would trigger here.")

            time.sleep(5)
        except Exception as e:
            logger.exception(f"[NIJA-WORKER] Error in worker loop: {e}")
            time.sleep(5)

# -----------------------------
# Start worker thread in background
# -----------------------------
worker_thread = Thread(target=nija_worker, daemon=True)
worker_thread.start()
logger.info("[NIJA-APP] Nija live trading worker started in background thread.")

# -----------------------------
# Flask app (for Render health checks)
# -----------------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija is live"

# -----------------------------
# Local testing entrypoint
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
