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

_MIN_TP1_PCT = 0.0100
_DEFAULT_TP1_PCT = 0.0120
_DEFAULT_TP2_PCT = 0.0180
_DEFAULT_TP3_PCT = 0.0260


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _targets() -> tuple[float, float, float]:
    tp1 = max(_MIN_TP1_PCT + 0.001, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP1_PCT", _DEFAULT_TP1_PCT))
    tp2 = max(tp1 + 0.003, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP2_PCT", _DEFAULT_TP2_PCT))
    tp3 = max(tp2 + 0.004, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP3_PCT", _DEFAULT_TP3_PCT))
    return tp1, tp2, tp3


def _tp_pct(entry: float, target: float, side: str) -> float:
    if entry <= 0.0 or target <= 0.0:
        return 0.0
    if str(side).lower() == "short":
        return max(0.0, (entry - target) / entry)
    return max(0.0, (target - entry) / entry)


def _price(entry: float, pct: float, side: str) -> float:
    if str(side).lower() == "short":
        return entry * (1.0 - pct)
    return entry * (1.0 + pct)


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
        "EXECUTION_ENTRY_TP_GEOMETRY_NORMALIZED symbol=%s side=%s old_tp1_pct=%.4f new_tp1_pct=%.4f min_pct=%.4f",
        symbol,
        side,
        old_tp1,
        new_tp1,
        _MIN_TP1_PCT,
    )
    print(
        f"[NIJA-PRINT] EXECUTION_ENTRY_TP_GEOMETRY_NORMALIZED | symbol={symbol} side={side} "
        f"old_tp1_pct={old_tp1 * 100.0:.3f}% new_tp1_pct={new_tp1 * 100.0:.3f}% min_pct={_MIN_TP1_PCT * 100.0:.3f}%",
        flush=True,
    )
    return new_levels


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute_entry", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_execution_entry_tp_geometry_wrapped", False):
        _PATCHED = True
        return True

    def _patched_execute_entry(self: Any, symbol: str, side: str, position_size: float, entry_price: float, stop_loss: float, take_profit_levels: Any, *args: Any, **kwargs: Any) -> Any:
        new_levels = _normalize(symbol, side, entry_price, take_profit_levels)
        return original(self, symbol, side, position_size, entry_price, stop_loss, new_levels, *args, **kwargs)

    setattr(_patched_execute_entry, "_nija_execution_entry_tp_geometry_wrapped", True)
    setattr(_patched_execute_entry, "__wrapped__", original)
    setattr(cls, "execute_entry", _patched_execute_entry)
    _PATCHED = True
    logger.warning("EXECUTION_ENTRY_TP_GEOMETRY_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] EXECUTION_ENTRY_TP_GEOMETRY_PATCHED | module={getattr(module, '__name__', '<unknown>')}", flush=True)
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
        logger.warning("EXECUTION_ENTRY_TP_GEOMETRY_MONITOR_COMPLETE patched=%s patched_any=%s", _PATCHED, patched_any)

    threading.Thread(target=_monitor, name="execution-entry-tp-geometry-monitor", daemon=True).start()
    logger.warning("EXECUTION_ENTRY_TP_GEOMETRY_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("EXECUTION_ENTRY_TP_GEOMETRY_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.execution_engine", "execution_engine"} or hasattr(module, "ExecutionEngine"):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("EXECUTION_ENTRY_TP_GEOMETRY_INSTALL_COMPLETE patched=%s", _PATCHED)
