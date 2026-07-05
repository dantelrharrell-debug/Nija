"""Repair OKX micro-notional pre-entry blocking."""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.okx_min_notional_prefilter_repair")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_LOCK = threading.Lock()
_MARKER = "OKX_MIN_NOTIONAL_PREFILTER_REPAIR_PATCHED marker=20260704h"
_NOTIONAL_INSTALLED = False
_SIDECAR_INSTALLED = False


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _install_notional_floor_repair() -> None:
    global _NOTIONAL_INSTALLED
    if _NOTIONAL_INSTALLED:
        return
    try:
        try:
            mod = importlib.import_module("bot.notional_floor_repair_patch")
        except Exception:
            mod = importlib.import_module("notional_floor_repair_patch")
        installer = getattr(mod, "install_import_hook", None)
        if callable(installer):
            installer()
        _NOTIONAL_INSTALLED = True
        logger.warning("NOTIONAL_FLOOR_REPAIR_CHAINED_FROM_OKX_PREFILTER marker=20260704h")
    except Exception as exc:
        logger.warning("NOTIONAL_FLOOR_REPAIR_CHAIN_FAILED err=%s", exc)


def _install_sidecar() -> None:
    global _SIDECAR_INSTALLED
    if _SIDECAR_INSTALLED:
        return
    try:
        try:
            mod = importlib.import_module("bot.venue_route_guard_patch")
        except Exception:
            mod = importlib.import_module("venue_route_guard_patch")
        installer = getattr(mod, "install_import_hook", None)
        if callable(installer):
            installer()
        _SIDECAR_INSTALLED = True
        logger.warning("VENUE_ROUTE_GUARD_CHAINED_FROM_OKX_PREFILTER marker=20260704h")
    except Exception as exc:
        logger.warning("VENUE_ROUTE_GUARD_CHAIN_FAILED err=%s", exc)


def _patch_module(module: ModuleType) -> bool:
    global _PATCHED
    _install_notional_floor_repair()
    _install_sidecar()
    changed = False
    try:
        broker_mins = getattr(module, "BROKER_MIN_ORDER_USD", None)
        if isinstance(broker_mins, dict):
            old = float(broker_mins.get("okx", 5.0) or 5.0)
            new = min(old, _float_env("NIJA_OKX_APEX_PREFILTER_MIN_USD", 1.0))
            if old != new:
                broker_mins["okx"] = new
                changed = True
            if "coinbase" in broker_mins:
                broker_mins["coinbase"] = min(float(broker_mins.get("coinbase", 1.0) or 1.0), 1.0)
            logger.critical("%s module=%s okx_prefilter_old=%.2f okx_prefilter_new=%.2f final_exchange_min_unchanged=True", _MARKER, getattr(module, "__name__", "<unknown>"), old, broker_mins.get("okx", new))
            print(f"[NIJA-PRINT] OKX_MIN_NOTIONAL_PREFILTER_REPAIR_PATCHED marker=20260704h okx_prefilter=${broker_mins.get('okx', new):.2f}", flush=True)
            _PATCHED = True
            return True
    except Exception as exc:
        logger.warning("OKX_MIN_NOTIONAL_PREFILTER_REPAIR_FAILED module=%s err=%s", getattr(module, "__name__", "<unknown>"), exc)
    return changed


def _try_patch_loaded() -> bool:
    _install_notional_floor_repair()
    _install_sidecar()
    patched = False
    for name in ("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + _float_env("NIJA_PATCH_MONITOR_SECONDS", 240.0)
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("OKX_MIN_NOTIONAL_PREFILTER_REPAIR_MONITOR_EXPIRED patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="okx-min-notional-prefilter-repair", daemon=True).start()
    logger.warning("OKX_MIN_NOTIONAL_PREFILTER_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _LOCK:
        logger.warning("OKX_MIN_NOTIONAL_PREFILTER_REPAIR_INSTALL_START marker=20260704h")
        print("[NIJA-PRINT] OKX_MIN_NOTIONAL_PREFILTER_REPAIR_INSTALL_START marker=20260704h", flush=True)
        _install_notional_floor_repair()
        _install_sidecar()
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"}:
                _patch_module(module)
            if name in {"bot.live_execution_runtime_hardening_patch", "live_execution_runtime_hardening_patch"}:
                _install_notional_floor_repair()
            if name in {"bot.usdt_kraken_ecel_routing_repair_patch", "usdt_kraken_ecel_routing_repair_patch"}:
                _install_sidecar()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("OKX_MIN_NOTIONAL_PREFILTER_REPAIR_INSTALL_COMPLETE patched=%s sidecar=%s", _PATCHED, _SIDECAR_INSTALLED)
