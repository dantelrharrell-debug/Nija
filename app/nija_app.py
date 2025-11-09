# nija_app.py
from loguru import logger
from nija_coinbase_advanced import client as cb_adv_client
import time

logger = logger.bind(name="nija_app")

# --- Test Advanced client ---
try:
    accounts = cb_adv_client.get_accounts()
    if not accounts:
        logger.error("No accounts returned. Bot will not start.")
        exit(1)
    logger.info(f"Coinbase Advanced client ready. Found {len(accounts)} account(s).")
except Exception as e:
    logger.exception(f"Failed to fetch accounts: {e}")
    exit(1)

# --- Live trading loop ---
def live_trading_loop():
    logger.info("Starting live trading loop...")
    while True:
        try:
            balances = cb_adv_client.get_spot_account_balances()
            logger.info(f"Balances: {balances}")
            # Placeholder: replace with your signal/trade logic
            logger.info("Checking for trading signals...")
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Live trading stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    live_trading_loop()
