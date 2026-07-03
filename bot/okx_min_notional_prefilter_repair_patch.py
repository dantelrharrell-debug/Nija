"""Repair OKX micro-notional pre-entry blocking.

The APEX strategy has an early affordability pre-filter that compares
`balance × risk_manager.min_position_pct` with BROKER_MIN_ORDER_USD[broker].
For OKX, a $222.27 canonical balance at 2% yields $4.45, so the pre-filter
blocks with "Need $250+ balance" even though the downstream exchange order
compiler already clamps valid OKX orders to the $5.00 exchange notional.

This patch lowers only the APEX early pre-filter floor for OKX so the signal can
reach the execution compiler. It does NOT lower the exchange compiler's final
minimum notional, and it does NOT bypass risk, kill-switch, writer authority,
or exchange validation.
"""

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
_MARKER = "OKX_MIN_NOTIONAL_PREFILTER_REPAIR_PATCHED marker=20260703h"


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _patch_module(module: ModuleType) -> bool:
    global _PATCHED
    changed = False
    try:
        broker_mins = getattr(module, "BROKER_MIN_ORDER_USD", None)
        if isinstance(broker_mins, dict):
            old = float(broker_mins.get("okx", 5.0) or 5.0)
            # This is only the APEX early affordability pre-filter. The final
            # ExchangeOrderCompiler still clamps/validates OKX orders to the real
            # exchange minimum before submit.
            new = min(old, _float_env("NIJA_OKX_APEX_PREFILTER_MIN_USD", 1.0))
            if old != new:
                broker_mins["okx"] = new
                changed = True
            # Keep Coinbase/Kraken micro floors unchanged unless they are higher
            # than their already established micro-compatible defaults.
            if "coinbase" in broker_mins:
                broker_mins["coinbase"] = min(float(broker_mins.get("coinbase", 1.0) or 1.0), 1.0)
            logger.critical("%s module=%s okx_prefilter_old=%.2f okx_prefilter_new=%.2f final_exchange_min_unchanged=True", _MARKER, getattr(module, "__name__", "<unknown>"), old, broker_mins.get("okx", new))
            print(f"[NIJA-PRINT] OKX_MIN_NOTIONAL_PREFILTER_REPAIR_PATCHED marker=20260703h okx_prefilter=${broker_mins.get('okx', new):.2f}", flush=True)
            _PATCHED = True
            return True
    except Exception as exc:
        logger.warning("OKX_MIN_NOTIONAL_PREFILTER_REPAIR_FAILED module=%s err=%s", getattr(module, "__name__", "<unknown>"), exc)
    return changed


def _try_patch_loaded() -> bool:
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
        logger.warning("OKX_MIN_NOTIONAL_PREFILTER_REPAIR_INSTALL_START marker=20260703h")
        print("[NIJA-PRINT] OKX_MIN_NOTIONAL_PREFILTER_REPAIR_INSTALL_START marker=20260703h", flush=True)
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"}:
                _patch_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("OKX_MIN_NOTIONAL_PREFILTER_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
