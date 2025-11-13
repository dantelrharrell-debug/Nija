# main.py
import time
import sys
from loguru import logger

# Setup logger to output to stdout (Railway reads stdout for logs)
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)

logger.info("Nija bot starting...")

# Import your bot main function
try:
    from app.start_bot_main import start_bot_main  # adjust path if different
    logger.info("Imported start_bot_main OK")
except Exception as e:
    logger.exception("Import start_bot_main failed: %s", e)

# Optional: start the bot if import succeeded
try:
    start_bot_main()
except Exception as e:
    logger.exception("Bot failed to start: %s", e)

# Keep the container alive and show heartbeat every minute
if __name__ == "__main__":
    while True:
        logger.info("heartbeat - Nija bot container is alive")
        sys.stdout.flush()
        time.sleep(60)
