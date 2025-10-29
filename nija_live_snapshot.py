# nija_live_snapshot.py
import logging
import time
from nija_client import client, check_live_status

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_live_snapshot")

# --- Health Check ---
if not check_live_status():
    logger.warning("[NIJA] Coinbase client not live. Running in Dummy mode.")

# --- Trading loop ---
def run_trader(dry_run=False, interval=5):
    """
    Simple live trading loop. Runs continuously every `interval` seconds.
    `dry_run=True` avoids placing real orders.
    """
    logger.info(f"[NIJA] Starting trader loop. Dry run: {dry_run}")
    try:
        while True:
            try:
                accounts = client.get_accounts()
                logger.info(f"[NIJA] Accounts fetched: {accounts}")
                
                # Example trade logic (replace with your strategy)
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
        logger.info("[NIJA] Trader stopped by user")

# --- Entry point ---
if __name__ == "__main__":
    # Set DRY_RUN from env variable (default True)
    import os
    DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"
    run_trader(dry_run=DRY_RUN)
