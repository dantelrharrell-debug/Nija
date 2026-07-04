from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.execution_entry_tp_geometry_patch")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_WRAP_ATTR = "_nija_execution_entry_tp_sl_geometry_wrapped_v20260704b"

_MIN_TP1_PCT = 0.0100
_DEFAULT_TP1_PCT = 0.0120
_DEFAULT_TP2_PCT = 0.0180
_DEFAULT_TP3_PCT = 0.0260
_DEFAULT_MAX_SL_PCT = 0.0030
_SL_BUFFER_PCT = 0.00005


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _wrapper_chain_has_attr(fn: Any, attr: str) -> bool:
    seen: set[int] = set()
    cur = fn
    while callable(cur) and id(cur) not in seen:
        seen.add(id(cur))
        if getattr(cur, attr, False):
            return True
        cur = getattr(cur, "__wrapped__", None)
    return False


def _targets() -> tuple[float, float, float]:
    tp1 = max(_MIN_TP1_PCT + 0.001, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP1_PCT", _DEFAULT_TP1_PCT))
    tp2 = max(tp1 + 0.003, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP2_PCT", _DEFAULT_TP2_PCT))
    tp3 = max(tp2 + 0.004, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP3_PCT", _DEFAULT_TP3_PCT))
    return tp1, tp2, tp3


def _max_sl_pct() -> float:
    # Match ExecutionEngine.MAX_SL_PCT from env and stay just inside the hard gate.
    # The live log showed maximum_pct=0.300%, so default to 0.003 when env is absent.
    configured = max(0.0005, _float_env("MAX_SL_PCT", _DEFAULT_MAX_SL_PCT))
    return max(0.0005, configured - _SL_BUFFER_PCT)


def _tp_pct(entry: float, target: float, side: str) -> float:
    if entry <= 0.0 or target <= 0.0:
        return 0.0
    if str(side).lower() == "short":
        return max(0.0, (entry - target) / entry)
    return max(0.0, (target - entry) / entry)


def _sl_pct(entry: float, stop_loss: float) -> float:
    if entry <= 0.0 or stop_loss <= 0.0:
        return 0.0
    return abs(entry - stop_loss) / entry


def _price(entry: float, pct: float, side: str) -> float:
    if str(side).lower() == "short":
        return entry * (1.0 - pct)
    return entry * (1.0 + pct)


def _stop_price(entry: float, pct: float, side: str) -> float:
    if str(side).lower() == "short":
        return entry * (1.0 + pct)
    return entry * (1.0 - pct)


def _normalize(symbol: str, side: str, entry_price: float, levels: Any) -> Any:
    if not isinstance(levels, dict):
        return levels
    try:
        entry = float(entry_price or 0.0)
    except Exception:
        return levels
    if entry <= 0.0:
        return levels
    old_tp1 = _tp_pct(entry, float(levels.get("tp1") or 0.0), side)
    target1, target2, target3 = _targets()
    if old_tp1 >= target1:
        return levels
    new_levels = dict(levels)
    old_tp2 = _tp_pct(entry, float(levels.get("tp2") or 0.0), side)
    old_tp3 = _tp_pct(entry, float(levels.get("tp3") or 0.0), side)
    new_tp1 = max(old_tp1, target1)
    new_tp2 = max(old_tp2, target2, new_tp1 + 0.003)
    new_tp3 = max(old_tp3, target3, new_tp2 + 0.004)
    new_levels["tp1"] = _price(entry, new_tp1, side)
    new_levels["tp2"] = _price(entry, new_tp2, side)
    new_levels["tp3"] = _price(entry, new_tp3, side)
    new_levels["execution_entry_tp_geometry_repaired"] = True
    new_levels["fallback_tp1_pct"] = new_tp1
    logger.critical(
        "EXECUTION_ENTRY_TP_GEOMETRY_NORMALIZED marker=20260704b symbol=%s side=%s old_tp1_pct=%.4f new_tp1_pct=%.4f min_pct=%.4f",
        symbol,
        side,
        old_tp1,
        new_tp1,
        _MIN_TP1_PCT,
    )
    print(
        f"[NIJA-PRINT] EXECUTION_ENTRY_TP_GEOMETRY_NORMALIZED marker=20260704b | symbol={symbol} side={side} "
        f"old_tp1_pct={old_tp1 * 100.0:.3f}% new_tp1_pct={new_tp1 * 100.0:.3f}% min_pct={_MIN_TP1_PCT * 100.0:.3f}%",
        flush=True,
    )
    return new_levels


def _normalize_stop_loss(symbol: str, side: str, entry_price: float, stop_loss: float) -> tuple[float, bool, float, float]:
    try:
        entry = float(entry_price or 0.0)
        stop = float(stop_loss or 0.0)
    except Exception:
        return stop_loss, False, 0.0, 0.0
    if entry <= 0.0 or stop <= 0.0:
        return stop_loss, False, 0.0, 0.0

    old_pct = _sl_pct(entry, stop)
    max_pct = _max_sl_pct()
    if old_pct <= max_pct:
        return stop_loss, False, old_pct, old_pct

    new_stop = _stop_price(entry, max_pct, side)
    logger.critical(
        "EXECUTION_ENTRY_SL_GEOMETRY_NORMALIZED marker=20260704b symbol=%s side=%s old_sl_pct=%.4f new_sl_pct=%.4f max_sl_pct=%.4f",
        symbol,
        side,
        old_pct,
        max_pct,
        _float_env("MAX_SL_PCT", _DEFAULT_MAX_SL_PCT),
    )
    print(
        f"[NIJA-PRINT] EXECUTION_ENTRY_SL_GEOMETRY_NORMALIZED marker=20260704b | symbol={symbol} side={side} "
        f"old_sl_pct={old_pct * 100.0:.3f}% new_sl_pct={max_pct * 100.0:.3f}% max_pct={_float_env('MAX_SL_PCT', _DEFAULT_MAX_SL_PCT) * 100.0:.3f}%",
        flush=True,
    )
    return new_stop, True, old_pct, max_pct


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute_entry", None)
    if not callable(original):
        return False
    if _wrapper_chain_has_attr(original, _WRAP_ATTR):
        _PATCHED = True
        return True

    def _patched_execute_entry(self: Any, symbol: str, side: str, position_size: float, entry_price: float, stop_loss: float, take_profit_levels: Any, *args: Any, **kwargs: Any) -> Any:
        new_levels = _normalize(symbol, side, entry_price, take_profit_levels)
        new_stop_loss, _, _, _ = _normalize_stop_loss(symbol, side, entry_price, stop_loss)
        return original(self, symbol, side, position_size, entry_price, new_stop_loss, new_levels, *args, **kwargs)

    setattr(_patched_execute_entry, _WRAP_ATTR, True)
    setattr(_patched_execute_entry, "__wrapped__", original)
    setattr(cls, "execute_entry", _patched_execute_entry)
    _PATCHED = True
    logger.warning("EXECUTION_ENTRY_TP_SL_GEOMETRY_PATCHED marker=20260704b module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] EXECUTION_ENTRY_TP_SL_GEOMETRY_PATCHED marker=20260704b | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.execution_engine", "execution_engine"} or hasattr(module, "ExecutionEngine"):
            patched = _install_on_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        patched_any = False
        while time.time() < deadline:
            patched_any = _try_patch_loaded() or patched_any
            if patched_any:
                break
            time.sleep(0.25)
        logger.warning("EXECUTION_ENTRY_TP_SL_GEOMETRY_MONITOR_COMPLETE marker=20260704b patched=%s patched_any=%s", _PATCHED, patched_any)

    threading.Thread(target=_monitor, name="execution-entry-tp-sl-geometry-monitor", daemon=True).start()
    logger.warning("EXECUTION_ENTRY_TP_SL_GEOMETRY_MONITOR_STARTED marker=20260704b")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("EXECUTION_ENTRY_TP_SL_GEOMETRY_INSTALL_COMPLETE marker=20260704b already_installed=True patched=%s", _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.execution_engine", "execution_engine"} or hasattr(module, "ExecutionEngine"):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("EXECUTION_ENTRY_TP_SL_GEOMETRY_INSTALL_COMPLETE marker=20260704b patched=%s", _PATCHED)
