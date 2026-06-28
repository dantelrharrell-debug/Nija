# bot/__init__.py
"""
NIJA Bot Package
Core trading modules for the NIJA autonomous trading system
"""

import sys
import os
import logging

# OKX uses direct REST with HMAC-SHA256 signed HTTPS calls.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)

try:
    from .okx_runtime_patch import install_import_hook as _install_okx_runtime_patch
    _install_okx_runtime_patch()
except Exception as _okx_patch_exc:
    logger.warning("OKX runtime patch unavailable: %s", _okx_patch_exc)

__version__ = "7.2.0"

logger.debug(f"NIJA Bot package initialized (v{__version__})")
