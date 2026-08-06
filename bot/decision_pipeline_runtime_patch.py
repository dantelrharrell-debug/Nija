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
import os
import threading
import time
import weakref
from collections import Counter
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.decision_pipeline")
_PATCHED_ATTR = "__nija_decision_pipeline_patch__"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}
_STATE_LOCK = threading.Lock()
_REJECTION_COUNTS: Counter[str] = Counter()
_LAST_ORDER_SUBMITTED_TS = 0.0
_LAST_REJECTION_SUMMARY_TS = 0.0
_READY_SINCE_TS = 0.0
_RESTART_LAST_ATTEMPT_TS: dict[str, float] = {}
_RESTART_TARGETS: dict[str, tuple[weakref.ReferenceType[Any], str]] = {}
_MONITOR_STARTED = False
_MONITOR_LOCK = threading.Lock()
_STAGE_HEARTBEATS = {
    "scan_scheduler": 0.0,
    "market_scanner": 0.0,
    "strategy_evaluation": 0.0,
    "risk_manager": 0.0,
    "execution_dispatcher": 0.0,
}


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _is_three_venue_ready() -> bool:
    ready = (
        _truthy_env("NIJA_THREE_VENUE_EXECUTION_READY")
        or _truthy_env("THREE_VENUE_EXECUTION_READY")
    )
    execution_enabled = (
        _truthy_env("NIJA_EXECUTION_ENABLED", True)
        or _truthy_env("EXECUTION_ENABLED", True)
    )
    try:
        from bot.writer_authority import WriterAuthority
    except ImportError:
        from writer_authority import WriterAuthority  # type: ignore[import]
    writer_ready = bool(
        WriterAuthority.get_status(
            force_refresh=False,
            enforce_active_invariant=True,
        ).ready
    )
    return bool(ready and execution_enabled and writer_ready)


def _format_field_value(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.8f}"
    return str(value).replace(" ", "_")


def _emit_event(event: str, **fields: Any) -> None:
    payload = [f"{k}={_format_field_value(v)}" for k, v in fields.items()]
    logger.warning("%s %s", event, " ".join(payload).strip())


def _register_restart_target(stage: str, instance: Any, method_name: str) -> None:
    if instance is None or not method_name or not callable(getattr(instance, method_name, None)):
        return
    with _STATE_LOCK:
        _RESTART_TARGETS[stage] = (weakref.ref(instance), method_name)


def _heartbeat(stage: str) -> None:
    now = time.time()
    with _STATE_LOCK:
        _STAGE_HEARTBEATS[stage] = now


def _extract_exchange_from_obj(obj: Any) -> str:
    for key in ("exchange", "broker", "venue", "broker_name"):
        value = _safe_get(obj, key, None)
        if value:
            return str(value)
    return "unknown"


def _reject_event_for_reason(reason: str) -> str:
    text = str(reason or "").strip().lower()
    if "position" in text and ("limit" in text or "cap" in text or "max" in text):
        return "POSITION_LIMIT_REJECT"
    if "min_notional" in text or "notional" in text:
        return "MIN_NOTIONAL_REJECT"
    if "cooldown" in text:
        return "COOLDOWN_REJECT"
    if "spread" in text or "slippage" in text:
        return "SPREAD_REJECT"
    if "volatility" in text:
        return "VOLATILITY_REJECT"
    if "trend" in text or "regime" in text or "market_filter" in text:
        return "TREND_REJECT"
    if "confidence" in text or "threshold" in text or "rsi" in text:
        return "CONFIDENCE_REJECT"
    if "risk" in text or "drawdown" in text or "exposure" in text:
        return "RISK_FILTER_REJECT"
    return "ENTRY_FILTER_REJECT"


def _record_rejection(
    *,
    event: str,
    symbol: Any,
    exchange: Any,
    strategy: Any,
    reason: Any,
    threshold: Any = None,
    actual_value: Any = None,
) -> None:
    reason_text = str(reason or "unspecified")
    with _STATE_LOCK:
        _REJECTION_COUNTS[reason_text] += 1
    _emit_event(
        event,
        symbol=symbol,
        exchange=exchange,
        strategy=strategy,
        reason=reason_text,
        threshold=threshold,
        actual_value=actual_value,
    )
    _emit_event(
        "SIGNAL_REJECTED",
        symbol=symbol,
        exchange=exchange,
        strategy=strategy,
        reason=reason_text,
        threshold=threshold,
        actual_value=actual_value,
    )


def _mark_order_submitted() -> None:
    global _LAST_ORDER_SUBMITTED_TS
    with _STATE_LOCK:
        _LAST_ORDER_SUBMITTED_TS = time.time()


def _emit_rejection_summary_if_due(now: float | None = None) -> None:
    global _LAST_REJECTION_SUMMARY_TS
    current = now if now is not None else time.time()
    with _STATE_LOCK:
        if _LAST_ORDER_SUBMITTED_TS > 0:
            return
        if current - _LAST_REJECTION_SUMMARY_TS < 60.0:
            return
        if not _REJECTION_COUNTS:
            return
        summary = ",".join(f"{reason}:{count}" for reason, count in sorted(_REJECTION_COUNTS.items()))
        _LAST_REJECTION_SUMMARY_TS = current
    _emit_event("REJECTION_SUMMARY", interval_seconds=60, counts_by_reason=summary)


def _resolve_restart_target(stage: str) -> tuple[Any, str] | tuple[None, None]:
    with _STATE_LOCK:
        target = _RESTART_TARGETS.get(stage) or _RESTART_TARGETS.get("scan_scheduler")
    if not target:
        return None, None
    ref, method_name = target
    instance = ref()
    if instance is None:
        return None, None
    return instance, method_name


def _attempt_stage_restart(stage: str, reason: str) -> None:
    now = time.time()
    cooldown = max(30.0, float(os.getenv("NIJA_AUDIT_STAGE_RESTART_COOLDOWN_S", "60") or "60"))
    with _STATE_LOCK:
        last_attempt = _RESTART_LAST_ATTEMPT_TS.get(stage, 0.0)
        if now - last_attempt < cooldown:
            return
        _RESTART_LAST_ATTEMPT_TS[stage] = now
    instance, method_name = _resolve_restart_target(stage)
    if instance is None or not method_name:
        _emit_event("PIPELINE_STAGE_RESTART_SKIPPED", stage=stage, reason=reason, detail="restart_target_unavailable")
        return

    def _runner() -> None:
        try:
            _emit_event("PIPELINE_STAGE_RESTART", stage=stage, reason=reason, method=method_name)
            getattr(instance, method_name)()
        except Exception as exc:
            _emit_event("PIPELINE_STAGE_RESTART_FAILED", stage=stage, reason=reason, error=f"{type(exc).__name__}:{exc}")

    threading.Thread(target=_runner, name=f"nija-stage-restart-{stage}", daemon=True).start()


def _ensure_monitor_started() -> None:
    global _MONITOR_STARTED, _READY_SINCE_TS
    if _MONITOR_STARTED:
        return
    with _MONITOR_LOCK:
        if _MONITOR_STARTED:
            return
        _MONITOR_STARTED = True

        def _monitor() -> None:
            global _READY_SINCE_TS
            while True:
                time.sleep(5.0)
                ready = _is_three_venue_ready()
                now = time.time()
                if ready and _READY_SINCE_TS <= 0:
                    _READY_SINCE_TS = now
                    _emit_event("THREE_VENUE_EXECUTION_READY", execution_enabled=True, writer_ready=True)
                if not ready:
                    continue
                _emit_rejection_summary_if_due(now)
                idle_limit = max(30.0, float(os.getenv("NIJA_AUDIT_STAGE_IDLE_SECONDS", "120") or "120"))
                for stage, ts in list(_STAGE_HEARTBEATS.items()):
                    if ts <= 0:
                        if _READY_SINCE_TS > 0 and now - _READY_SINCE_TS > idle_limit:
                            _attempt_stage_restart(stage, "never_started_after_ready")
                        continue
                    idle_for = now - ts
                    if idle_for > idle_limit:
                        _attempt_stage_restart(stage, f"idle_for_{int(idle_for)}s")

        threading.Thread(target=_monitor, name="nija-live-pipeline-audit-monitor", daemon=True).start()
        _emit_event("LIVE_PIPELINE_AUDIT_MONITOR_STARTED")


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
            exchange = _safe_get(analysis, "exchange", getattr(self, "_get_broker_name", lambda: "unknown")())
            strategy = _safe_get(analysis, "strategy", cls.__name__)
            _heartbeat("execution_dispatcher")
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
            _emit_event(
                "ORDER_CREATED",
                symbol=symbol,
                exchange=exchange,
                strategy=strategy,
                action=action,
                threshold=_safe_get(analysis, "threshold_used"),
                actual_value=score,
            )
            _emit_event(
                "ORDER_SUBMITTED",
                symbol=symbol,
                exchange=exchange,
                strategy=strategy,
                action=action,
                threshold=_safe_get(analysis, "threshold_used"),
                actual_value=score,
            )
            _mark_order_submitted()
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
                    _emit_event(
                        "ORDER_REJECTED",
                        symbol=symbol,
                        exchange=exchange,
                        strategy=strategy,
                        reason="execute_action_returned_false",
                    )
                    _record_rejection(
                        event="ENTRY_FILTER_REJECT",
                        symbol=symbol,
                        exchange=exchange,
                        strategy=strategy,
                        reason="execute_action_returned_false",
                        threshold=_safe_get(analysis, "threshold_used"),
                        actual_value=score,
                    )
                    logger.error(
                        "DECISION_PIPELINE_BLOCK trace=%s symbol=%s stage=execute_action reason=returned_false_or_none action=%s score=%s",
                        trace_id,
                        symbol,
                        action,
                        score,
                    )
                else:
                    _emit_event(
                        "ORDER_ACCEPTED",
                        symbol=symbol,
                        exchange=exchange,
                        strategy=strategy,
                        action=action,
                    )
                return result
            except Exception as exc:
                _emit_event(
                    "ORDER_REJECTED",
                    symbol=symbol,
                    exchange=exchange,
                    strategy=strategy,
                    reason=f"{type(exc).__name__}:{exc}",
                )
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
            _heartbeat("execution_dispatcher")
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
            _heartbeat("execution_dispatcher")
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
                    _record_rejection(
                        event="RISK_FILTER_REJECT",
                        symbol=symbol,
                        exchange=broker,
                        strategy=cls.__name__,
                        reason=error or "pipeline_returned_unsuccessful",
                        threshold=None,
                        actual_value=size,
                    )
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
            _heartbeat("execution_dispatcher")
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
                    _emit_event(
                        "ORDER_REJECTED",
                        symbol=symbol,
                        exchange=broker,
                        strategy=cls.__name__,
                        reason=error or "broker_returned_empty_result",
                    )
                    logger.error(
                        "DECISION_PIPELINE_BLOCK trace=%s symbol=%s stage=broker_submit broker=%s reason=%s",
                        trace_id,
                        symbol,
                        broker,
                        error or "broker_returned_empty_result",
                    )
                else:
                    _emit_event(
                        "ORDER_ACCEPTED",
                        symbol=symbol,
                        exchange=broker,
                        strategy=cls.__name__,
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


def _patch_ai_source(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    patched = False
    original_eval = getattr(cls, "evaluate_symbol", None)
    if callable(original_eval):
        @wraps(original_eval)
        def evaluate_symbol(self: Any, *args: Any, **kwargs: Any):
            symbol = kwargs.get("symbol")
            if symbol is None and args:
                symbol = _safe_get(args[0], "symbol", "unknown")
            _heartbeat("strategy_evaluation")
            result = original_eval(self, *args, **kwargs)
            if result is None:
                threshold = kwargs.get("threshold") or kwargs.get("ai_threshold")
                _record_rejection(
                    event="CONFIDENCE_REJECT",
                    symbol=symbol,
                    exchange=kwargs.get("broker", "unknown"),
                    strategy=cls.__name__,
                    reason="evaluate_symbol_returned_none",
                    threshold=threshold,
                    actual_value=None,
                )
                return result
            _emit_event(
                "SIGNAL_CREATED",
                symbol=_safe_get(result, "symbol", symbol),
                exchange=kwargs.get("broker", "unknown"),
                strategy=cls.__name__,
                threshold=_safe_get(result, "threshold_used", kwargs.get("threshold")),
                actual_value=_safe_get(result, "composite_score", None),
            )
            return result

        setattr(cls, "evaluate_symbol", evaluate_symbol)
        patched = True

    original_rank = getattr(cls, "rank_and_select", None)
    if callable(original_rank):
        @wraps(original_rank)
        def rank_and_select(self: Any, candidates: Any, *args: Any, **kwargs: Any):
            selected = original_rank(self, candidates, *args, **kwargs)
            for sig in list(selected or []):
                _emit_event(
                    "SYMBOL_SELECTED",
                    symbol=_safe_get(sig, "symbol"),
                    exchange=_safe_get(sig, "exchange", "unknown"),
                    strategy=cls.__name__,
                    threshold=_safe_get(sig, "threshold_used"),
                    actual_value=_safe_get(sig, "composite_score"),
                )
                _emit_event(
                    "SIGNAL_ACCEPTED",
                    symbol=_safe_get(sig, "symbol"),
                    exchange=_safe_get(sig, "exchange", "unknown"),
                    strategy=cls.__name__,
                    threshold=_safe_get(sig, "threshold_used"),
                    actual_value=_safe_get(sig, "composite_score"),
                )
            return selected

        setattr(cls, "rank_and_select", rank_and_select)
        patched = True

    if patched:
        setattr(cls, _PATCHED_ATTR, True)
    return patched


def _patch_risk_gate_class(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    patched = False
    for method_name in ("evaluate", "validate_trade"):
        original = getattr(cls, method_name, None)
        if not callable(original):
            continue

        @wraps(original)
        def wrapper(self: Any, *args: Any, __original=original, __method_name=method_name, **kwargs: Any):
            _heartbeat("risk_manager")
            result = __original(self, *args, **kwargs)
            symbol = kwargs.get("symbol") or _safe_get(result, "symbol", "unknown")
            exchange = _extract_exchange_from_obj(result)
            strategy = cls.__name__
            if __method_name == "validate_trade" and isinstance(result, tuple):
                approved = bool(result[0])
                reason = result[1] if len(result) > 1 else ""
                if approved:
                    _emit_event("ENTRY_APPROVED", symbol=symbol, exchange=exchange, strategy=strategy, reason="risk_validated")
                else:
                    _record_rejection(
                        event="RISK_FILTER_REJECT",
                        symbol=symbol,
                        exchange=exchange,
                        strategy=strategy,
                        reason=reason or "risk_validate_rejected",
                        threshold=None,
                        actual_value=kwargs.get("size_usd"),
                    )
                return result
            decision = str(_safe_get(result, "final_decision", "EXECUTE"))
            reason = _safe_get(result, "block_reason", "") or _safe_get(result, "reason", "")
            threshold = kwargs.get("ai_threshold")
            actual = kwargs.get("ai_score")
            if decision == "EXECUTE":
                _emit_event("ENTRY_APPROVED", symbol=symbol, exchange=exchange, strategy=strategy, reason="risk_execute")
            else:
                reject_event = _reject_event_for_reason(str(reason))
                _record_rejection(
                    event=reject_event,
                    symbol=symbol,
                    exchange=exchange,
                    strategy=strategy,
                    reason=reason or "risk_blocked",
                    threshold=threshold,
                    actual_value=actual,
                )
            return result

        setattr(cls, method_name, wrapper)
        patched = True

    if patched:
        setattr(cls, _PATCHED_ATTR, True)
    return patched


def _patch_core_loop(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    patched = False

    for method_name in ("start", "run", "main_loop"):
        original = getattr(cls, method_name, None)
        if not callable(original):
            continue

        @wraps(original)
        def lifecycle(self: Any, *args: Any, __original=original, __method_name=method_name, **kwargs: Any):
            _heartbeat("scan_scheduler")
            _register_restart_target("scan_scheduler", self, __method_name)
            _emit_event("SCAN_STARTED", method=__method_name, source=cls.__name__)
            return __original(self, *args, **kwargs)

        setattr(cls, method_name, lifecycle)
        patched = True

    original_scan = getattr(cls, "run_scan_phase", None)
    if callable(original_scan):
        @wraps(original_scan)
        def run_scan_phase(self: Any, *args: Any, **kwargs: Any):
            symbols = kwargs.get("symbols")
            if symbols is None and len(args) >= 3:
                symbols = args[2]
            symbols_count = len(symbols or [])
            _heartbeat("market_scanner")
            _emit_event("SCAN_STARTED", symbols=symbols_count, source=f"{cls.__name__}.run_scan_phase")
            result = original_scan(self, *args, **kwargs)
            _emit_event(
                "MARKET_SCAN_COMPLETE",
                symbols=symbols_count,
                entries_taken=_safe_get(result, "entries_taken", None),
                entries_blocked=_safe_get(result, "entries_blocked", None),
                symbols_scored=_safe_get(result, "symbols_scored", None),
            )
            return result

        setattr(cls, "run_scan_phase", run_scan_phase)
        patched = True

    original_phase3 = getattr(cls, "_phase3_scan_and_enter", None)
    if callable(original_phase3):
        @wraps(original_phase3)
        def phase3(self: Any, *args: Any, **kwargs: Any):
            _heartbeat("strategy_evaluation")
            entries, blocked, scored, gate_counts = original_phase3(self, *args, **kwargs)
            if blocked and not entries:
                for reason, count in dict(gate_counts or {}).items():
                    if not count:
                        continue
                    reject_event = _reject_event_for_reason(reason)
                    _record_rejection(
                        event=reject_event,
                        symbol="unknown",
                        exchange="unknown",
                        strategy=cls.__name__,
                        reason=f"{reason}:{count}",
                        threshold=None,
                        actual_value=count,
                    )
            if entries > 0:
                _emit_event("ENTRY_APPROVED", symbol="cycle", exchange="runtime", strategy=cls.__name__, actual_value=entries)
            return entries, blocked, scored, gate_counts

        setattr(cls, "_phase3_scan_and_enter", phase3)
        patched = True

    if patched:
        setattr(cls, _PATCHED_ATTR, True)
        logger.warning("DECISION_PIPELINE_CORE_LOOP_PATCHED class=%s", cls.__name__)
    return patched


def _patch_independent_trader(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    patched = False
    for method_name in ("start_independent_trading", "run_broker_trading_loop", "_execute_trading_cycle"):
        original = getattr(cls, method_name, None)
        if not callable(original):
            continue

        @wraps(original)
        def wrapper(self: Any, *args: Any, __original=original, __method_name=method_name, **kwargs: Any):
            _heartbeat("scan_scheduler" if __method_name == "start_independent_trading" else "market_scanner")
            if __method_name == "start_independent_trading":
                _register_restart_target("scan_scheduler", self, __method_name)
            return __original(self, *args, **kwargs)

        setattr(cls, method_name, wrapper)
        patched = True

    if patched:
        setattr(cls, _PATCHED_ATTR, True)
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
        if "aiengine" in lname or ("ai" in lname and "engine" in lname):
            patched = _patch_ai_source(obj) or patched
        if "pipeline" in lname:
            patched = _patch_pipeline(obj) or patched
        if "risk" in lname and ("engine" in lname or "permission" in lname):
            patched = _patch_risk_gate_class(obj) or patched
        if "coreloop" in lname:
            patched = _patch_core_loop(obj) or patched
        if "independentbrokertrader" in lname:
            patched = _patch_independent_trader(obj) or patched
        if "broker" in lname or "kraken" in lname or "coinbase" in lname or "okx" in lname:
            patched = _patch_broker_class(obj) or patched
    return patched


def install_import_hook() -> None:
    import sys

    _ensure_monitor_started()

    for name, module in list(sys.modules.items()):
        if name.startswith("bot.") and name.endswith(
            (
                "nija_apex_strategy_v71",
                "trading_strategy",
                "execution_pipeline",
                "broker_manager",
                "execution_engine",
                "nija_ai_engine",
                "trade_permission_engine",
                "nija_core_loop",
                "independent_broker_trader",
                "control.signal_pipeline",
                "control.risk_engine",
            )
        ):
            _patch_module(module)

    if getattr(builtins, "_NIJA_DECISION_PIPELINE_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name.endswith(
            (
                "nija_apex_strategy_v71",
                "trading_strategy",
                "execution_pipeline",
                "broker_manager",
                "execution_engine",
                "nija_ai_engine",
                "trade_permission_engine",
                "nija_core_loop",
                "independent_broker_trader",
                "signal_pipeline",
                "risk_engine",
            )
        ):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("Decision pipeline patch failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_DECISION_PIPELINE_HOOK_INSTALLED", True)
    logger.warning("DECISION_PIPELINE_INSTALL_COMPLETE")
