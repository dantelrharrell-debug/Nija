# main.py
import time
import logging
from loguru import logger as loguru_logger

# Use the package import style so Python finds app/nija_client.py
from app.nija_client import CoinbaseClient

# Configure Python logging (optional - you can keep loguru in nija_client too)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_main")

def start_bot_main():
    logger.info("Starting Nija bot (main.py)...")
    try:
        client = CoinbaseClient()  # expects env vars / .env handling inside nija_client
    except Exception as e:
        logger.exception("Failed to initialize CoinbaseClient: %s", e)
        return

    # Single-run startup check: fetch accounts once and print result
    try:
        accounts = client.get_accounts()
        if accounts:
            logger.info("Accounts response received (startup): %s", accounts)
        else:
            logger.warning("Accounts fetch returned no data (startup).")
    except Exception as e:
        logger.exception("Error fetching accounts on startup: %s", e)

    # Optional heartbeat loop: keeps process alive and retries
    try:
        while True:
            logger.info("heartbeat")
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.exception("Unexpected runtime error: %s", e)

if __name__ == "__main__":
    start_bot_main()
