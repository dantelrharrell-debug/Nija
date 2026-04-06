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

    logger.info("Initializing trading bot...")
    try:
        strategy = TradingStrategy()
        # Post-connection delay: allow nonce state to stabilise before the first
        # market scan.  The TradingStrategy __init__ already waits 45 s *before*
        # connecting; this additional pause runs *after* all brokers are connected
        # so the first run_trading_cycle() does not race against freshly-issued
        # nonces and trigger nonce-thrashing errors.
        _post_connect_delay = int(os.getenv("NIJA_POST_CONNECT_DELAY", "7"))
        if _post_connect_delay > 0:
            logger.info(
                f"⏱️  Post-connection stabilisation delay: {_post_connect_delay}s "
                "(override with NIJA_POST_CONNECT_DELAY env var)"
            )
            time.sleep(_post_connect_delay)
            logger.info("✅ Post-connection delay complete — starting first scan cycle")
        while True:
            start = time.perf_counter()
            strategy.run_trading_cycle()
            duration = time.perf_counter() - start
            logger.info(f"Scan cycle: {duration:.4f}s")
            time.sleep(150)
    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    run_live_trading()
