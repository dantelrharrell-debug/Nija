import logging
from loguru import logger

def configure_logging(app):
    # Standard Flask logging
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    app.logger.addHandler(handler)
    
    # Optional: Loguru integration
    logger.add("logs/bot.log", rotation="1 MB")
