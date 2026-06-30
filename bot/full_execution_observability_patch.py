"""Full execution observability for NIJA live trading.

This module is logging-only. It does not approve trades, bypass gates, change
risk limits, change order sizing, or alter broker behavior.

It adds canonical WARNING/ERROR telemetry for:
- every candidate that reaches execution
- every gate check pass/fail when common gate classes/functions are invoked
- broker submission request/result
- skipped signal decisions
- pending-order lifecycle events
"""

from __future__ import annotations

import builtins
import logging
import time
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger("nija.full_execution_observability")
_PATCHED_ATTR = "__nija_full_execution_observability_patch__"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _safe_bool(result: Any) -> bool:
    if isinstance(result, tuple) and result:
        return bool(result[0])
    if isinstance(result, dict):
        for key in ("approved", "allowed", "passed", "success", "ok"):
            if key in result:
                return bool(result[key])
    for key in ("approved", "allowed", "passed", "success", "ok"):
        if hasattr(result, key):
            return bool(getattr(result, key))
    return bool(result)


def _reason(result: Any) -> str:
    if isinstance(result, tuple) and len(result) > 1:
        return str(result[1])
    if isinstance(result, dict):
        for key in ("reason", "error", "message", "detail", "reject_reason"):
            if result.get(key):
                return str(result.get(key))
    for key in ("reason", "error", "message", "detail", "reject_reason"):
        value = getattr(result, key, None)
        if value:
            return str(value)
    return ""


def _trace(symbol: Any = None, stage: str = "event") -> str:
    return f"{symbol or 'unknown'}:{stage}:{int(time.time() * 1000)}"


def _patch_method(cls: type, method_name: str, wrapper_factory: Callable[[Callable[..., Any]], Callable[..., Any]]) -> bool:
    original = getattr(cls, method_name, None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return False
    wrapped = wrapper_factory(original)
    setattr(wrapped, _PATCHED_ATTR, True)
    setattr(cls, method_name, wrapped)
    return True


def _patch_candidates(cls: type) -> bool:
    patched = False
    for method_name in ("execute_action", "execute_entry", "enter_position", "open_position"):
        def make_wrapper(original: Callable[..., Any], mname: str = method_name):
            @wraps(original)
            def wrapper(self: Any, *args: Any, **kwargs: Any):
                analysis = args[0] if args else kwargs.get("analysis")
                symbol = kwargs.get("symbol") or (args[1] if len(args) > 1 else _get(analysis, "symbol"))
                action = kwargs.get("action") or _get(analysis, "action") or _get(analysis, "side")
                score = _get(analysis, "score", _get(analysis, "confidence"))
                confidence = _get(analysis, "confidence", score)
                strategy = _get(analysis, "strategy", self.__class__.__name__)
                broker = kwargs.get("broker") or kwargs.get("broker_name") or _get(analysis, "broker") or _get(analysis, "preferred_broker")
                size = kwargs.get("size_usd") or kwargs.get("position_size") or _get(analysis, "position_size", _get(analysis, "size_usd"))
                tid = _trace(symbol, mname)
                logger.warning(
                    "EXEC_CANDIDATE trace=%s stage=%s_start symbol=%s action=%s score=%s confidence=%s strategy=%s broker=%s position_size=%s",
                    tid, mname, symbol, action, score, confidence, strategy, broker or "auto", size,
                )
                try:
                    result = original(self, *args, **kwargs)
                    logger.warning(
                        "EXEC_CANDIDATE_RESULT trace=%s stage=%s_end symbol=%s success=%s reason=%s result_type=%s",
                        tid, mname, symbol, _safe_bool(result), _reason(result), type(result).__name__,
                    )
                    if not _safe_bool(result):
                        logger.error(
                            "EXEC_CANDIDATE_BLOCK trace=%s symbol=%s stage=%s reason=%s score=%s confidence=%s broker=%s position_size=%s",
                            tid, symbol, mname, _reason(result) or "returned_false", score, confidence, broker or "auto", size,
                        )
                    return result
                except Exception as exc:
                    logger.exception("EXEC_CANDIDATE_EXCEPTION trace=%s symbol=%s stage=%s error=%s", tid, symbol, mname, exc)
                    raise
            return wrapper
        patched = _patch_method(cls, method_name, make_wrapper) or patched
    return patched


def _patch_gates(cls: type) -> bool:
    patched = False
    gate_methods = (
        "assess", "check", "validate", "validate_entry_size", "can_execute", "can_open_position",
        "check_risk", "check_slippage", "compile", "normalize", "enforce", "evaluate",
    )
    for method_name in gate_methods:
        def make_wrapper(original: Callable[..., Any], mname: str = method_name):
            @wraps(original)
            def wrapper(self: Any, *args: Any, **kwargs: Any):
                symbol = kwargs.get("symbol") or (args[0] if args and isinstance(args[0], str) else None)
                size = kwargs.get("size_usd") or kwargs.get("position_size") or kwargs.get("amount")
                gate = self.__class__.__name__
                tid = _trace(symbol, f"gate_{gate}_{mname}")
                logger.warning(
                    "EXEC_GATE_START trace=%s gate=%s method=%s symbol=%s size=%s kwargs=%s",
                    tid, gate, mname, symbol, size, sorted(kwargs.keys()),
                )
                try:
                    result = original(self, *args, **kwargs)
                    passed = _safe_bool(result)
                    reason = _reason(result)
                    logger.warning(
                        "EXEC_GATE_RESULT trace=%s gate=%s method=%s symbol=%s passed=%s reason=%s result_type=%s",
                        tid, gate, mname, symbol, passed, reason, type(result).__name__,
                    )
                    if not passed:
                        logger.error(
                            "EXEC_GATE_FAIL trace=%s gate=%s method=%s symbol=%s reason=%s size=%s",
                            tid, gate, mname, symbol, reason or "gate_returned_false", size,
                        )
                    return result
                except Exception as exc:
                    logger.exception("EXEC_GATE_EXCEPTION trace=%s gate=%s method=%s symbol=%s error=%s", tid, gate, mname, symbol, exc)
                    raise
            return wrapper
        patched = _patch_method(cls, method_name, make_wrapper) or patched
    return patched


def _patch_broker_submit(cls: type) -> bool:
    patched = False
    methods = ("place_order", "submit_order", "create_order", "execute_order", "market_order", "buy_market", "sell_market")
    for method_name in methods:
        def make_wrapper(original: Callable[..., Any], mname: str = method_name):
            @wraps(original)
            def wrapper(self: Any, *args: Any, **kwargs: Any):
                broker = getattr(self, "name", None) or getattr(self, "broker_name", None) or self.__class__.__name__
                symbol = kwargs.get("symbol") or (args[0] if args else None)
                side = kwargs.get("side") or kwargs.get("action") or (args[1] if len(args) > 1 else None)
                qty = kwargs.get("quantity") or kwargs.get("qty") or kwargs.get("amount")
                size = kwargs.get("size_usd") or kwargs.get("notional")
                tid = _trace(symbol, f"broker_{broker}_{mname}")
                logger.warning(
                    "BROKER_SUBMIT_START trace=%s broker=%s method=%s symbol=%s side=%s quantity=%s size_usd=%s kwargs=%s",
                    tid, broker, mname, symbol, side, qty, size, sorted(kwargs.keys()),
                )
                try:
                    result = original(self, *args, **kwargs)
                    order_id = _get(result, "order_id", _get(result, "id", _get(result, "client_order_id")))
                    status = _get(result, "status", _get(result, "state"))
                    error = _get(result, "error", _get(result, "reject_reason"))
                    logger.warning(
                        "BROKER_SUBMIT_RESULT trace=%s broker=%s method=%s symbol=%s side=%s ack=%s order_id=%s status=%s error=%s response_type=%s",
                        tid, broker, mname, symbol, side, bool(result) and not error, order_id, status, error, type(result).__name__,
                    )
                    if error or not result:
                        logger.error("BROKER_SUBMIT_REJECT trace=%s broker=%s symbol=%s reason=%s", tid, broker, symbol, error or "empty_response")
                    return result
                except Exception as exc:
                    logger.exception("BROKER_SUBMIT_EXCEPTION trace=%s broker=%s method=%s symbol=%s error=%s", tid, broker, mname, symbol, exc)
                    raise
            return wrapper
        patched = _patch_method(cls, method_name, make_wrapper) or patched
    return patched


def _patch_order_lifecycle(cls: type) -> bool:
    patched = False
    methods = (
        "record_order", "create_pending_order", "add_pending_order", "mark_ack", "mark_filled",
        "mark_partial_fill", "mark_cancelled", "cancel_order", "reconcile", "reconcile_order",
        "record_fill", "record_reject", "on_order_filled", "on_order_rejected",
    )
    for method_name in methods:
        def make_wrapper(original: Callable[..., Any], mname: str = method_name):
            @wraps(original)
            def wrapper(self: Any, *args: Any, **kwargs: Any):
                symbol = kwargs.get("symbol") or _get(args[0], "symbol") if args else kwargs.get("symbol")
                order_id = kwargs.get("order_id") or _get(args[0], "order_id", _get(args[0], "id")) if args else kwargs.get("order_id")
                tid = _trace(symbol, f"order_{mname}")
                logger.warning("ORDER_LIFECYCLE_START trace=%s event=%s symbol=%s order_id=%s", tid, mname, symbol, order_id)
                try:
                    result = original(self, *args, **kwargs)
                    logger.warning(
                        "ORDER_LIFECYCLE_RESULT trace=%s event=%s symbol=%s order_id=%s success=%s reason=%s",
                        tid, mname, symbol, order_id, _safe_bool(result), _reason(result),
                    )
                    return result
                except Exception as exc:
                    logger.exception("ORDER_LIFECYCLE_EXCEPTION trace=%s event=%s symbol=%s order_id=%s error=%s", tid, mname, symbol, order_id, exc)
                    raise
            return wrapper
        patched = _patch_method(cls, method_name, make_wrapper) or patched
    return patched


def _patch_skips(cls: type) -> bool:
    patched = False
    methods = ("should_enter", "evaluate_signal", "analyze_market", "scan_symbol", "generate_signal", "score_symbol")
    for method_name in methods:
        def make_wrapper(original: Callable[..., Any], mname: str = method_name):
            @wraps(original)
            def wrapper(self: Any, *args: Any, **kwargs: Any):
                symbol = kwargs.get("symbol") or (args[0] if args and isinstance(args[0], str) else None)
                result = original(self, *args, **kwargs)
                action = _get(result, "action")
                allowed = _get(result, "allowed", _get(result, "trade_allowed", _get(result, "approved", None)))
                score = _get(result, "score", _get(result, "confidence"))
                reason = _reason(result)
                if allowed is False or str(action).upper() in {"HOLD", "SKIP", "NONE", "NO_TRADE"}:
                    logger.warning(
                        "SKIPPED_SIGNAL symbol=%s method=%s action=%s allowed=%s score=%s reason=%s",
                        symbol, mname, action, allowed, score, reason or "not_selected",
                    )
                elif result is not None:
                    logger.warning(
                        "SIGNAL_EVALUATED symbol=%s method=%s action=%s allowed=%s score=%s reason=%s",
                        symbol, mname, action, allowed, score, reason,
                    )
                return result
            return wrapper
        patched = _patch_method(cls, method_name, make_wrapper) or patched
    return patched


def _patch_module(module: Any) -> bool:
    if module is None:
        return False
    patched = False
    for name in dir(module):
        obj = getattr(module, name, None)
        if not isinstance(obj, type) or getattr(obj, _PATCHED_ATTR, False):
            continue
        lname = name.lower()
        if any(x in lname for x in ("strategy", "apex", "engine", "coreloop", "core_loop")):
            patched = _patch_candidates(obj) or patched
            patched = _patch_skips(obj) or patched
        if any(x in lname for x in ("risk", "gate", "compiler", "normalizer", "constraint", "pipeline", "governor")):
            patched = _patch_gates(obj) or patched
        if any(x in lname for x in ("broker", "kraken", "coinbase", "okx")):
            patched = _patch_broker_submit(obj) or patched
        if any(x in lname for x in ("order", "pending", "position", "tracker", "ledger")):
            patched = _patch_order_lifecycle(obj) or patched
        if patched:
            setattr(obj, _PATCHED_ATTR, True)
    return patched


def install_import_hook() -> None:
    import sys
    for name, module in list(sys.modules.items()):
        if name.startswith("bot."):
            try:
                _patch_module(module)
            except Exception:
                pass
    if getattr(builtins, "_NIJA_FULL_EXEC_OBS_HOOK_INSTALLED", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.startswith("bot") or name in {"execution_engine", "execution_pipeline", "broker_manager"}:
                _patch_module(module)
        except Exception as exc:
            logger.debug("full execution observability patch skipped for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_FULL_EXEC_OBS_HOOK_INSTALLED", True)
    logger.warning("FULL_EXECUTION_OBSERVABILITY_INSTALL_COMPLETE")
