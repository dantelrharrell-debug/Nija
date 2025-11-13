import time
from loguru import logger
import sys

# Ensure logs go to stdout
logger.remove()
logger.add(sys.stdout, level="INFO")

logger.info("Container started and main.py is running...")

# Keep container alive
while True:
    logger.info("Heartbeat: container is alive")
    time.sleep(60)
