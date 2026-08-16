"""Require the bounded Kraken read layer before platform position sync can start.

Production release v121 proved a startup ordering race: v98 installed v108
(platform position-sync dispatch) before v121 (bounded Kraken REST reads).  v108
can patch capital refresh and launch a Kraken reconciliation worker immediately.
If that first worker enters Kraken's shared private-API lock before v121 wraps the
concrete API object, the already-running HTTP request remains unbounded and later
bounded generations can queue behind the same lock indefinitely.

v122 closes that race without changing readiness semantics:

* v121 must be installed before v108 is allowed to dispatch Kraken work;
* v108 is installed only after that prerequisite is satisfied;
* as a defense in depth, v108's connected-unsynced discovery suppresses Kraken
  if the v121 installation flag is ever absent, while leaving other brokers
  eligible for their normal reconciliation path;
* no synthetic positions, readiness, writer authority, nonce authority, capital,
  risk, or execution authority are fabricated;
* no new import hook is added.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.kraken_position_sync_prereq_v122")
MARKER = "20260816-kraken-position-sync-prereq-v122"
RELEASE_ID = "20260816-runtime-convergence-v122"
_PATCH_ATTR = "_nija_kraken_position_sync_prereq_v122"
_LOCK = threading.RLock()
_INSTALLED = False


def _v121_ready() -> bool:
    return os.environ.get("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", "").strip() == "1"


def _ensure_v121() -> bool:
    try:
        from bot import kraken_read_timeout_v121_patch as v121
    except Exception:
        try:
            import kraken_read_timeout_v121_patch as v121  # type: ignore[import]
        except Exception as exc:
            LOGGER.critical(
                "KRAKEN_POSITION_SYNC_V122_V121_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False
    installer = getattr(v121, "install_import_hook", None) or getattr(v121, "install", None)
    if not callable(installer) or installer() is False or not _v121_ready():
        LOGGER.critical(
            "KRAKEN_POSITION_SYNC_V122_V121_PREREQ_FAILED marker=%s trading_fail_closed=true",
            MARKER,
        )
        return False
    return True


def _load_v108() -> ModuleType | None:
    try:
        from bot import platform_position_sync_v108_patch as v108
        return v108
    except Exception:
        try:
            import platform_position_sync_v108_patch as v108  # type: ignore[import]
            return v108
        except Exception as exc:
            LOGGER.critical(
                "KRAKEN_POSITION_SYNC_V122_V108_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return None


def _patch_v108(v108: ModuleType) -> bool:
    current = getattr(v108, "_connected_unsynced_platform_brokers", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def connected_unsynced_v122(manager: Any):
        brokers = list(current(manager) or [])
        if _v121_ready():
            return brokers

        allowed = []
        blocked = 0
        for broker_name, broker in brokers:
            if str(broker_name or "").strip().lower() == "kraken":
                blocked += 1
                continue
            allowed.append((broker_name, broker))

        if blocked:
            LOGGER.critical(
                "KRAKEN_POSITION_SYNC_V122_DISPATCH_BLOCKED marker=%s blocked=%d reason=v121_not_ready non_kraken_continues=true synthetic_empty_snapshot=false trading_fail_closed=true",
                MARKER,
                blocked,
            )
        return allowed

    setattr(connected_unsynced_v122, _PATCH_ATTR, True)
    setattr(connected_unsynced_v122, "__wrapped__", current)
    v108._connected_unsynced_platform_brokers = connected_unsynced_v122
    LOGGER.critical(
        "KRAKEN_POSITION_SYNC_V122_V108_PATCHED marker=%s v121_prerequisite=true non_kraken_dispatch_unchanged=true import_hook_added=false",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch") or sys.modules.get(
        "runtime_release_manifest_patch"
    )
    if not isinstance(manifest, ModuleType):
        try:
            import bot.runtime_release_manifest_patch as manifest  # type: ignore[no-redef]
        except Exception:
            return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["kraken_position_sync_prereq_v122"] = "NIJA_KRAKEN_POSITION_SYNC_PREREQ_V122_INSTALLED"
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if not _ensure_v121():
            return False

        v108 = _load_v108()
        if v108 is None:
            return False
        installer = getattr(v108, "install_import_hook", None) or getattr(v108, "install", None)
        if not callable(installer) or installer() is False:
            return False
        if not _patch_v108(v108):
            return False

        os.environ["NIJA_KRAKEN_POSITION_SYNC_PREREQ_V122_INSTALLED"] = "1"
        if not _patch_release_manifest():
            os.environ.pop("NIJA_KRAKEN_POSITION_SYNC_PREREQ_V122_INSTALLED", None)
            return False

        _INSTALLED = True
        LOGGER.critical(
            "KRAKEN_POSITION_SYNC_PREREQ_V122_INSTALLED marker=%s v121_ready=true v108_after_v121=true kraken_dispatch_fail_closed=true import_hook_added=false safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    """Compatibility installer name; v122 deliberately adds no import hook."""
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_v121_ready",
    "_ensure_v121",
    "_patch_v108",
]
