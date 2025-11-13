import time, sys
from loguru import logger

# Setup logger for Railway
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)

logger.info("Nija bot starting...")

try:
    from app.start_bot_main import start_bot_main
    logger.info("Imported start_bot_main OK")
    # Start your bot logic
    start_bot_main()
except Exception as e:
    logger.exception("Failed to import/start bot: %s", e)

# Heartbeat to show container is alive
while True:
    logger.info("heartbeat")
    sys.stdout.flush()
    time.sleep(60)
