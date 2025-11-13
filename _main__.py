# main.py
import time
import sys
from loguru import logger

# Import your bot startup
from app.start_bot_main import main as start_bot_main

# Configure loguru to log to stdout (so Render can see it)
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True, backtrace=True, diagnose=True)

if __name__ == "__main__":
    logger.info("🔹 Nija Bot container starting...")

    try:
        # Start your bot
        logger.info("🔹 Initializing Nija Bot...")
        start_bot_main()
        logger.info("✅ Nija Bot started successfully.")
    except Exception as e:
        logger.exception(f"❌ Bot failed to start: {e}")
        # Keep container alive so you can see logs
        while True:
            logger.error("Bot failed to start. Container alive for debugging.")
            time.sleep(60)

    # Keep container alive with heartbeat logs
    while True:
        logger.info("💓 Heartbeat: container is alive")
        time.sleep(60)
