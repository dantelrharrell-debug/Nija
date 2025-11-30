# bot/live_bot_script.py
import time
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def start_trading_loop():
    """
    Safe placeholder trading loop. Replace with your real bot implementation.
    Only runs when START_BOT=1 and import succeeds.
    """
    logger.info("start_trading_loop() placeholder started (no live trading).")
    try:
        while True:
            # Do tiny heartbeat work so we can confirm the thread is alive
            logger.info("bot heartbeat")
            time.sleep(60)  # once per minute; adjust if you need faster logs during testing
    except Exception:
        logger.exception("placeholder trading loop exiting.")
