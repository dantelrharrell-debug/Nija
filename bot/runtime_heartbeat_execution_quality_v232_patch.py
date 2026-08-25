"""Heartbeat execution-quality liveness and rejection provenance repair (v232).

Production on 2026-08-25 proved that the canonical heartbeat startup probe can
reach MultiBrokerExecutionRouter and still be trapped by the AI execution-quality
filter.  A DEFER result is a local pre-dispatch scheduling decision: no request
has reached Coinbase/Kraken/OKX.  ExecutionPipeline._on_order_rejected previously
handled that RouteResult as an unknown exchange rejection, emitted
accepted=False telemetry, and raised ``ECEL FAILURE - INVALID ORDER ESCAPED``.
That could contaminate the exchange-rejection window and also prevented the
heartbeat ORDER_VERIFY marker needed by activation.

The same production trace showed score=57.5 in the documented DEFER band.  The
quality filter already has a native high-urgency policy that upgrades DEFER to
APPROVE while preserving REJECT.  v232 uses that existing policy only for the
already-whitelisted startup probe strategies ``HEARTBEAT_TRADE`` and
``HEARTBEAT_TRADE_CLOSE``.  Ordinary orders keep their existing urgency and
quality policy.

Safety properties:
* Quality REJECT is never bypassed.  Only DEFER may be upgraded by the filter's
  existing high-urgency rule.
* ECEL, minimum-notional, risk, writer, nonce, capital, broker-health,
  reconciliation, kill-switch, order and fill gates are unchanged.
* A local execution-quality DEFER/REJECT is not reported as an exchange response
  and cannot add an exchange rejection sample.
* No execution proof, heartbeat marker, authority, nonce readiness or activation
  state is fabricated.  Genuine exchange ORDER/FILL proof is still required.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_execution_quality_v232")
MARKER = "20260825-heartbeat-execution-quality-v232"
_READY_FLAG = "NIJA_HEARTBEAT_EXECUTION_QUALITY_V232_READY"
_ROUTE_PATCH_ATTR = "_nija_heartbeat_execution_quality_v232_route"
_REJECT_PATCH_ATTR = "_nija_heartbeat_execution_quality_v232_reject"
_LOCK = threading.RLock()

_HEARTBEAT_STRATEGIES = frozenset({"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"})
_LOCAL_QUALITY_PREFIXES = (
    "execution quality filter deferred",
    "execution quality filter rejected",
)
# Must remain at/above execution_quality_filter.URGENCY_DEFER_OVERRIDE (0.75).
_HEARTBEAT_URGENCY = 1.0


def _is_heartbeat_strategy(value: Any) -> bool:
    return str(value or "").strip().upper() in _HEARTBEAT_STRATEGIES


def _is_local_quality_gate_error(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return any(text.startswith(prefix) for prefix in _LOCAL_QUALITY_PREFIXES)


def _wrap_router_route(current: Callable[..., Any]) -> Callable[..., Any]:
    """Apply the filter's native high-urgency DEFER policy to startup probes.

    ``RouteRequest`` is intentionally not widened with a new schema field.  The
    existing router reads urgency through ``getattr(request, 'urgency', 0.5)``;
    the wrapper supplies the transient attribute only while the synchronous
    route call runs and then restores the request exactly.
    """
    if bool(getattr(current, _ROUTE_PATCH_ATTR, False)):
        return current

    @wraps(current)
    def route_v232(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_heartbeat_strategy(getattr(request, "strategy", "")):
            return current(self, request, *args, **kwargs)

        had_urgency = hasattr(request, "urgency")
        prior_urgency = getattr(request, "urgency", None)
        try:
            try:
                prior_value = float(prior_urgency)
            except (TypeError, ValueError):
                prior_value = 0.5
            # Never lower an explicitly stronger urgency supplied by a caller.
            effective = max(prior_value, _HEARTBEAT_URGENCY)
            setattr(request, "urgency", effective)
            LOGGER.critical(
                "HEARTBEAT_EXECUTION_QUALITY_V232_URGENCY marker=%s strategy=%s "
                "urgency_before=%.2f urgency_after=%.2f native_defer_override_only=true "
                "quality_reject_preserved=true ordinary_orders_unchanged=true "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
                str(getattr(request, "strategy", "")),
                prior_value,
                effective,
            )
            return current(self, request, *args, **kwargs)
        finally:
            try:
                if had_urgency:
                    setattr(request, "urgency", prior_urgency)
                else:
                    delattr(request, "urgency")
            except Exception:
                # RouteRequest is currently mutable.  If a future request type
                # restricts attribute restoration, do not mask the route result.
                pass

    setattr(route_v232, _ROUTE_PATCH_ATTR, True)
    setattr(route_v232, "__wrapped__", current)
    return route_v232


def _wrap_order_rejected(current: Callable[..., Any]) -> Callable[..., Any]:
    """Keep local execution-quality decisions out of exchange telemetry."""
    if bool(getattr(current, _REJECT_PATCH_ATTR, False)):
        return current

    @wraps(current)
    def on_order_rejected_v232(
        self: Any,
        request: Any,
        error: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if _is_local_quality_gate_error(error):
            LOGGER.info(
                "HEARTBEAT_EXECUTION_QUALITY_V232_LOCAL_BLOCK marker=%s strategy=%s "
                "symbol=%s reason=%s local_pre_dispatch=true exchange_request_sent=false "
                "exchange_rejection_recorded=false ecel_failure_raised=false "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
                str(getattr(request, "strategy", "")),
                str(getattr(request, "symbol", "unknown")),
                str(error or ""),
            )
            # The caller already owns a PipelineResult(success=False).  Returning
            # here preserves the local block without claiming an exchange reject.
            return None
        return current(self, request, error, *args, **kwargs)

    setattr(on_order_rejected_v232, _REJECT_PATCH_ATTR, True)
    setattr(on_order_rejected_v232, "__wrapped__", current)
    return on_order_rejected_v232


def _patch_router() -> bool:
    try:
        module = importlib.import_module("bot.multi_broker_execution_router")
    except Exception as exc:
        LOGGER.critical(
            "HEARTBEAT_EXECUTION_QUALITY_V232_ROUTER_IMPORT_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "route", None)
    if not callable(current):
        return False
    if not bool(getattr(current, _ROUTE_PATCH_ATTR, False)):
        cls.route = _wrap_router_route(current)
    installed = getattr(cls, "route", None)
    return bool(callable(installed) and getattr(installed, _ROUTE_PATCH_ATTR, False))


def _patch_execution_pipeline() -> bool:
    try:
        module = importlib.import_module("bot.execution_pipeline")
    except Exception as exc:
        LOGGER.critical(
            "HEARTBEAT_EXECUTION_QUALITY_V232_PIPELINE_IMPORT_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_on_order_rejected", None)
    if not callable(current):
        return False
    if not bool(getattr(current, _REJECT_PATCH_ATTR, False)):
        cls._on_order_rejected = _wrap_order_rejected(current)
    installed = getattr(cls, "_on_order_rejected", None)
    return bool(callable(installed) and getattr(installed, _REJECT_PATCH_ATTR, False))


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    except Exception:
        return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["heartbeat_execution_quality_v232"] = _READY_FLAG
    return True


def install() -> bool:
    with _LOCK:
        router_ready = _patch_router()
        pipeline_ready = _patch_execution_pipeline()
        manifest_ready = _patch_release_manifest()
        ready = bool(router_ready and pipeline_ready and manifest_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "HEARTBEAT_EXECUTION_QUALITY_V232_FAILED marker=%s router=%s pipeline=%s "
                "manifest=%s trading_fail_closed=true",
                MARKER,
                str(router_ready).lower(),
                str(pipeline_ready).lower(),
                str(manifest_ready).lower(),
            )
            return False
        LOGGER.critical(
            "HEARTBEAT_EXECUTION_QUALITY_V232_READY marker=%s ready=true "
            "heartbeat_native_urgency_defer_override=true quality_reject_preserved=true "
            "local_quality_blocks_excluded_from_exchange_rejections=true "
            "ordinary_orders_unchanged=true ecel_risk_writer_nonce_capital_broker_health_unchanged=true "
            "execution_proof_fabricated=false forced_trade=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_is_heartbeat_strategy",
    "_is_local_quality_gate_error",
    "_wrap_router_route",
    "_wrap_order_rejected",
]
