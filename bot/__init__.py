# bot/__init__.py
"""
NIJA Bot Package
Core trading modules for the NIJA autonomous trading system
"""

import os
import logging

# ── candlelite writable config dir ───────────────────────────────────────────
# The okx SDK depends on candlelite, which tries to write SETTINGS.config into
# its own site-packages directory on first import.  In containerised / read-only
# environments this raises [Errno 13] Permission denied and prevents OKX from
# connecting.  We redirect candlelite to /tmp BEFORE any import that could
# trigger candlelite initialisation.  os.environ.setdefault() is used so an
# operator-supplied value is never overwritten.
_candlelite_dir = os.path.join(os.environ.get("TMPDIR", "/tmp"), "candlelite")
try:
    os.makedirs(_candlelite_dir, exist_ok=True)
except OSError:
    _candlelite_dir = os.environ.get("TMPDIR", "/tmp")
os.environ.setdefault("CANDLELITE_CONFIG_DIR", _candlelite_dir)
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
