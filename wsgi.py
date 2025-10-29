# wsgi.py
from flask import Flask, jsonify
import threading
import time
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_wsgi")

# --- Attempt to import Coinbase client ---
try:
    from nija_client import client as real_client, check_live_status as real_check
    client = real_client
    check_live_status = real_check
    LIVE_CLIENT_AVAILABLE = True
    logger.info("[NIJA] Coinbase client available. Using live client.")
except Exception as e:
    logger.warning(f"[NIJA] Coinbase client not available. Using DummyClient. Reason: {e}")
    LIVE_CLIENT_AVAILABLE = False

    class DummyClient:
        def get_accounts(self):
            logger.info("[NIJA-DUMMY] get_accounts called")
            return [{"currency": "USD", "balance": "1000"}]

        def place_order(self, **kwargs):
            logger.info(f"[NIJA-DUMMY] place_order called with {kwargs}")
            return {"status": "dummy", "order": kwargs}

    client = DummyClient()
    def check_live_status():
        return False

app = Flask(__name__)

# --- Global flag for trader status ---
trader_running = False

# --- Trader loop ---
def run_trader(dry_run=True, interval=5):
    global trader_running
    trader_running = True
    logger.info(f"[NIJA] Trader loop started. Dry run: {dry_run}")

    try:
        while True:
            try:
                accounts = client.get_accounts()
                logger.info(f"[NIJA] Accounts fetched: {accounts}")

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

# --- Determine DRY_RUN automatically ---
DRY_RUN_ENV = os.getenv("DRY_RUN")
if DRY_RUN_ENV is not None:
    DRY_RUN = DRY_RUN_ENV.lower() == "true"
else:
    # Auto-disable dry run if live client detected
    DRY_RUN = not LIVE_CLIENT_AVAILABLE

logger.info(f"[NIJA] DRY_RUN is set to {DRY_RUN}")

# --- Start trader in background thread ---
trader_thread = threading.Thread(target=run_trader, args=(DRY_RUN,), daemon=True)
trader_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
