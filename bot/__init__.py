# bot/__init__.py
"""
NIJA Bot Package
Core trading modules for the NIJA autonomous trading system
"""

import os
import logging

# Set up logging for the bot package
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

# Package version
__version__ = "7.2.0"

# Verify we're in the bot directory context
logger.debug(f"NIJA Bot package initialized (v{__version__})")

