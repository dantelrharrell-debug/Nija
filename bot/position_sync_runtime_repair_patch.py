"""Recurring position reconciliation for brokers that connect after startup.

The original usercustomize hook permanently marked startup sync complete after the
first capital refresh. Platform Kraken was often connected at that point while
user brokers were still binding, so Daivon/Tania never received startup position
reconciliation. This final wrapper is deliberately idempotent and rate-limited.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.position_sync_runtime_repair")
_MARKER = "20260713-position-sync-v2"
_PATCH_ATTR = "_nija_position_sync_runtime_repair_v2"
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED: set[tuple[str, int]] = set()
_LOCK = threading.RLock()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed == parsed else default


def _connected_brokers(manager: Any) -> dict[str, Any]:
    brokers: dict[str, Any] = {}
    for broker_type, broker in (getattr(manager, "platform_brokers", {}) or {}).items():
        if broker is not None and getattr(broker, "connected", False):
            key = str(getattr(broker_type, "value", broker_type)).lower()
            brokers[f"platform:{key}"] = broker
    for user_id, mapping in (getattr(manager, "user_brokers", {}) or {}).items():
        for broker_type, broker in (mapping or {}).items():
            if broker is not None and getattr(broker, "connected", False):
                key = str(getattr(broker_type, "value", broker_type)).lower()
                brokers[f"user:{user_id}:{key}"] = broker
    return brokers


def _should_reconcile(manager: Any, now: float) -> bool:
    try:
        interval = max(5.0, float(os.environ.get("NIJA_POSITION_SYNC_REFRESH_INTERVAL_S", "30") or "30"))
    except Exception:
        interval = 30.0
    last = _safe_float(getattr(manager, "_nija_position_sync_last_attempt_at", 0.0))
    return now - last >= interval


def _run_reconcile(manager: Any, trigger: str) -> None:
    now = time.time()
    if not _should_reconcile(manager, now):
        return
    setattr(manager, "_nija_position_sync_last_attempt_at", now)

    try:
        from bot.startup_position_sync import sync_exchange_positions_on_startup
    except ImportError:
        from startup_position_sync import sync_exchange_positions_on_startup  # type: ignore[import]

    connected_before = _connected_brokers(manager)
    reconciled = sync_exchange_positions_on_startup(
        SimpleNamespace(multi_account_manager=manager)
    )
    connected_after = _connected_brokers(manager)
    synced = {
        name: bool(getattr(broker, "_startup_position_sync_adopted", False))
        for name, broker in connected_after.items()
    }
    setattr(manager, "_startup_position_sync_done", bool(synced) and all(synced.values()))
    setattr(manager, "_nija_position_sync_last_connected", tuple(sorted(connected_after)))
    logger.critical(
        "POSITION_SYNC_RUNTIME_RECONCILE marker=%s trigger=%s connected_before=%s "
        "connected_after=%s synced=%s reconciled=%d all_synced=%s",
        _MARKER,
        trigger,
        sorted(connected_before),
        sorted(connected_after),
        synced,
        reconciled,
        bool(synced) and all(synced.values()),
    )


def _patch_mabm(module: ModuleType) -> bool:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "refresh_capital_authority", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    original = current

    def refresh_capital_authority(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        try:
            ready = isinstance(result, dict) and _safe_float(result.get("ready")) > 0.0
            capital = _safe_float(result.get("total_capital")) if isinstance(result, dict) else 0.0
            if ready and capital > 0.0:
                _run_reconcile(
                    self,
                    str(kwargs.get("trigger", "refresh_capital_authority")),
                )
        except Exception as exc:
            logger.exception("POSITION_SYNC_RUNTIME_RECONCILE_FAILED marker=%s error=%s", _MARKER, exc)
        return result

    setattr(refresh_capital_authority, _PATCH_ATTR, True)
    setattr(refresh_capital_authority, "__wrapped__", original)
    setattr(cls, "refresh_capital_authority", refresh_capital_authority)
    logger.warning("POSITION_SYNC_RUNTIME_REPAIR_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    with _LOCK:
        if key in _PATCHED:
            return True
        patched = _patch_mabm(module)
        if patched:
            _PATCHED.add(key)
        return patched


def _patch_loaded() -> None:
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_module(module)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    os.environ.setdefault("NIJA_POSITION_SYNC_REFRESH_INTERVAL_S", "30")
    _patch_loaded()
    if _ORIGINAL_IMPORT is not None:
        return

    _ORIGINAL_IMPORT = builtins.__import__
    local = threading.local()

    def import_hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        if getattr(local, "active", False):
            return module
        local.active = True
        try:
            _patch_loaded()
        finally:
            local.active = False
        return module

    builtins.__import__ = import_hook  # type: ignore[assignment]
    _patch_loaded()
    logger.warning("POSITION_SYNC_RUNTIME_REPAIR_INSTALLED marker=%s", _MARKER)


__all__ = [
    "install_import_hook",
    "_patch_mabm",
    "_run_reconcile",
]
