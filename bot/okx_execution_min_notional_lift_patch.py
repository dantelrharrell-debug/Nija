from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.okx_execution_min_notional_lift")
_PATCHED = False
_MONITOR_STARTED = False
_WRAP_ATTR = "_nija_okx_execution_min_notional_lift_wrapped_v20260705a"
_QUOTES = ("-USDT", "-USDC")


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default) or default)
    except Exception:
        return default


def _symbol_needs_okx_floor(symbol: Any) -> bool:
    text = str(symbol or "").upper().replace("/", "-").replace("_", "-")
    return any(text.endswith(q) for q in _QUOTES)


def _target_floor() -> float:
    base = _float_env("NIJA_OKX_EXECUTION_MIN_NOTIONAL_USD", _float_env("OKX_MIN_ORDER_USD", 10.0))
    # Add a small buffer so ECEL rounding does not compile to 9.99999999 and fail
    # the exchange minimum by a fraction of a cent.
    buffer = _float_env("NIJA_OKX_EXECUTION_MIN_NOTIONAL_BUFFER_USD", 0.05)
    return max(10.0, base) + max(0.01, buffer)


def _patch_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_submit_market_order_via_pipeline", None)
    if not callable(original):
        return False
    if getattr(original, _WRAP_ATTR, False):
        _PATCHED = True
        return True

    def _submit_market_order_with_okx_floor(self: Any, broker_client: Any, symbol: str, side: str, size_usd: float, *args: Any, **kwargs: Any):
        adjusted_size = float(size_usd or 0.0)
        floor = _target_floor()
        available = kwargs.get("available_balance_usd")
        try:
            available_f = float(available or 0.0)
        except Exception:
            available_f = 0.0
        if _symbol_needs_okx_floor(symbol) and 0.0 < adjusted_size < floor:
            if available_f <= 0.0 or floor <= available_f:
                logger.critical(
                    "OKX_EXECUTION_MIN_NOTIONAL_LIFT_APPLIED marker=20260705a symbol=%s old_size=$%.2f new_size=$%.2f available=$%.2f side=%s",
                    symbol,
                    adjusted_size,
                    floor,
                    available_f,
                    side,
                )
                print(
                    f"[NIJA-PRINT] OKX_EXECUTION_MIN_NOTIONAL_LIFT_APPLIED marker=20260705a symbol={symbol} old_size=${adjusted_size:.2f} new_size=${floor:.2f} available=${available_f:.2f}",
                    flush=True,
                )
                adjusted_size = floor
            else:
                logger.warning(
                    "OKX_EXECUTION_MIN_NOTIONAL_LIFT_SKIPPED marker=20260705a symbol=%s requested=$%.2f floor=$%.2f available=$%.2f reason=insufficient_available_balance",
                    symbol,
                    adjusted_size,
                    floor,
                    available_f,
                )
        return original(self, broker_client, symbol, side, adjusted_size, *args, **kwargs)

    setattr(_submit_market_order_with_okx_floor, _WRAP_ATTR, True)
    setattr(_submit_market_order_with_okx_floor, "__wrapped__", original)
    setattr(cls, "_submit_market_order_via_pipeline", _submit_market_order_with_okx_floor)
    _PATCHED = True
    logger.warning("OKX_EXECUTION_MIN_NOTIONAL_LIFT_PATCHED marker=20260705a module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] OKX_EXECUTION_MIN_NOTIONAL_LIFT_PATCHED marker=20260705a module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.execution_engine", "execution_engine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                patched = _patch_module(module) or patched
            except Exception as exc:
                logger.warning("OKX_EXECUTION_MIN_NOTIONAL_LIFT_PATCH_FAILED module=%s err=%s", name, exc)
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.getenv("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        patched = False
        while time.time() < deadline:
            patched = _try_patch_loaded() or patched
            if patched:
                break
            time.sleep(0.5)
        logger.warning("OKX_EXECUTION_MIN_NOTIONAL_LIFT_MONITOR_COMPLETE marker=20260705a patched=%s", patched)

    threading.Thread(target=_monitor, name="okx-execution-min-notional-lift-monitor", daemon=True).start()
    logger.warning("OKX_EXECUTION_MIN_NOTIONAL_LIFT_MONITOR_STARTED marker=20260705a")


def install_import_hook() -> None:
    _try_patch_loaded()
    _start_monitor()
    if getattr(builtins, "_NIJA_OKX_EXECUTION_MIN_NOTIONAL_LIFT_IMPORT_HOOK_INSTALLED", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if name in {"bot.execution_engine", "execution_engine"} or str(name).endswith("execution_engine"):
            _try_patch_loaded()
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_OKX_EXECUTION_MIN_NOTIONAL_LIFT_IMPORT_HOOK_INSTALLED", True)
    logger.warning("OKX_EXECUTION_MIN_NOTIONAL_LIFT_INSTALL_COMPLETE marker=20260705a patched=%s", _PATCHED)


def install() -> None:
    install_import_hook()
