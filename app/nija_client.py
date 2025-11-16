# main.py
import time
import logging
from app.nija_client import CoinbaseClient  # <-- import package.module style

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_main")

def start_bot_main():
    logger.info("Starting Nija bot (main.py)...")
    client = CoinbaseClient()  # will load env vars internally if coded that way
    try:
        accounts = client.get_accounts()
        logger.info("Accounts response: %s", accounts)
    except Exception as e:
        logger.exception("Startup error: %s", e)

if __name__ == "__main__":
    start_bot_main()
    # keep process alive if you want a heartbeat loop:
    # while True:
    #     logger.info("heartbeat")
    #     time.sleep(5)
