# start_bot.py
import os
import time
from loguru import logger

# Import our minimal Coinbase client
from nija_client import CoinbaseClient

logger.info("Starting Nija bot — LIVE mode")

# Initialize the client
try:
    client = CoinbaseClient(
        base=os.getenv("COINBASE_BASE"),
        jwt=os.getenv("COINBASE_JWT")  # optional for now
    )
except Exception as e:
    logger.error(f"Failed to initialize CoinbaseClient: {e}")
    raise SystemExit(1)

# Main loop stub — avoids crashing
def main_loop():
    tick = 0
    while True:
        tick += 1
        logger.info(f"[Tick {tick}] Checking accounts/balance...")

        try:
            accounts = client.get_accounts()
            if not accounts:
                logger.warning("[NIJA-BALANCE] No accounts returned (stub mode)")
            else:
                logger.info(f"Fetched {len(accounts)} accounts")
        except Exception as e:
            logger.error(f"Error fetching accounts: {e}")

        try:
            balance = client.get_balance()
            logger.info(f"[NIJA-BALANCE] Total balance: {balance}")
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")

        time.sleep(5)  # 5s between ticks; adjust as needed

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Nija bot stopped manually.")
