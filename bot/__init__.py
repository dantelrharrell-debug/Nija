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
# connecting.
#
# Root cause: candlelite resolves and CACHES its config directory at import
# time.  Setting CANDLELITE_CONFIG_DIR after candlelite has already been
# imported has no effect because the path is baked into module-level variables.
#
# Fix (three-layer defence):
#   1. Force-set the env var unconditionally (os.environ[...] = ..., NOT
#      setdefault) so it wins even if something set it earlier to a bad value.
#   2. Create the target directory so candlelite never needs to fall back.
#   3. After setting the env var, eagerly import candlelite and overwrite every
#      known module-level attribute that holds the config path so that any
#      already-cached value is corrected before okx.api is imported.
_candlelite_dir = os.path.join(os.environ.get("TMPDIR", "/tmp"), "candlelite")
try:
    os.makedirs(_candlelite_dir, exist_ok=True)
except OSError:
    _candlelite_dir = os.environ.get("TMPDIR", "/tmp")

# Force-set — never use setdefault here; we must win over any stale value.
os.environ["CANDLELITE_CONFIG_DIR"] = _candlelite_dir

# Eagerly import candlelite (if installed) and patch its cached config path so
# that the module-level variables reflect /tmp/candlelite rather than the
# read-only site-packages directory, regardless of import order.
try:
    import candlelite  # noqa: F401 — side-effect import to trigger caching

    # Patch every attribute that candlelite (and its sub-modules) use to store
    # the resolved config directory.  Attribute names observed in candlelite
    # source: CONFIG_DIR, config_dir, SETTINGS_DIR, settings_dir, BASE_DIR.
    # We patch all plausible names defensively.
    _cl_patch_attrs = (
        "CONFIG_DIR", "config_dir",
        "SETTINGS_DIR", "settings_dir",
        "BASE_DIR", "base_dir",
        "CONFIG_PATH", "config_path",
    )
    import sys as _sys
    for _mod_name, _mod in list(_sys.modules.items()):
        if _mod_name == "candlelite" or _mod_name.startswith("candlelite."):
            for _attr in _cl_patch_attrs:
                if hasattr(_mod, _attr):
                    _old = getattr(_mod, _attr)
                    # Only patch string attributes that look like paths pointing
                    # into site-packages (i.e. NOT already under /tmp).
                    if isinstance(_old, str) and "/tmp" not in _old:
                        setattr(_mod, _attr, _candlelite_dir)
            # Also patch SETTINGS_FILE / config_file if they point to the
            # read-only site-packages location.
            for _file_attr in ("SETTINGS_FILE", "settings_file", "CONFIG_FILE", "config_file"):
                if hasattr(_mod, _file_attr):
                    _old_file = getattr(_mod, _file_attr)
                    if isinstance(_old_file, str) and "/tmp" not in _old_file:
                        import os.path as _osp
                        setattr(
                            _mod,
                            _file_attr,
                            _osp.join(_candlelite_dir, _osp.basename(_old_file)),
                        )
except ImportError:
    pass  # candlelite not installed — nothing to patch
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
