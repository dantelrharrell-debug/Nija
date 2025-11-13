# main.py
import time, sys
from loguru import logger
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)
logger.info("Nija bot starting... (debug main.py)")
try:
    from app.start_bot_main import start_bot_main
    logger.info("Imported start_bot_main OK")
except Exception as e:
    logger.exception("Import start_bot_main failed: %s", e)
while True:
    logger.info("heartbeat")
    sys.stdout.flush()
    time.sleep(60)
