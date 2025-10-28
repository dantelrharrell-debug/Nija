#!/usr/bin/env python3
# nija_live_snapshot.py
import os
import time
import logging
from nija_client import client, get_accounts, place_order

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# -------------------------------
# Health check (optional)
# -------------------------------
def health_check():
    try:
        accounts = get_accounts()
        status = "live" if accounts else "no accounts"
        logger.info(f"Health check: {status}")
        return status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return "error"

# -------------------------------
# Main loop
# -------------------------------
def main_loop():
    logger.info("🌟 Starting Nija bot main loop...")
    while True:
        try:
            # Example trading logic
            accounts = get_accounts()
            if accounts:
                logger.info(f"Connected to {len(accounts)} account(s).")
                # Example: place dummy order
                # place_order("BTC-USD", "buy", Decimal("0.001"))
            else:
                logger.warning("No accounts detected!")
            time.sleep(10)
        except KeyboardInterrupt:
            logger.info("🚨 Nija bot stopped manually.")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main_loop()
