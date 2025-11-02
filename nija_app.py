from flask import Flask

app = Flask(__name__)

# Your routes and initialization
@app.route("/")
def index():
    return "Nija is live"

# -----------------------------
# nija_app.py (LIVE ONLY)
# -----------------------------
import logging
import time
from decimal import Decimal
from nija_client import client, get_usd_balance

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
            # Replace with your actual trading logic
            if balance > 10:  # just a safety example
                logger.info("[NIJA-WORKER] Ready to trade. Add your BUY/SELL logic here.")

            time.sleep(5)  # Adjust sleep for desired frequency
        except KeyboardInterrupt:
            logger.info("[NIJA-WORKER] KeyboardInterrupt received. Stopping worker.")
            break
        except Exception as e:
            logger.exception(f"[NIJA-WORKER] Error in worker loop: {e}")
            time.sleep(5)

# -----------------------------
# Run preflight check
# -----------------------------
if __name__ == "__main__":
    try:
        balance = get_usd_balance()
        logger.info(f"[NIJA-APP] Preflight check passed. USD Balance: {balance}")
        logger.info("[NIJA-APP] Starting LIVE bot...")

        nija_worker()
    except Exception as e:
        logger.error(f"[NIJA-APP] Cannot start bot: {e}")
        raise SystemExit("[NIJA] Fix Coinbase credentials or connection before running.")
