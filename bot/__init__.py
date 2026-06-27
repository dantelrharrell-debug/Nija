# bot/__init__.py
"""
NIJA Bot Package
Core trading modules for the NIJA autonomous trading system
"""

import sys
import os
import logging

# ── candlelite writable config dir ───────────────────────────────────────────
# OKX trading is disabled (ENABLE_OKX_TRADING=false). The candlelite
# monkey-patching code has been removed. We still set CANDLELITE_CONFIG_DIR
# to a writable /tmp path as a harmless precaution.
_candlelite_dir = os.path.join(os.environ.get("TMPDIR", "/tmp"), "candlelite")
try:
    os.makedirs(_candlelite_dir, exist_ok=True)
except OSError:
    _candlelite_dir = os.environ.get("TMPDIR", "/tmp")

os.environ["CANDLELITE_CONFIG_DIR"] = _candlelite_dir
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
