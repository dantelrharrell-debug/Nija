"""Fail closed live Phase-3 entries whenever canonical market-data health is false.

This patch is deliberately entry-only: protective exits, reconciliation, and broker
position management are untouched. It does not grant readiness, submit orders,
clear latches, or modify market-data thresholds.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_market_data_entry_failclosed_v403")
MARKER = "20260908-runtime-market-data-entry-failclosed-v403"
_ATTR = "_nija_market_data_entry_failclosed_v403"
_LOCK = threading.RLock()
_HOOK = False
_MONITOR = False


def _health() -> tuple[bool, dict[str, Any]]:
    try:
        pool_mod = importlib.import_module("bot.ohlc_worker_pool")
        pool = pool_mod.get_pool()
        healthy, detail = pool.compute_market_data_healthy(
            runtime_state="LIVE_ACTIVE", execution_authority=1
        )
        return bool(healthy), dict(detail or {})
    except Exception as exc:
        return False, {"health_probe_error": f"{type(exc).__name__}:{exc}"}


def _patch_module(module: Any) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(current):
        return False
    if getattr(current, _ATTR, False):
        return True
    original = current

    @wraps(original)
    def phase3_market_health_gate(self: Any, *args: Any, **kwargs: Any):
        healthy, detail = _health()
        if not healthy:
            symbols = []
            if len(args) >= 3 and isinstance(args[2], (list, tuple, set)):
                symbols = list(args[2])
            elif isinstance(kwargs.get("symbols"), (list, tuple, set)):
                symbols = list(kwargs.get("symbols") or [])
            blocked = max(1, len(symbols))
            try:
                record = getattr(self, "_record_reject", None)
                if callable(record):
                    record("market_data_unhealthy")
            except Exception:
                pass
            LOGGER.critical(
                "ENTRY_BLOCKED reason=market_data_unhealthy marker=%s blocked=%d detail=%s "
                "entry_fail_closed=true exits_unchanged=true orders_submitted=false "
                "forced_activation=false safety_gates_bypassed=false",
                MARKER, blocked, detail,
            )
            return (0, blocked, 0, {"market_data_unhealthy": blocked})
        return original(self, *args, **kwargs)

    setattr(phase3_market_health_gate, _ATTR, True)
    setattr(phase3_market_health_gate, "__wrapped__", original)
    setattr(cls, "_phase3_scan_and_enter", phase3_market_health_gate)
    LOGGER.critical(
        "RUNTIME_MARKET_DATA_ENTRY_FAILCLOSED_V403_PATCHED marker=%s module=%s "
        "phase3_entries_only=true protective_exits_unchanged=true thresholds_unchanged=true "
        "orders_submitted=false forced_activation=false safety_gates_bypassed=false",
        MARKER, getattr(module, "__name__", "unknown"),
    )
    return True


def _patch_loaded() -> int:
    count = 0
    for name, module in list(sys.modules.items()):
        if name in {"bot.nija_core_loop", "nija_core_loop"} and isinstance(module, ModuleType):
            try:
                count += int(_patch_module(module))
            except Exception:
                pass
    return count


def _install_import_hook() -> None:
    global _HOOK
    if _HOOK or getattr(builtins, "_NIJA_MARKET_DATA_ENTRY_FAILCLOSED_V403_HOOK", False):
        _HOOK = True
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name in {"bot.nija_core_loop", "nija_core_loop"} or "nija_core_loop" in name:
                target = sys.modules.get("bot.nija_core_loop") or sys.modules.get("nija_core_loop") or module
                _patch_module(target)
        except Exception as exc:
            LOGGER.warning("V403_IMPORT_PATCH_RETRY error=%s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_MARKET_DATA_ENTRY_FAILCLOSED_V403_HOOK", True)
    _HOOK = True


def _install_monitor() -> None:
    global _MONITOR
    if _MONITOR:
        return
    _MONITOR = True

    def worker() -> None:
        deadline = time.monotonic() + 240.0
        while time.monotonic() < deadline:
            if _patch_loaded() > 0:
                return
            time.sleep(0.25)
        LOGGER.critical("V403_PATCH_MONITOR_EXPIRED trading_fail_closed=true")

    threading.Thread(target=worker, name="market-data-entry-failclosed-v403", daemon=True).start()


def install() -> bool:
    with _LOCK:
        _patch_loaded()
        _install_import_hook()
        _install_monitor()
        LOGGER.critical(
            "RUNTIME_MARKET_DATA_ENTRY_FAILCLOSED_V403_READY marker=%s ready=true "
            "phase3_entries_only=true protective_exits_unchanged=true thresholds_unchanged=true "
            "orders_submitted=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


install_import_hook = install
__all__ = ["MARKER", "install", "install_import_hook"]
