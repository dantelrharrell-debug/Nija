"""Preserve successful empty-position snapshots without refetching brokers.

The canonical startup reconciler already marks a connected broker synchronized
when its authoritative ``get_positions()`` call succeeds with an empty list.
This compatibility patch therefore must not issue a second broker fetch: an
outer runtime wrapper may intentionally convert a failed inner fetch to ``[]``
for balance/equity classification, and treating that fallback as authoritative
would incorrectly turn a timeout into synchronization success.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.empty_position_sync_success")
_MARKER = "20260815-empty-position-sync-v2"
_ATTR = "_nija_empty_position_sync_success_v2"
_LOCK = threading.RLock()


def _patch(module: ModuleType) -> bool:
    current = getattr(module, "_adopt_broker_positions", None)
    if not callable(current):
        return False
    if getattr(current, _ATTR, False):
        return True

    @wraps(current)
    def adopt(broker: Any, broker_name: str, eps: Any) -> int:
        # Delegate exactly once to the canonical reconciler. It owns the
        # authoritative fetch and already treats a genuine empty snapshot as
        # synchronized. Never refetch here and never manufacture success from
        # a compatibility-layer empty fallback.
        result = int(current(broker, broker_name, eps) or 0)
        fetch_ok = getattr(broker, "_startup_position_sync_fetch_ok", None)
        if fetch_ok is False:
            setattr(broker, "_startup_position_sync_adopted", False)
            logger.warning(
                "EMPTY_POSITION_SYNC_FAILURE_PRESERVED marker=%s broker=%s error=%s authoritative_empty=false",
                _MARKER,
                broker_name,
                getattr(broker, "_startup_position_sync_error", "position_fetch_failed"),
            )
        return result

    setattr(adopt, _ATTR, True)
    adopt.__wrapped__ = current
    module._adopt_broker_positions = adopt
    os.environ["NIJA_EMPTY_POSITION_SYNC_READY"] = "1"
    logger.critical(
        "EMPTY_POSITION_SYNC_SUCCESS_PATCHED marker=%s refetch=false masked_failure_preserved=true",
        _MARKER,
    )
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
