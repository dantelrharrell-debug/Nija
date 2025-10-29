# nija_live_snapshot.py
import os
import logging
import threading
import time
from flask import Flask, jsonify
from nija_client import client, check_live_status, get_accounts, place_order

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_live_snapshot")

app = Flask(__name__)

# Simple background trader for demo (honors DRY_RUN)
def trader_loop(dry_run=True, interval=5):
    logger.info("[NIJA] Starting trader loop. Dry run: %s", dry_run)
    try:
        while True:
            try:
                accounts = get_accounts()
                logger.info("[NIJA] Accounts fetched: %s", accounts)
                if not dry_run:
                    # Example order (replace with your real logic)
                    order = place_order(product_id="BTC-USD", side="buy", price="50000.00", size="0.001")
                    logger.info("[NIJA] Order placed: %s", order)
                else:
                    logger.info("[NIJA] Dry run enabled. No order placed.")
            except Exception as e:
                logger.exception("[NIJA] Trading loop error: %s", e)
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("[NIJA] Trader loop stopped")

@app.route("/health")
def health():
    live = check_live_status()
    return jsonify({
        "status": "alive",
        "trading": "live" if live and os.getenv("DRY_RUN", "true").lower() == "false" else "dry-run",
        "coinbase_live": bool(live)
    }), 200

if __name__ == "__main__":
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
    t = threading.Thread(target=trader_loop, args=(DRY_RUN,), daemon=True)
    t.start()
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
