#!/usr/bin/env python3
import logging
from nija_client import client, start_trading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("🌟 Starting Nija bot...")
    start_trading()
