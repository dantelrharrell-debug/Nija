import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
from trading_strategy import TradingStrategy

# Main trading logic and bot initialization goes here...
def run_live_trading():
    # Setup logging
    LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'nija.log'))
    logger = logging.getLogger("nija")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=2)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    if not logger.hasHandlers():
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    logger.info("\ud83d\udccb Initializing trading bot...")
    try:
        strategy = TradingStrategy()
        while True:
            strategy.run_trading_cycle()
            time.sleep(150)
    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    run_live_trading()
