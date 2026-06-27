# bot/__init__.py
"""
NIJA Bot Package
Core trading modules for the NIJA autonomous trading system
"""

import sys
import os
import logging

# ── candlelite writable config dir ───────────────────────────────────────────
# The okx SDK depends on candlelite, which tries to write SETTINGS.config into
# its own site-packages directory on first import.  In containerised / read-only
# environments this raises [Errno 13] Permission denied.
#
# Root cause: candlelite.settings initialises and writes to site-packages
# DURING the import statement itself, before any env var can take effect.
#
# Fix: pre-import candlelite.settings here and monkey-patch save_settings()
# and init_settings() to redirect all writes to a writable /tmp path.
# Because Python caches modules in sys.modules, when the okx SDK later does
# "import candlelite.settings" it gets our already-patched version.
_candlelite_dir = os.path.join(os.environ.get("TMPDIR", "/tmp"), "candlelite")
try:
    os.makedirs(_candlelite_dir, exist_ok=True)
except OSError:
    _candlelite_dir = os.environ.get("TMPDIR", "/tmp")

# Force-set — never use setdefault here; we must win over any stale value.
os.environ["CANDLELITE_CONFIG_DIR"] = _candlelite_dir

# Pre-import and patch candlelite.settings BEFORE the okx SDK can import it.
try:
    import candlelite.settings as cl_settings

    # Store original functions
    _original_save_settings = cl_settings.save_settings
    _original_init_settings = cl_settings.init_settings

    # Patch save_settings to redirect site-packages paths to /tmp
    def patched_save_settings(data=None, settings_path=None):
        if settings_path and '/site-packages/' in settings_path:
            settings_path = os.path.join(_candlelite_dir, 'SETTINGS.config')
        return _original_save_settings(data=data, settings_path=settings_path)

    # Patch init_settings to point CONFIG_DIR and SETTINGS_FILE at /tmp
    def patched_init_settings():
        cl_settings.SETTINGS_FILE = os.path.join(_candlelite_dir, 'SETTINGS.config')
        cl_settings.CONFIG_DIR = _candlelite_dir
        return _original_init_settings()

    cl_settings.save_settings = patched_save_settings
    cl_settings.init_settings = patched_init_settings
except ImportError:
    pass  # candlelite not installed; OKX broker will handle the missing dep
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
