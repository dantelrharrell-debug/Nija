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
# environments this raises [Errno 13] Permission denied.
#
# We set CANDLELITE_CONFIG_DIR here so that if candlelite is imported later
# (e.g. transitively through the okx SDK) it will pick up the writable path.
# We do NOT eagerly import candlelite here — doing so causes it to initialise
# and write to site-packages BEFORE the env var can take effect, which is the
# exact crash we are trying to prevent.
#
# OKX trading is currently disabled (ENABLE_OKX_TRADING=false in railway.json)
# so candlelite will not be imported at all during normal operation.
_candlelite_dir = os.path.join(os.environ.get("TMPDIR", "/tmp"), "candlelite")
try:
    os.makedirs(_candlelite_dir, exist_ok=True)
except OSError:
    _candlelite_dir = os.environ.get("TMPDIR", "/tmp")

# Force-set — never use setdefault here; we must win over any stale value.
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
