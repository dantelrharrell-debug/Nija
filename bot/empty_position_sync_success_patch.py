"""Mark a connected broker with a successful empty snapshot as synchronized.

Zero open positions is a valid broker state, not a synchronization failure. The
legacy startup reconciler left ``_startup_position_sync_adopted=False`` whenever
``get_positions()`` returned an empty list, causing perpetual ``all_synced=False``.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.empty_position_sync_success")
_MARKER = "20260715-empty-position-sync-v1"
_ATTR = "_nija_empty_position_sync_success_v1"
_LOCK = threading.RLock()


def _patch(module: ModuleType) -> bool:
    current = getattr(module, "_adopt_broker_positions", None)
    if not callable(current):
        return False
    if getattr(current, _ATTR, False):
        return True

    @wraps(current)
    def adopt(broker: Any, broker_name: str, eps: Any) -> int:
        result = int(current(broker, broker_name, eps) or 0)
        if bool(getattr(broker, "_startup_position_sync_adopted", False)):
            return result
        if not bool(getattr(broker, "connected", False)):
            return result
        getter = getattr(broker, "get_positions", None)
        if not callable(getter):
            return result
        try:
            snapshot = getter()
        except Exception:
            return result
        if isinstance(snapshot, list) and not snapshot:
            setattr(broker, "_startup_position_sync_adopted", True)
            setattr(broker, "_startup_position_sync_symbols", tuple())
            logger.info(
                "EMPTY_POSITION_SNAPSHOT_SYNCED marker=%s broker=%s connected=true positions=0",
                _MARKER,
                broker_name,
            )
        return result

    setattr(adopt, _ATTR, True)
    adopt.__wrapped__ = current
    module._adopt_broker_positions = adopt
    os.environ["NIJA_EMPTY_POSITION_SYNC_READY"] = "1"
    logger.critical("EMPTY_POSITION_SYNC_SUCCESS_PATCHED marker=%s", _MARKER)
    return True


def install_import_hook() -> None:
    import importlib
    with _LOCK:
        module = importlib.import_module("bot.startup_position_sync")
        if not _patch(module):
            raise RuntimeError("startup_position_sync_not_patchable")
        os.environ["NIJA_EMPTY_POSITION_SYNC_PATCH_INSTALLED"] = "1"


def install() -> None:
    install_import_hook()


__all__ = ["install", "install_import_hook", "_patch"]
