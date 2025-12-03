import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("tv_webhook_listener")

def main():
    logger.info("tv_webhook_listener started.")
    try:
        while True:
            # Replace this with your actual webhook listener code
            time.sleep(5)
            logger.info("tv_webhook_listener heartbeat...")
    except Exception as e:
        logger.exception("tv_webhook_listener crashed:", exc_info=e)

if __name__ == "__main__":
    main()
