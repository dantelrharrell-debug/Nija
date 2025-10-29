# wsgi.py
from flask import Flask, jsonify
import threading
import time
import os
import logging

# Import our client wrapper from nija_client
# (expects the nija_client.py you pasted earlier)
from nija_client import client, get_accounts, place_order, DRY_RUN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_wsgi")

app = Flask(__name__)

# --- Global flag for trader status ---
trader_running = False

def check_live_status() -> bool:
    """
    Returns True if the system is configured to place live orders.
    Uses the client flags and the DRY_RUN global from nija_client.
    """
    try:
        is_live_flag = getattr(client, "is_live", False)
        is_dummy_flag = getattr(client, "is_dummy", False)
        return bool(is_live_flag) and (not bool(DRY_RUN)) and (not bool(is_dummy_flag))
    except Exception:
        return False

# --- Trader loop ---
def run_trader(interval: int = 5):
    """
    Simple trader loop:
    - fetches accounts
    - attempts a tiny buy order (example)
    """
    global trader_running
    trader_running = True
    logger.info(f"[NIJA] Trader loop started. DRY_RUN={DRY_RUN} client_is_live={getattr(client,'is_live',False)}")

    try:
        while True:
            try:
                accounts = get_accounts()
                logger.info(f"[NIJA] Accounts fetched: {accounts}")

                # Example trading logic (replace with your real algo)
                order_resp = place_order(
                    side="buy",
                    product_id="BTC-USD",
                    size="0.001",
                    price="50000.00",
                    order_type="limit"
                )

                # Decide logging based on whether the order was simulated
                simulated = order_resp.get("simulated", True) if isinstance(order_resp, dict) else True

                if check_live_status() and not simulated:
                    logger.info("[NIJA] LIVE ORDER placed: %s", order_resp)
                else:
                    logger.info("[NIJA] SIMULATED order (dry run/dummy): %s", order_resp)

            except Exception as e:
                logger.exception("[NIJA] Error in trading loop: %s", e)

            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("[NIJA] Trader stopped by KeyboardInterrupt")
    finally:
        trader_running = False
        logger.info("[NIJA] Trader loop exited")

# --- Health check endpoint ---
@app.route("/health", methods=["GET"])
def health_check():
    try:
        accounts = get_accounts()
    except Exception as e:
        accounts = [{"error": str(e)}]
    return jsonify({
        "status": "Flask alive",
        "trader": "running" if trader_running else "stopped",
        "coinbase_live": check_live_status(),
        "accounts_sample": accounts
    })

# --- Start trader in background thread when run as main ---
if __name__ == "__main__":
    # Use environment variable to control dry run interval or trading toggles if needed
    interval = int(os.getenv("TRADER_INTERVAL", "5"))
    start_trader = os.getenv("START_TRADER", "true").lower() in ("1", "true", "yes")

    if start_trader:
        trader_thread = threading.Thread(target=run_trader, args=(interval,), daemon=True)
        trader_thread.start()
        logger.info("[NIJA] Trader background thread started")

    # Start Flask (development server). In production gunicorn will import this module.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
