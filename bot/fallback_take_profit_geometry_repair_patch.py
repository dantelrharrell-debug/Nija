"""Normalize fallback take-profit geometry to satisfy ExecutionEngine gates.

Latest live Railway logs showed the safe execute-entry logger working and the
entry path reaching the target_geometry_gate. The remaining rejection was:

    target_geometry_tp_too_small detail='tp_pct=0.850 minimum_pct=1.000'

That means the stop-loss normalization is working, but the successful native
fallback payload can still return a tp1 that is below ExecutionEngine's hard
minimum take-profit geometry. This patch wraps NijaCoreLoop's fallback payload
builder after the existing payload repair and raises fallback tp targets above
the hard minimum without loosening the execution gate.

2026-07-04 runtime repair: RegimeDetector.adjust_take_profit_levels() accepted
only dict TP ladders and called .items(). Native strategy analysis can pass a
list returned by RiskManager.calculate_take_profit_levels(), causing
"'list' object has no attribute 'items'" after a valid size/SL is produced.
This patch preserves dict behavior and adds list/tuple/scalar compatibility.
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

logger = logging.getLogger("nija.fallback_take_profit_geometry_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_REGIME_TP_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_WRAP_ATTR = "_nija_fallback_take_profit_geometry_repair_wrapped"
_REGIME_TP_WRAP_ATTR = "_nija_regime_take_profit_levels_list_safe_wrapped_v20260704a"

# ExecutionEngine requires tp_pct >= 1.000%. Use a small buffer so float/rounding
# cannot put fallback tp1 right back on the rejection boundary.
_EXECUTION_MIN_TP_PCT = 0.0100
_DEFAULT_FALLBACK_TP1_PCT = 0.0120
_DEFAULT_FALLBACK_TP2_PCT = 0.0180
_DEFAULT_FALLBACK_TP3_PCT = 0.0260


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _wrapper_chain_has_attr(fn: Any, attr: str) -> bool:
    """Return True if any wrapper in a __wrapped__ chain already has attr.

    This patch and the fallback payload repair both wrap the same method. Chain
    awareness prevents wrapper ping-pong where each monitor scan wraps the other
    patch again and floods logs with repeated PATCHED markers.
    """
    seen: set[int] = set()
    cur = fn
    while callable(cur) and id(cur) not in seen:
        seen.add(id(cur))
        if getattr(cur, attr, False):
            return True
        cur = getattr(cur, "__wrapped__", None)
    return False


def _target_tp_pcts() -> tuple[float, float, float]:
    tp1 = max(_EXECUTION_MIN_TP_PCT + 0.001, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP1_PCT", _DEFAULT_FALLBACK_TP1_PCT))
    tp2 = max(tp1 + 0.003, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP2_PCT", _DEFAULT_FALLBACK_TP2_PCT))
    tp3 = max(tp2 + 0.004, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP3_PCT", _DEFAULT_FALLBACK_TP3_PCT))
    return tp1, tp2, tp3


def _tp_pct(entry: float, target: float, action: str) -> float:
    if entry <= 0.0 or target <= 0.0:
        return 0.0
    if action == "enter_short":
        return max(0.0, (entry - target) / entry)
    return max(0.0, (target - entry) / entry)


def _price_for_pct(entry: float, pct: float, action: str) -> float:
    if action == "enter_short":
        return entry * (1.0 - pct)
    return entry * (1.0 + pct)


def _normalize_tp_geometry(payload: Any) -> tuple[Any, bool, float, float]:
    if not isinstance(payload, dict):
        return payload, False, 0.0, 0.0
    tp = payload.get("take_profit")
    if not isinstance(tp, dict):
        return payload, False, 0.0, 0.0
    try:
        entry = float(payload.get("entry_price") or 0.0)
    except Exception:
        return payload, False, 0.0, 0.0
    if entry <= 0.0:
        return payload, False, 0.0, 0.0

    action = str(payload.get("action") or "enter_long").strip().lower()
    if action not in {"enter_long", "enter_short"}:
        action = "enter_long"

    target1, target2, target3 = _target_tp_pcts()
    old_tp1 = _tp_pct(entry, float(tp.get("tp1") or 0.0), action)
    old_tp2 = _tp_pct(entry, float(tp.get("tp2") or 0.0), action)
    old_tp3 = _tp_pct(entry, float(tp.get("tp3") or 0.0), action)

    new_tp1 = max(old_tp1, target1)
    new_tp2 = max(old_tp2, target2, new_tp1 + 0.003)
    new_tp3 = max(old_tp3, target3, new_tp2 + 0.004)

    if old_tp1 >= _EXECUTION_MIN_TP_PCT and old_tp1 >= target1:
        return payload, False, old_tp1, old_tp1

    tp["tp1"] = _price_for_pct(entry, new_tp1, action)
    tp["tp2"] = _price_for_pct(entry, new_tp2, action)
    tp["tp3"] = _price_for_pct(entry, new_tp3, action)
    tp["fallback_tp1_pct"] = new_tp1
    tp["fallback_tp_min_pct"] = _EXECUTION_MIN_TP_PCT
    payload["take_profit"] = tp
    payload["fallback_take_profit_geometry_repaired"] = True
    payload["fallback_target_geometry_capped"] = True
    payload["reason"] = str(payload.get("reason") or "fallback_entry") + " [fallback_take_profit_geometry_repaired]"
    return payload, True, old_tp1, new_tp1


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_build_forced_fallback_entry_analysis", None)
    if not callable(original):
        return False
    if _wrapper_chain_has_attr(original, _WRAP_ATTR):
        _PATCHED = True
        return True

    def _patched_build_forced_fallback_entry_analysis(self: Any, *args: Any, **kwargs: Any) -> Any:
        payload = original(self, *args, **kwargs)
        payload, changed, old_pct, new_pct = _normalize_tp_geometry(payload)
        if changed:
            symbol = getattr(args[1], "symbol", "UNKNOWN") if len(args) > 1 else getattr(kwargs.get("sig"), "symbol", "UNKNOWN")
            logger.critical(
                "FORCED_FALLBACK_TP_GEOMETRY_NORMALIZED symbol=%s old_tp1_pct=%.4f new_tp1_pct=%.4f min_pct=%.4f",
                symbol,
                old_pct,
                new_pct,
                _EXECUTION_MIN_TP_PCT,
            )
            print(
                f"[NIJA-PRINT] FORCED_FALLBACK_TP_GEOMETRY_NORMALIZED | symbol={symbol} "
                f"old_tp1_pct={old_pct * 100.0:.3f}% new_tp1_pct={new_pct * 100.0:.3f}% min_pct={_EXECUTION_MIN_TP_PCT * 100.0:.3f}%",
                flush=True,
            )
        return payload

    setattr(_patched_build_forced_fallback_entry_analysis, _WRAP_ATTR, True)
    setattr(_patched_build_forced_fallback_entry_analysis, "__wrapped__", original)
    setattr(cls, "_build_forced_fallback_entry_analysis", _patched_build_forced_fallback_entry_analysis)
    _PATCHED = True
    logger.warning("FORCED_FALLBACK_TP_GEOMETRY_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] FORCED_FALLBACK_TP_GEOMETRY_REPAIR_PATCHED | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _adjust_tp_value(value: Any, multiplier: float) -> Any:
    if isinstance(value, (int, float)):
        return value * multiplier
    try:
        # Preserve numeric strings if any legacy caller emits them.
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return float(stripped) * multiplier
    except Exception:
        pass
    return value


def _install_regime_tp_on_module(module: ModuleType) -> bool:
    global _REGIME_TP_PATCHED
    cls = getattr(module, "RegimeDetector", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "adjust_take_profit_levels", None)
    if not callable(original):
        return False
    if _wrapper_chain_has_attr(original, _REGIME_TP_WRAP_ATTR):
        _REGIME_TP_PATCHED = True
        return True

    def _patched_adjust_take_profit_levels(self: Any, regime: Any, base_tp_levels: Any) -> Any:
        params = self.get_regime_parameters(regime)
        multiplier = params.get("take_profit_multiplier", 1.0) if isinstance(params, dict) else 1.0
        try:
            multiplier = float(multiplier or 1.0)
        except Exception:
            multiplier = 1.0

        if isinstance(base_tp_levels, dict):
            return {level: _adjust_tp_value(price, multiplier) for level, price in base_tp_levels.items()}
        if isinstance(base_tp_levels, list):
            adjusted = [_adjust_tp_value(price, multiplier) for price in base_tp_levels]
            logger.info(
                "REGIME_TP_LIST_NORMALIZED marker=20260704a regime=%s count=%d multiplier=%.4f",
                getattr(regime, "value", regime),
                len(adjusted),
                multiplier,
            )
            return adjusted
        if isinstance(base_tp_levels, tuple):
            adjusted_tuple = tuple(_adjust_tp_value(price, multiplier) for price in base_tp_levels)
            logger.info(
                "REGIME_TP_TUPLE_NORMALIZED marker=20260704a regime=%s count=%d multiplier=%.4f",
                getattr(regime, "value", regime),
                len(adjusted_tuple),
                multiplier,
            )
            return adjusted_tuple

        adjusted_scalar = _adjust_tp_value(base_tp_levels, multiplier)
        logger.info(
            "REGIME_TP_SCALAR_NORMALIZED marker=20260704a regime=%s input_type=%s multiplier=%.4f",
            getattr(regime, "value", regime),
            type(base_tp_levels).__name__,
            multiplier,
        )
        return adjusted_scalar

    setattr(_patched_adjust_take_profit_levels, _REGIME_TP_WRAP_ATTR, True)
    setattr(_patched_adjust_take_profit_levels, "__wrapped__", original)
    setattr(cls, "adjust_take_profit_levels", _patched_adjust_take_profit_levels)
    _REGIME_TP_PATCHED = True
    logger.warning("REGIME_TP_LEVELS_LIST_SAFE_PATCHED marker=20260704a module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] REGIME_TP_LEVELS_LIST_SAFE_PATCHED marker=20260704a | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
            patched = _install_on_module(module) or patched
        if name in {"bot.market_regime_detector", "market_regime_detector"} or hasattr(module, "RegimeDetector"):
            patched = _install_regime_tp_on_module(module) or patched
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
            time.sleep(0.25)
        logger.warning(
            "FORCED_FALLBACK_TP_GEOMETRY_REPAIR_MONITOR_COMPLETE patched=%s regime_tp_patched=%s patched_any=%s",
            _PATCHED,
            _REGIME_TP_PATCHED,
            patched_any,
        )

    threading.Thread(target=_monitor, name="fallback-take-profit-geometry-repair-monitor", daemon=True).start()
    logger.warning("FORCED_FALLBACK_TP_GEOMETRY_REPAIR_MONITOR_STARTED")


def _eager_import_regime_detector() -> None:
    importer = _ORIGINAL_IMPORT_MODULE or importlib.import_module
    for name in ("bot.market_regime_detector", "market_regime_detector"):
        try:
            module = importer(name)
            _install_regime_tp_on_module(module)
            return
        except Exception:
            continue


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        if _ORIGINAL_IMPORT_MODULE is None:
            _ORIGINAL_IMPORT_MODULE = importlib.import_module
        _eager_import_regime_detector()
        _start_monitor()
        if getattr(importlib.import_module, "_nija_fallback_tp_import_hook_v20260704a", False):
            logger.warning(
                "FORCED_FALLBACK_TP_GEOMETRY_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s regime_tp_patched=%s",
                _PATCHED,
                _REGIME_TP_PATCHED,
            )
            return

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
                _install_on_module(module)
            if name in {"bot.market_regime_detector", "market_regime_detector"} or hasattr(module, "RegimeDetector"):
                _install_regime_tp_on_module(module)
            _try_patch_loaded()
            return module

        setattr(_wrapped_import_module, "_nija_fallback_tp_import_hook_v20260704a", True)
        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning(
            "FORCED_FALLBACK_TP_GEOMETRY_REPAIR_INSTALL_COMPLETE patched=%s regime_tp_patched=%s",
            _PATCHED,
            _REGIME_TP_PATCHED,
        )
