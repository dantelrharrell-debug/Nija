import os
import sys
import logging
import time
from trading.bot import TradingBot
from trading.config import TradingConfig
from trading.api import TradingAPI
from trading.utils import setup_logging


def run_live_trading():
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        config = TradingConfig()
        api = TradingAPI(config)
        bot = TradingBot(config, api)
        logger.info("Starting live trading bot...")
        bot.run()
    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    run_live_trading()
