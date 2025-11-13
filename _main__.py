import time
import sys
from loguru import logger

# Import your bot startup
from app.start_bot_main import main as start_bot_main

# Log to stdout, unbuffered
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True, backtrace=True, diagnose=True)

def keep_alive():
    while True:
        logger.info("💓 Heartbeat: container is alive")
        sys.stdout.flush()  # Ensure Railway sees logs immediately
        time.sleep(60)

if __name__ == "__main__":
    logger.info("🔹 Nija Bot container starting...")
    sys.stdout.flush()

    try:
        logger.info("🔹 Initializing Nija Bot...")
        sys.stdout.flush()
        start_bot_main()
        logger.info("✅ Nija Bot started successfully.")
        sys.stdout.flush()
    except Exception as e:
        logger.exception(f"❌ Bot failed to start: {e}")
        sys.stdout.flush()

    # Keep container alive with heartbeat
    keep_alive()
