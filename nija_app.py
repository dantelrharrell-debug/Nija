# nija_app.py
import logging
from threading import Thread
from time import sleep

from nija_client import CoinbaseClient, get_usd_balance  # <-- safe import

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_app")

# --- Initialize client ---
client = CoinbaseClient()  # Will be real or DummyClient safely

# --- PEM setup (if you use it for Coinbase auth) ---
def write_pem():
    try:
        pem_content = "YOUR PEM CONTENT HERE"
        with open("/tmp/coinbase.pem", "w") as f:
            f.write(pem_content)
        logger.info("[NIJA] PEM written")
    except Exception as e:
        logger.warning(f"[NIJA] Could not write PEM: {e}")

write_pem()

# --- Worker Thread ---
def nija_worker():
    logger.info("[NIJA-WORKER] Started")
    while True:
        try:
            usd_balance = get_usd_balance(client)
            logger.info(f"[NIJA-WORKER] USD Balance: {usd_balance}")
            # --- Place your trading logic here ---
        except Exception as e:
            logger.error(f"[NIJA-WORKER] Error: {e}")
        sleep(5)  # adjust loop timing as needed

# --- Start worker thread ---
Thread(target=nija_worker, daemon=True).start()
logger.info("[NIJA-APP] Worker thread started")

# --- Flask App ---
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"status": "NIJA app running", "client": type(client).__name__})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
