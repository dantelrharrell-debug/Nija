# wsgi.py
from flask import Flask, jsonify
import threading
import time
import os
import logging

# --- Color codes for terminal ---
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_wsgi")

# --- Attempt to import Coinbase client ---
try:
    from nija_client import client as real_client, check_live_status as real_check
    client = real_client
    check_live_status = real_check
    LIVE_CLIENT_AVAILABLE = True
    logger.info(f"{GREEN}[NIJA] Coinbase client available. Running in LIVE MODE.{RESET}")
except Exception as e:
    logger.warning(f"{YELLOW}[NIJA] Coinbase client not available. Using DummyClient. Reason: {e}{RESET}")
    LIVE_CLIENT_AVAILABLE = False

    class DummyClient:
        def get_accounts(self):
            logger.info(f"{YELLOW}[NIJA-DUMMY] get_accounts called{RESET}")
            return [{"currency": "USD", "balance": "1000"}]

        def place_order(self, **kwargs):
            logger.info(f"{YELLOW}[NIJA-DUMMY] place_order called with {kwargs}{RESET}")
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
    mode = "DRY RUN" if dry_run else "LIVE TRADING"
    color = YELLOW if dry_run else GREEN
    logger.info(f"{color}[NIJA] Trader loop started. Mode: {mode}{RESET}")

    try:
        while True:
            try:
                accounts = client.get_accounts()
                logger.info(f"{color}[NIJA] Accounts fetched: {accounts}{RESET}")

                if not dry_run:
                    order = client.place_order(
                        product_id="BTC-USD",
                        side="buy",
                        price="50000.00",
                        size="0.001"
                    )
                    logger.info(f"{GREEN}[NIJA] LIVE ORDER placed: {order}{RESET}")
                else:
                    logger.info(f"{YELLOW}[NIJA] Dry run enabled. No order placed.{RESET}")

            except Exception as e:
                logger.exception(f"{YELLOW}[NIJA] Error in trading loop: {e}{RESET}")
            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info(f"{YELLOW}[NIJA] Trader stopped{RESET}")
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
