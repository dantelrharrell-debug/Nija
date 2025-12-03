import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("coinbase_trader")

def main():
    logger.info("coinbase_trader started.")
    try:
        while True:
            # Replace this with your trading loop
            time.sleep(5)
            logger.info("coinbase_trader heartbeat...")
    except Exception as e:
        logger.exception("coinbase_trader crashed:", exc_info=e)

if __name__ == "__main__":
    main()
