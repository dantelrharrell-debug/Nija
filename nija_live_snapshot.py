#!/usr/bin/env python3
import logging
import time
from nija_client import client, start_trading, get_accounts

# ------------------------------
# Logging setup
# ------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ------------------------------
# Main bot loop
# ------------------------------
def main():
    logging.info("🌟 Nija bot is starting...")
    
    # Check accounts first
    accounts = get_accounts()
    if not accounts:
        logging.error("❌ No accounts available. Cannot start trading loop.")
        return

    logging.info("🔥 Trading loop starting...")
    
    try:
        while True:
            for account in accounts:
                try:
                    logging.info(f" - {account['currency']}: {account['balance']['amount']}")
                except (TypeError, KeyError):
                    logging.warning(f"Skipping malformed account data: {account}")
            # Add your trading logic here
            time.sleep(5)  # loop delay for demonstration
    except KeyboardInterrupt:
        logging.info("🛑 Nija bot stopped by user.")

if __name__ == "__main__":
    main()
