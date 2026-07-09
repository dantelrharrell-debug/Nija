from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.tpe_min_notional_reason_sanitizer")
_MARKER = "20260709a"
_PATCH_ATTR = "_nija_tpe_min_notional_reason_sanitizer_v20260709a"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _min_notional_for_broker(broker: str) -> float:
    broker_l = str(broker or "").lower()
    if broker_l == "okx":
        return max(_f(os.environ.get("OKX_MIN_ORDER_USD"), 10.0), 10.0)
    if broker_l == "coinbase":
        return max(_f(os.environ.get("COINBASE_MIN_ORDER_USD"), 1.0), 1.0)
    if broker_l == "kraken":
        return max(_f(os.environ.get("KRAKEN_MIN_NOTIONAL_USD"), 10.0), 10.0)
    return max(_f(os.environ.get("MIN_NOTIONAL_OVERRIDE"), 10.0), 1.0)


def _reason_has_min_notional(reason: Any) -> bool:
    text = str(reason or "").upper()
    return "BROKER_MIN_NOTIONAL_BLOCK" in text or "MIN_NOTIONAL" in text


def _sanitize_analysis(analysis: Any, symbol: str = "") -> Any:
    if not isinstance(analysis, dict):
        return analysis
    broker = str(analysis.get("broker_selected") or analysis.get("broker") or analysis.get("execution_broker") or "okx").lower()
    capital = _f(analysis.get("capital_allocated") or analysis.get("tpe_capital_allocated") or analysis.get("order_notional"), 0.0)
    min_notional = _f(analysis.get("min_notional"), 0.0) or _min_notional_for_broker(broker)
    reason = analysis.get("reason") or analysis.get("reason_blocked") or ""
    filter_stage = str(analysis.get("filter_stage") or "")
    if capital >= min_notional and (_reason_has_min_notional(reason) or _reason_has_min_notional(filter_stage)):
        repaired = dict(analysis)
        repaired["action"] = repaired.get("action") if repaired.get("action") in {"enter_long", "enter_short"} else "enter_long"
        repaired["reason"] = ""
        repaired["reason_blocked"] = ""
        repaired["filter_stage"] = "tpe_capital_min_notional_repaired"
        repaired["order_notional"] = max(_f(repaired.get("order_notional"), 0.0), capital)
        repaired["position_size"] = max(_f(repaired.get("position_size"), 0.0), capital)
        repaired["final_order_notional"] = max(_f(repaired.get("final_order_notional"), 0.0), capital)
        repaired["min_notional_reason_repaired"] = True
        logger.critical(
            "TPE_MIN_NOTIONAL_REASON_SANITIZED marker=%s symbol=%s broker=%s capital_allocated=%.8f min_notional=%.8f previous_reason=%s",
            _MARKER,
            symbol or repaired.get("symbol") or "",
            broker,
            capital,
            min_notional,
            reason,
        )
        print(f"[NIJA-PRINT] TPE_MIN_NOTIONAL_REASON_SANITIZED marker={_MARKER} symbol={symbol or repaired.get('symbol') or ''} capital_allocated={capital:.8f}", flush=True)
        return repaired
    return analysis


def _patch_apex_module(module: ModuleType) -> bool:
    patched = False
    for cls in list(vars(module).values()):
        if not isinstance(cls, type):
            continue
        original_execute = getattr(cls, "execute_action", None)
        if callable(original_execute) and not getattr(original_execute, _PATCH_ATTR, False):
            base = getattr(original_execute, "__wrapped__", original_execute)

            @wraps(base)
            def execute_action(self: Any, analysis: Any, symbol: str, *args: Any, __orig=base, **kwargs: Any) -> Any:
                return __orig(self, _sanitize_analysis(analysis, symbol), symbol, *args, **kwargs)

            setattr(execute_action, _PATCH_ATTR, True)
            setattr(execute_action, "__wrapped__", base)
            setattr(cls, "execute_action", execute_action)
            patched = True
            logger.warning("TPE_MIN_NOTIONAL_REASON_SANITIZER_EXECUTE_PATCHED marker=%s class=%s", _MARKER, getattr(cls, "__name__", cls))
        original_analyze = getattr(cls, "analyze_market", None)
        if callable(original_analyze) and not getattr(original_analyze, _PATCH_ATTR, False):
            base_analyze = getattr(original_analyze, "__wrapped__", original_analyze)

            @wraps(base_analyze)
            def analyze_market(self: Any, df: Any, symbol: str, account_balance: float, *args: Any, __orig=base_analyze, **kwargs: Any) -> Any:
                result = __orig(self, df, symbol, account_balance, *args, **kwargs)
                return _sanitize_analysis(result, symbol)

            setattr(analyze_market, _PATCH_ATTR, True)
            setattr(analyze_market, "__wrapped__", base_analyze)
            setattr(cls, "analyze_market", analyze_market)
            patched = True
            logger.warning("TPE_MIN_NOTIONAL_REASON_SANITIZER_ANALYZE_PATCHED marker=%s class=%s", _MARKER, getattr(cls, "__name__", cls))
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    try:
        modules = list(sys.modules.items())
    except RuntimeError:
        modules = list(dict(sys.modules).items())
    for name, module in modules:
        if not isinstance(module, ModuleType):
            continue
        if name.endswith("nija_apex_strategy_v71") or name.endswith("apex_strategy") or name.endswith("trading_strategy"):
            try:
                patched = _patch_apex_module(module) or patched
            except Exception as exc:
                logger.warning("TPE_MIN_NOTIONAL_REASON_SANITIZER_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def install_import_hook() -> None:
    if not _truthy("NIJA_TPE_MIN_NOTIONAL_REASON_SANITIZER_ENABLED", True):
        logger.warning("TPE_MIN_NOTIONAL_REASON_SANITIZER_DISABLED marker=%s", _MARKER)
        return
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_TPE_MIN_NOTIONAL_REASON_SANITIZER_INSTALLED_V20260709A", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith(("nija_apex_strategy_v71", "apex_strategy", "trading_strategy")):
            _try_patch_loaded()
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_TPE_MIN_NOTIONAL_REASON_SANITIZER_INSTALLED_V20260709A", True)
    logger.warning("TPE_MIN_NOTIONAL_REASON_SANITIZER_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
