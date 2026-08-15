"""Tune startup position-fetch timeout without weakening position-sync safety.

Production logs on 2026-08-15 showed authoritative Kraken position snapshots
crossing the v95 five-second default. v95 correctly failed closed, but the
short default caused repeated timeout/invalidation during otherwise healthy
broker startup.

v98 changes only the *default* timeout to 12 seconds. An explicit
NIJA_POSITION_FETCH_TIMEOUT_S value remains authoritative. v99 is installed
from the same canonical slot so platform readiness is isolated from slow user
position snapshots while each user execution path remains fail closed. v100
uses that same early fast-path slot to install bounded canonical TradingStrategy
class recovery before Step 2.5 publication can consume a stale partial module.
"""
from __future__ import annotations

import logging
import os
from typing import Any

LOGGER = logging.getLogger("nija.position_sync_timeout_v98")
MARKER = "20260815-position-sync-timeout-v98"
_DEFAULT_TIMEOUT_S = 12.0
_INSTALLED = False


def _timeout_s_v98() -> float:
    raw = os.environ.get("NIJA_POSITION_FETCH_TIMEOUT_S")
    if raw is None or not str(raw).strip():
        return _DEFAULT_TIMEOUT_S
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_S


def _install_v99() -> bool:
    try:
        from bot import position_sync_account_isolation_v99_patch as v99
    except ImportError:
        import position_sync_account_isolation_v99_patch as v99  # type: ignore[import]
    installer = getattr(v99, "install_import_hook", None) or getattr(v99, "install", None)
    if not callable(installer):
        return False
    return installer() is not False


def _install_v100() -> bool:
    try:
        from bot import canonical_strategy_class_recovery_v100_patch as v100
    except ImportError:
        import canonical_strategy_class_recovery_v100_patch as v100  # type: ignore[import]
    installer = getattr(v100, "install_import_hook", None) or getattr(v100, "install", None)
    if not callable(installer):
        return False
    return installer() is not False


def install() -> bool:
    global _INSTALLED

    try:
        from bot import position_sync_core_handoff_v95_patch as v95
    except ImportError:
        import position_sync_core_handoff_v95_patch as v95  # type: ignore[import]

    setattr(v95, "_timeout_s", _timeout_s_v98)
    if not _install_v99():
        LOGGER.critical(
            "POSITION_SYNC_TIMEOUT_V98_V99_INSTALL_FAILED marker=%s trading_fail_closed=true",
            MARKER,
        )
        return False
    if not _install_v100():
        LOGGER.critical(
            "POSITION_SYNC_TIMEOUT_V98_V100_INSTALL_FAILED marker=%s trading_fail_closed=true",
            MARKER,
        )
        return False

    if _INSTALLED:
        return True

    os.environ["NIJA_POSITION_SYNC_TIMEOUT_V98_INSTALLED"] = "1"
    _INSTALLED = True
    LOGGER.critical(
        "POSITION_SYNC_TIMEOUT_V98_INSTALLED marker=%s default_timeout_s=%.1f "
        "explicit_env_override_preserved=true account_isolation_v99=true "
        "strategy_class_recovery_v100=true safety_gates_unchanged=true",
        MARKER,
        _DEFAULT_TIMEOUT_S,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_timeout_s_v98"]
