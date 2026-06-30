"""Canonical decision-pipeline telemetry for NIJA.

Purpose
-------
After startup is healthy and a symbol receives a high score, every next step
must be visible:

score -> signal candidate -> execute_action -> execute_entry -> compiler/pipeline
-> broker submit -> ACK/fill/reject -> SL/TP management

This patch adds logging only. It does not loosen risk controls, change strategy,
or bypass broker/exchange validation.
"""

from __future__ import annotations

import builtins
import logging
import time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.decision_pipeline")
_PATCHED_ATTR = "__nija_decision_pipeline_patch__"


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _patch_apex(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    patched = False

    original_execute_action = getattr(cls, "execute_action", None)
    if callable(original_execute_action):
        @wraps(original_execute_action)
        def execute_action(self: Any, analysis: Any, symbol: str, *args: Any, **kwargs: Any):
            action = _safe_get(analysis, "action")
            score = _safe_get(analysis, "score", _safe_get(analysis, "confidence"))
            size = _safe_get(analysis, "position_size", _safe_get(analysis, "size_usd"))
            price = _safe_get(analysis, "price", _safe_get(analysis, "entry_price"))
            stop = _safe_get(analysis, "stop_loss")
            trace_id = f"{symbol}:{action}:{int(time.time() * 1000)}"
            logger.warning(
                "DECISION_PIPELINE_STAGE trace=%s stage=execute_action_start symbol=%s action=%s score=%s size=%s price=%s stop_loss=%s",
                trace_id,
                symbol,
                action,
                score,
                size,
                price,
                stop,
            )
            try:
                result = original_execute_action(self, analysis, symbol, *args, **kwargs)
                logger.warning(
                    "DECISION_PIPELINE_STAGE trace=%s stage=execute_action_end symbol=%s action=%s success=%s result_type=%s",
                    trace_id,
                    symbol,
                    action,
                    bool(result),
                    type(result).__name__,
                )
                if not result:
                    logger.error(
                        "DECISION_PIPELINE_BLOCK trace=%s symbol=%s stage=execute_action reason=returned_false_or_none action=%s score=%s",
                        trace_id,
                        symbol,
                        action,
                        score,
                    )
                return result
            except Exception as exc:
                logger.exception(
                    "DECISION_PIPELINE_EXCEPTION trace=%s symbol=%s stage=execute_action error=%s",
                    trace_id,
                    symbol,
                    exc,
                )
                raise

        setattr(cls, "execute_action", execute_action)
        patched = True

    original_execute_entry = getattr(cls, "execute_entry", None)
    if callable(original_execute_entry):
        @wraps(original_execute_entry)
        def execute_entry(self: Any, *args: Any, **kwargs: Any):
            symbol = kwargs.get("symbol") if kwargs else None
            if symbol is None and args:
                symbol = args[0]
            side = kwargs.get("side") or kwargs.get("direction")
            size = kwargs.get("size_usd") or kwargs.get("position_size")
            price = kwargs.get("entry_price") or kwargs.get("price")
            trace_id = f"{symbol or 'unknown'}:{side or 'entry'}:{int(time.time() * 1000)}"
            logger.warning(
                "DECISION_PIPELINE_STAGE trace=%s stage=execute_entry_start symbol=%s side=%s size=%s price=%s kwargs=%s",
                trace_id,
                symbol,
                side,
                size,
                price,
                sorted(list(kwargs.keys())) if isinstance(kwargs, dict) else [],
            )
            try:
                result = original_execute_entry(self, *args, **kwargs)
                logger.warning(
                    "DECISION_PIPELINE_STAGE trace=%s stage=execute_entry_end symbol=%s side=%s success=%s result_type=%s",
                    trace_id,
                    symbol,
                    side,
                    bool(result),
                    type(result).__name__,
                )
                if not result:
                    logger.error(
                        "DECISION_PIPELINE_BLOCK trace=%s symbol=%s stage=execute_entry reason=returned_false_or_none side=%s size=%s price=%s",
                        trace_id,
                        symbol,
                        side,
                        size,
                        price,
                    )
                return result
            except Exception as exc:
                logger.exception(
                    "DECISION_PIPELINE_EXCEPTION trace=%s symbol=%s stage=execute_entry error=%s",
                    trace_id,
                    symbol,
                    exc,
                )
                raise

        setattr(cls, "execute_entry", execute_entry)
        patched = True

    if patched:
        setattr(cls, _PATCHED_ATTR, True)
        logger.warning("DECISION_PIPELINE_APEX_PATCHED class=%s", cls.__name__)
    return patched


def _patch_pipeline(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    patched = False
    for method_name in ("execute", "submit", "run", "process", "compile_and_submit"):
        original = getattr(cls, method_name, None)
        if not callable(original):
            continue

        @wraps(original)
        def wrapper(self: Any, *args: Any, __original=original, __method_name=method_name, **kwargs: Any):
            request = args[0] if args else kwargs.get("request")
            symbol = _safe_get(request, "symbol", kwargs.get("symbol"))
            side = _safe_get(request, "side", kwargs.get("side"))
            size = _safe_get(request, "size_usd", kwargs.get("size_usd"))
            trace_id = f"{symbol or 'unknown'}:{side or 'unknown'}:{int(time.time() * 1000)}"
            logger.warning(
                "DECISION_PIPELINE_STAGE trace=%s stage=execution_pipeline_start method=%s symbol=%s side=%s size=%s",
                trace_id,
                __method_name,
                symbol,
                side,
                size,
            )
            try:
                result = __original(self, *args, **kwargs)
                success = _safe_get(result, "success", bool(result))
                error = _safe_get(result, "error", None)
                broker = _safe_get(result, "broker", None)
                logger.warning(
                    "DECISION_PIPELINE_STAGE trace=%s stage=execution_pipeline_end method=%s symbol=%s side=%s success=%s broker=%s error=%s",
                    trace_id,
                    __method_name,
                    symbol,
                    side,
                    success,
                    broker,
                    error,
                )
                if not success:
                    logger.error(
                        "DECISION_PIPELINE_BLOCK trace=%s symbol=%s stage=execution_pipeline reason=%s side=%s size=%s",
                        trace_id,
                        symbol,
                        error or "pipeline_returned_unsuccessful",
                        side,
                        size,
                    )
                return result
            except Exception as exc:
                logger.exception(
                    "DECISION_PIPELINE_EXCEPTION trace=%s symbol=%s stage=execution_pipeline method=%s error=%s",
                    trace_id,
                    symbol,
                    __method_name,
                    exc,
                )
                raise

        setattr(cls, method_name, wrapper)
        patched = True

    if patched:
        setattr(cls, _PATCHED_ATTR, True)
        logger.warning("DECISION_PIPELINE_EXECUTION_PIPELINE_PATCHED class=%s", cls.__name__)
    return patched


def _patch_broker_class(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    patched = False
    method_names = (
        "place_order",
        "submit_order",
        "create_order",
        "market_order",
        "buy_market",
        "sell_market",
        "execute_order",
    )
    for method_name in method_names:
        original = getattr(cls, method_name, None)
        if not callable(original):
            continue

        @wraps(original)
        def wrapper(self: Any, *args: Any, __original=original, __method_name=method_name, **kwargs: Any):
            symbol = kwargs.get("symbol") or (args[0] if args else None)
            side = kwargs.get("side") or kwargs.get("action") or (args[1] if len(args) > 1 else None)
            size = kwargs.get("size_usd") or kwargs.get("amount") or kwargs.get("qty") or kwargs.get("quantity")
            broker = getattr(self, "name", None) or getattr(self, "broker_name", None) or self.__class__.__name__
            trace_id = f"{broker}:{symbol}:{side}:{int(time.time() * 1000)}"
            logger.warning(
                "DECISION_PIPELINE_STAGE trace=%s stage=broker_submit_start broker=%s method=%s symbol=%s side=%s size=%s",
                trace_id,
                broker,
                __method_name,
                symbol,
                side,
                size,
            )
            try:
                result = __original(self, *args, **kwargs)
                order_id = _safe_get(result, "order_id", _safe_get(result, "id", None))
                status = _safe_get(result, "status", None)
                error = _safe_get(result, "error", None)
                logger.warning(
                    "DECISION_PIPELINE_STAGE trace=%s stage=broker_submit_end broker=%s method=%s symbol=%s side=%s order_id=%s status=%s error=%s success=%s",
                    trace_id,
                    broker,
                    __method_name,
                    symbol,
                    side,
                    order_id,
                    status,
                    error,
                    bool(result) and not error,
                )
                if error or not result:
                    logger.error(
                        "DECISION_PIPELINE_BLOCK trace=%s symbol=%s stage=broker_submit broker=%s reason=%s",
                        trace_id,
                        symbol,
                        broker,
                        error or "broker_returned_empty_result",
                    )
                return result
            except Exception as exc:
                logger.exception(
                    "DECISION_PIPELINE_EXCEPTION trace=%s symbol=%s stage=broker_submit broker=%s method=%s error=%s",
                    trace_id,
                    symbol,
                    broker,
                    __method_name,
                    exc,
                )
                raise

        setattr(cls, method_name, wrapper)
        patched = True

    if patched:
        setattr(cls, _PATCHED_ATTR, True)
        logger.warning("DECISION_PIPELINE_BROKER_PATCHED class=%s", cls.__name__)
    return patched


def _patch_module(module: Any) -> bool:
    if module is None:
        return False
    patched = False
    for name in dir(module):
        obj = getattr(module, name, None)
        if not isinstance(obj, type):
            continue
        lname = name.lower()
        if "apex" in lname or "strategy" in lname:
            patched = _patch_apex(obj) or patched
        if "pipeline" in lname:
            patched = _patch_pipeline(obj) or patched
        if "broker" in lname or "kraken" in lname or "coinbase" in lname or "okx" in lname:
            patched = _patch_broker_class(obj) or patched
    return patched


def install_import_hook() -> None:
    import sys

    for name, module in list(sys.modules.items()):
        if name.startswith("bot.") and name.endswith(("nija_apex_strategy_v71", "trading_strategy", "execution_pipeline", "broker_manager", "execution_engine")):
            _patch_module(module)

    if getattr(builtins, "_NIJA_DECISION_PIPELINE_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name.endswith(("nija_apex_strategy_v71", "trading_strategy", "execution_pipeline", "broker_manager", "execution_engine")):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("Decision pipeline patch failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_DECISION_PIPELINE_HOOK_INSTALLED", True)
    logger.warning("DECISION_PIPELINE_INSTALL_COMPLETE")
