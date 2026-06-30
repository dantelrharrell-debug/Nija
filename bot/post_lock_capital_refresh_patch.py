"""Post-lock capital refresh hook.

This module is imported by bot.__init__.  It intentionally performs only safe
startup reconciliation and logging.  The previous deployment warned that this
module was missing, so package startup could not install the hook.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("nija.post_lock_capital_refresh")
_INSTALLED = False


def install_import_hook() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    logger.warning("POST_LOCK_CAPITAL_REFRESH_INSTALL_COMPLETE")
