import os
import sys
import time
from loguru import logger
from nija_client import CoinbaseClient  # our advanced-ready client

logger = logger.bind(name="nija_startup")

# Force Advanced JWT mode
client = CoinbaseClient(advanced=True)

def list_accounts():
    try:
        accounts = client.get_accounts()
        for acc in accounts:
            bal = acc.get("balance", {})
            logger.info(f"Account: {acc.get('name')} | Balance: {bal.get('amount')} {bal.get('currency')}")
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")

def live_trading_loop():
    logger.info("Starting live trading loop...")
    while True:
        try:
            accounts = client.get_accounts()
            for acc in accounts:
                bal = acc.get("balance", {})
                logger.info(f"[LIVE CHECK] {acc.get('name')}: {bal.get('amount')} {bal.get('currency')}")
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Live trading stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    list_accounts()
    live_trading_loop()
