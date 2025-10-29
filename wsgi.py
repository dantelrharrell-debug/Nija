# wsgi.py
from flask import Flask, jsonify
from nija_client import client, check_live_status
import threading
import time
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_wsgi")

app = Flask(__name__)

# --- Global flag for trader status ---
trader_running = False

# --- Trader loop ---
def run_trader(dry_run=False, interval=5):
    global trader_running
    trader_running = True
    logger.info(f"[NIJA] Trader loop started. Dry run: {dry_run}")
    try:
        while True:
            try:
                accounts = client.get_accounts()
                logger.info(f"[NIJA] Accounts fetched: {accounts}")

                # Example trade logic
                if not dry_run:
                    order = client.place_order(
                        product_id="BTC-USD",
                        side="buy",
                        price="50000.00",
                        size="0.001"
                    )
                    logger.info(f"[NIJA] Order placed: {order}")
                else:
                    logger.info("[NIJA] Dry run enabled. No order placed.")

            except Exception as e:
                logger.exception("[NIJA] Error in trading loop")
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("[NIJA] Trader stopped")
    finally:
        trader_running = False

# --- Health check endpoint ---
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "Flask alive",
        "trader": "running" if trader_running else "stopped",
        "coinbase_live": check_live_status()
    })

# --- Start trader in background thread ---
if __name__ == "__main__":
    DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"
    trader_thread = threading.Thread(target=run_trader, args=(DRY_RUN,), daemon=True)
    trader_thread.start()
    # Start Flask
    app.run(host="0.0.0.0", port=10000)
