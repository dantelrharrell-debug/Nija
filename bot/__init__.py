# bot/__init__.py
"""
NIJA Bot Package
Core trading modules for the NIJA autonomous trading system
"""

import sys
import os
import logging

# ── OKX uses direct REST — no candlelite / okx SDK import needed ─────────────
# NIJA's OKX integration uses _OKXRestClient (HMAC-SHA256 signed HTTPS calls)
# instead of the upstream okx/candlelite SDK, so no environment patching is
# required.  The block below is intentionally removed.
# ─────────────────────────────────────────────────────────────────────────────

# Set up logging for the bot package
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)

# Package version
__version__ = "7.2.0"

# Verify we're in the bot directory context
logger.debug(f"NIJA Bot package initialized (v{__version__})")
