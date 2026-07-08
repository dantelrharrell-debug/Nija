from __future__ import annotations

import logging

logger = logging.getLogger("nija.execution_route_integrity_import_guard")


def install_import_hook() -> None:
    logger.warning("EXECUTION_ROUTE_INTEGRITY_IMPORT_GUARD_DISABLED marker=20260707b reason=prevent_recursive_import_spam")


def install() -> None:
    install_import_hook()
