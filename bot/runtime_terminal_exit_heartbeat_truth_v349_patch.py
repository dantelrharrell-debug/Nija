"""Terminal protective-exit + heartbeat rejection truth convergence v349.

Production evidence on 2026-09-03 exposed two final safety/liveness defects:

* an authoritative 35.34862 CELO protective close was enlarged by ECEL to the
  venue minimum of 70 CELO.  v343 caps the earlier v341 base-quantity path, but
  a later ECEL compile can still enlarge the effective order.  v349 adds a
  post-ECEL, pre-broker terminal firewall: a protective SELL-to-close may never
  exceed independently verified holdings.  If the venue minimum cannot be met
  without overselling, the order is deterministically deferred; it is never
  rounded up and never dispatched.
* heartbeat BUY attempts with a generic local ``status=error`` were reported as
  exchange ``rejected_orders`` unconditionally.  Five local/pre-dispatch
  failures could therefore trip the execution circuit breaker before a genuine
  execution proof was possible.  v349 records the actual heartbeat pipeline
  result and excludes only proven local/pre-dispatch deferrals from the
  exchange-rejection breaker.  Explicit/unknown exchange failures remain
  unchanged and continue to count.

No readiness, position, ACK, fill, broker response or protective coverage is
fabricated.  The patch never clears a circuit breaker, never forces a trade or
activation, never bypasses ECEL/minimum rules, and never enlarges an exit.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_terminal_exit_heartbeat_truth_v349")
MARKER = "20260903-runtime-terminal-exit-heartbeat-truth-v349"
RELEASE_ID = "20260903-runtime-convergence-v349"
_READY_FLAG = "NIJA_RUNTIME_TERMINAL_EXIT_HEARTBEAT_TRUTH_V349_READY"
_LOCK = threading.RLock()
_TLS = threading.local()
_COMPILED: dict[int, tuple[float, float, str]] = {}
_COMPILED_LOCK = threading.Lock()
_LOG_PATCH = "_nija_v349_post_ecel_capture"
_GATE_PATCH = "_nija_v349_terminal_exit_firewall"
_HB_SUBMIT_PATCH = "_nija_v349_heartbeat_submit_provenance"
_ANOMALY_PATCH = "_nija_v349_heartbeat_rejection_truth"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _meta(request: Any) -> dict[str, Any]:
    raw = getattr(request, "metadata", None)
    return dict(raw or {}) if isinstance(raw, Mapping) else {}


def _protective_exit(request: Any) -> tuple[bool, float, str]:
    meta = _meta(request)
    side = str(getattr(request, "side", "") or meta.get("side") or "").strip().lower()
    intent = str(getattr(request, "intent_type", "") or meta.get("intent_type") or meta.get("intent") or "").strip().lower()
    effect = str(getattr(request, "position_effect", "") or meta.get("position_effect") or "").strip().lower()
    origin = str(meta.get("origin") or meta.get("exit_origin") or meta.get("source") or "").strip().lower()
    verified = _f(meta.get("verified_position_quantity"), 0.0)
    trusted_origin = origin in {"universal_v67", "kraken_account_exit", "protective_exit", "auto_exit"}
    is_exit = side == "sell" and verified > 0.0 and (
        intent in {"exit", "reduce", "close"} or effect == "close" or trusted_origin
    )
    return is_exit, verified, origin


def _patch_pipeline_terminal_firewall() -> bool:
    module = importlib.import_module("bot.execution_pipeline")
    cls = getattr(module, "ExecutionPipeline", None)
    result_cls = getattr(module, "PipelineResult", None)
    if not isinstance(cls, type) or not callable(result_cls):
        return False

    current_log = getattr(cls, "_log_ecel_final_order", None)
    current_gate = getattr(cls, "_gate_broker_capabilities", None)
    if not callable(current_log) or not callable(current_gate):
        return False

    if not bool(getattr(current_log, _LOG_PATCH, False)):
        original_log = current_log

        @wraps(original_log)
        def log_v349(self: Any, request: Any, compiled: Any) -> Any:
            result = original_log(self, request, compiled)
            try:
                if compiled is not None and bool(getattr(compiled, "accepted", False)):
                    base = _f(getattr(compiled, "compiled_base_size", None), 0.0)
                    price = _f(getattr(compiled, "compiled_price_usd", None), 0.0)
                    reason = str(getattr(compiled, "reason", "") or "")
                    with _COMPILED_LOCK:
                        _COMPILED[id(request)] = (base, price, reason)
            except Exception:
                LOGGER.debug("v349 ECEL capture failed", exc_info=True)
            return result

        setattr(log_v349, _LOG_PATCH, True)
        setattr(log_v349, "__wrapped__", original_log)
        cls._log_ecel_final_order = log_v349

    current_gate = getattr(cls, "_gate_broker_capabilities", None)
    if not callable(current_gate):
        return False
    if not bool(getattr(current_gate, _GATE_PATCH, False)):
        original_gate = current_gate

        @wraps(original_gate)
        def gate_v349(self: Any, request: Any, t_start: float) -> Any:
            with _COMPILED_LOCK:
                compiled_base, compiled_price, compile_reason = _COMPILED.pop(id(request), (0.0, 0.0, ""))
            is_exit, verified, origin = _protective_exit(request)
            if is_exit and compiled_base > 0.0:
                tolerance = max(1e-12, abs(verified) * 1e-8)
                if compiled_base > verified + tolerance:
                    error = (
                        "EXIT_BELOW_EXCHANGE_MIN_AFTER_HOLDINGS_CAP "
                        f"verified_qty={verified:.12g} compiled_qty={compiled_base:.12g} "
                        "oversell_blocked=true"
                    )
                    LOGGER.critical(
                        "TERMINAL_EXIT_V349_OVERSELL_BLOCKED marker=%s symbol=%s account=%s "
                        "verified_qty=%.12f compiled_qty=%.12f compiled_price=%.10f origin=%s "
                        "compile_reason=%s broker_dispatch=false tracker_preserved=true "
                        "minimum_order_bypass=false exchange_rejection=false fill_fabricated=false "
                        "safety_gates_bypassed=false",
                        MARKER,
                        str(getattr(request, "symbol", "") or ""),
                        str(getattr(request, "account_id", "") or ""),
                        verified,
                        compiled_base,
                        compiled_price,
                        origin or "unknown",
                        compile_reason or "accepted",
                    )
                    return result_cls(
                        success=False,
                        symbol=str(getattr(request, "symbol", "") or ""),
                        side=str(getattr(request, "side", "") or ""),
                        size_usd=_f(getattr(request, "size_usd", 0.0), 0.0),
                        error=error,
                        latency_ms=max(0.0, (time.monotonic() - float(t_start)) * 1000.0),
                    )
            return original_gate(self, request, t_start)

        setattr(gate_v349, _GATE_PATCH, True)
        setattr(gate_v349, "__wrapped__", original_gate)
        cls._gate_broker_capabilities = gate_v349

    return bool(getattr(getattr(cls, "_log_ecel_final_order", None), _LOG_PATCH, False)) and bool(
        getattr(getattr(cls, "_gate_broker_capabilities", None), _GATE_PATCH, False)
    )


_LOCAL_HEARTBEAT_ERROR_MARKERS = (
    "execution quality filter deferred",
    "execution gate pending",
    "execution gate blocked",
    "state_machine=",
    "trading_state_machine",
    "throttl",
    "pretrade",
    "pre-trade",
    "risk gate",
    "risk blocked",
    "capitalauthorization",
    "capital authorization",
    "position sync",
    "position_sync",
    "ecel",
    "below_min",
    "minimum order",
    "min_notional",
    "min_qty",
    "submit helper unavailable",
    "direct broker fallback blocked",
    "circuit breaker",
    "writer",
    "nonce",
    "reconciliation",
    "broker health",
)


def _result_fields(result: Any) -> tuple[str, str, str]:
    if isinstance(result, Mapping):
        status = str(result.get("status") or "").strip().lower()
        error = str(result.get("error") or result.get("message") or "").strip()
        order_id = str(result.get("order_id") or result.get("id") or "").strip()
        return status, error, order_id
    status = str(getattr(result, "status", "") or "").strip().lower()
    error = str(getattr(result, "error", "") or "").strip()
    order_id = str(getattr(result, "order_id", "") or getattr(result, "id", "") or "").strip()
    return status, error, order_id


def _patch_heartbeat_submit_provenance() -> bool:
    patched = False
    for name in ("bot.trading_strategy", "trading_strategy"):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        current = getattr(module, "submit_market_order_via_pipeline", None)
        if not callable(current):
            continue
        if bool(getattr(current, _HB_SUBMIT_PATCH, False)):
            patched = True
            continue
        original = current

        @wraps(original)
        def submit_v349(*args: Any, __original=original, **kwargs: Any) -> Any:
            result = __original(*args, **kwargs)
            strategy = str(kwargs.get("strategy") or "").strip().upper()
            if strategy in {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}:
                status, error, order_id = _result_fields(result)
                _TLS.heartbeat_result = {
                    "strategy": strategy,
                    "status": status,
                    "error": error,
                    "order_id": order_id,
                }
            return result

        setattr(submit_v349, _HB_SUBMIT_PATCH, True)
        setattr(submit_v349, "__wrapped__", original)
        module.submit_market_order_via_pipeline = submit_v349
        patched = True
    return patched


def _proven_local_heartbeat_error(detail: str) -> tuple[bool, str]:
    text = str(detail or "").strip().lower()
    if not (text.startswith("heartbeat_buy_not_accepted status=error") or text.startswith("heartbeat_stage_insufficient")):
        return False, "not_target"
    result = getattr(_TLS, "heartbeat_result", None)
    if not isinstance(result, Mapping):
        return False, "provenance_missing"
    order_id = str(result.get("order_id") or "").strip()
    error = str(result.get("error") or "").strip().lower()
    status = str(result.get("status") or "").strip().lower()
    # Never suppress an explicit exchange acknowledgement/order id or an
    # explicit rejected status.  Unknown errors continue to count fail-closed.
    if order_id or status == "rejected":
        return False, "exchange_provenance_present"
    if any(marker in error for marker in _LOCAL_HEARTBEAT_ERROR_MARKERS):
        return True, error[:240]
    # Stage insufficiency after an accepted order is a verification/fill
    # problem, not an order rejection.  Keep fill/partial-fill handling intact
    # but do not poison the rejected-order counter.
    if text.startswith("heartbeat_stage_insufficient") and status not in {"rejected", "error", "failed"}:
        return True, f"verification_stage_only status={status or 'unknown'}"
    return False, "unclassified_error"


def _patch_execution_anomaly_truth() -> bool:
    tsm = importlib.import_module("bot.trading_state_machine")
    current = getattr(tsm, "report_execution_anomaly", None)
    if not callable(current):
        return False
    if bool(getattr(current, _ANOMALY_PATCH, False)):
        return True
    original = current

    @wraps(original)
    def report_v349(kind: str, detail: str = "", *args: Any, **kwargs: Any) -> Any:
        if str(kind or "").strip().lower() == "rejected_orders":
            local, why = _proven_local_heartbeat_error(str(detail or ""))
            if local:
                LOGGER.warning(
                    "HEARTBEAT_REJECTION_V349_LOCAL_DEFERRED marker=%s detail=%s provenance=%s "
                    "rejected_order_counter_incremented=false exchange_rejection_suppressed=false "
                    "heartbeat_retry_preserved=true execution_proof_fabricated=false",
                    MARKER, str(detail or "")[:300], why,
                )
                return None
        return original(kind, detail, *args, **kwargs)

    setattr(report_v349, _ANOMALY_PATCH, True)
    setattr(report_v349, "__wrapped__", original)
    tsm.report_execution_anomaly = report_v349
    try:
        alias = importlib.import_module("trading_state_machine")
        alias.report_execution_anomaly = report_v349
    except Exception:
        pass
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_terminal_exit_heartbeat_truth_v349"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        terminal = heartbeat = anomaly = manifest = False
        try:
            terminal = _patch_pipeline_terminal_firewall()
            heartbeat = _patch_heartbeat_submit_provenance()
            anomaly = _patch_execution_anomaly_truth()
            manifest = _register_manifest()
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_TERMINAL_EXIT_HEARTBEAT_TRUTH_V349_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        ready = bool(terminal and heartbeat and anomaly and manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_TERMINAL_EXIT_HEARTBEAT_TRUTH_V349_%s marker=%s ready=%s "
            "post_ecel_holdings_firewall=%s heartbeat_submit_provenance=%s heartbeat_rejection_truth=%s manifest=%s "
            "exit_never_enlarged=true below_min_exit_deferred=true broker_dispatch_on_oversell=false "
            "explicit_exchange_rejections_unchanged=true unknown_heartbeat_errors_fail_closed=true "
            "circuit_breaker_not_cleared=true confirmed_fill_required=true forced_trade=false forced_activation=false "
            "writer_nonce_risk_capital_killswitch_position_sync_ecel_broker_health_order_ack_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(), str(terminal).lower(),
            str(heartbeat).lower(), str(anomaly).lower(), str(manifest).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook"]
