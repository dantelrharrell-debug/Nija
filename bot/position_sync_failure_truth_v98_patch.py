"""Fail closed when a fresh position-sync attempt cannot fetch a broker snapshot.

Production deployment 20d4351a showed a broker that had previously synchronized
successfully timing out on a later authoritative refresh. startup_position_sync
caught the timeout and returned without clearing ``_startup_position_sync_adopted``,
so aggregate sync/readiness incorrectly remained true.

v98 moves the invariant to the canonical startup-sync boundary: every fresh
broker reconciliation revokes prior sync success before calling ``get_positions``.
Only a successful authoritative snapshot may set the broker back to synchronized.
No broker connectivity, risk, nonce, writer, capital, or order-dispatch gate is
weakened or synthesized.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.position_sync_failure_truth_v98")
MARKER = "20260815-position-sync-failure-truth-v98"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_POSITION_SYNC_FAILURE_TRUTH_V98_IMPORT_HOOK"
_ADOPT_ATTR = "_nija_position_sync_failure_truth_v98"
_BASENAME = "startup_position_sync.py"


def _basename(module: Any) -> str:
    if not isinstance(module, ModuleType):
        return ""
    try:
        return Path(str(getattr(module, "__file__", "") or "")).name
    except Exception:
        return ""


def _revoke_previous_success(broker: Any) -> None:
    try:
        setattr(broker, "_startup_position_sync_adopted", False)
        setattr(broker, "_startup_position_sync_symbols", tuple())
        setattr(broker, "_startup_position_sync_fetch_ok", None)
        setattr(broker, "_startup_position_sync_error", None)
    except Exception:
        pass
    os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = "0"
    os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] = "0"


def _patch_startup_sync(module: ModuleType) -> bool:
    current = getattr(module, "_adopt_broker_positions", None)
    if not callable(current):
        return False
    if getattr(current, _ADOPT_ATTR, False):
        return True

    @wraps(current)
    def adopt_broker_positions_v98(broker: Any, broker_name: str, eps: Any) -> int:
        previous = bool(getattr(broker, "_startup_position_sync_adopted", False))
        _revoke_previous_success(broker)
        try:
            result = int(current(broker, broker_name, eps) or 0)
        except BaseException as exc:
            _revoke_previous_success(broker)
            try:
                setattr(broker, "_startup_position_sync_fetch_ok", False)
                setattr(broker, "_startup_position_sync_error", f"{type(exc).__name__}:{exc}")
            except Exception:
                pass
            LOGGER.warning(
                "POSITION_SYNC_V98_EXCEPTION marker=%s broker=%s previous_synced=%s error=%s:%s fail_closed=true",
                MARKER,
                broker_name,
                str(previous).lower(),
                type(exc).__name__,
                exc,
            )
            raise

        synced = bool(getattr(broker, "_startup_position_sync_adopted", False))
        if not synced:
            os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = "0"
            os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] = "0"
            LOGGER.warning(
                "POSITION_SYNC_V98_UNSYNCED marker=%s broker=%s previous_synced=%s stale_success_reused=false activation_blocked=true",
                MARKER,
                broker_name,
                str(previous).lower(),
            )
        return result

    setattr(adopt_broker_positions_v98, _ADOPT_ATTR, True)
    setattr(adopt_broker_positions_v98, "__wrapped__", current)
    module._adopt_broker_positions = adopt_broker_positions_v98
    LOGGER.critical(
        "POSITION_SYNC_FAILURE_TRUTH_V98_PATCHED marker=%s module=%s file=%s prefetch_revocation=true fail_closed=true",
        MARKER,
        getattr(module, "__name__", "<unknown>"),
        getattr(module, "__file__", None),
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name, module in tuple(sys.modules.items()):
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        if name not in ("bot.startup_position_sync", "startup_position_sync") and _basename(module) != _BASENAME:
            continue
        seen.add(id(module))
        changed = _patch_startup_sync(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if "startup_position_sync" in str(name or ""):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_POSITION_SYNC_FAILURE_TRUTH_V98_INSTALLED"] = "1"
        LOGGER.critical(
            "POSITION_SYNC_FAILURE_TRUTH_V98_INSTALLED marker=%s prefetch_revocation=true stale_success_reuse=false safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_patch_startup_sync"]
