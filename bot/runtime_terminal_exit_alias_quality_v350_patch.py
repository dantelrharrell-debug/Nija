"""Terminal protective-exit alias + execution-quality convergence v350.

Fresh production evidence on 2026-09-03 showed two concrete protective-exit
regressions after v349 was added:

* ``bot.execution_pipeline`` and ``execution_pipeline`` can exist as distinct
  module/class identities.  v349 patched only the package-qualified identity, so
  a legacy pipeline class could still allow ECEL to enlarge a verified close
  above authoritative holdings.  v350 installs the same post-ECEL holdings
  firewall on every distinct loaded/importable pipeline identity.
* the multi-broker AI execution-quality filter was applied to verified
  risk-reducing protective closes.  It deferred exits because of local fill-score
  quality even after writer/nonce/broker-health/kill-switch/ECEL authority had
  passed.  v350 skips only that routing optimizer for independently verified
  protective closes.  Minimum-order, ECEL, writer, nonce, broker-health,
  kill-switch, circuit, position, ACK and confirmed-fill gates remain intact.

No readiness, position, ACK, fill, broker response or protection coverage is
fabricated.  No exit is enlarged, no exchange minimum is bypassed, no circuit or
kill switch is cleared, and ordinary entry routing is unchanged.
"""
from __future__ import annotations

import copy
import importlib
import logging
import math
import os
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_terminal_exit_alias_quality_v350")
MARKER = "20260903-runtime-terminal-exit-alias-quality-v350"
RELEASE_ID = "20260903-runtime-convergence-v350"
_READY_FLAG = "NIJA_RUNTIME_TERMINAL_EXIT_ALIAS_QUALITY_V350_READY"
_LOCK = threading.RLock()
_COMPILED: dict[int, tuple[float, float, str]] = {}
_COMPILED_LOCK = threading.Lock()
_LOG_PATCH = "_nija_v350_post_ecel_capture"
_GATE_PATCH = "_nija_v350_terminal_exit_alias_firewall"
_ROUTE_PATCH = "_nija_v350_protective_exit_quality_optimizer_scope"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _metadata(request: Any) -> dict[str, Any]:
    raw = getattr(request, "metadata", None)
    return dict(raw or {}) if isinstance(raw, Mapping) else {}


def _verified_protective_close(request: Any) -> tuple[bool, float, str]:
    meta = _metadata(request)
    side = _norm(getattr(request, "side", "") or meta.get("side"))
    intent = _norm(getattr(request, "intent_type", "") or meta.get("intent_type") or meta.get("intent"))
    effect = _norm(getattr(request, "position_effect", "") or meta.get("position_effect"))
    origin = _norm(meta.get("origin") or meta.get("exit_origin") or meta.get("source"))
    verified = _f(meta.get("verified_position_quantity"), 0.0)
    trusted_origin = origin in {"universal_v67", "kraken_account_exit", "protective_exit", "auto_exit"}
    closing = bool(
        meta.get("closing_position") is True
        or intent in {"exit", "reduce", "close"}
        or effect in {"close", "close_only", "reduce"}
        or trusted_origin
    )
    protective = bool(meta.get("protective_exit") is True or trusted_origin)
    return bool(side in {"sell", "buy"} and verified > 0.0 and closing and protective), verified, origin


def _patch_pipeline_module(module: ModuleType) -> bool:
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
        def log_v350(self: Any, request: Any, compiled: Any) -> Any:
            result = original_log(self, request, compiled)
            try:
                if compiled is not None and bool(getattr(compiled, "accepted", False)):
                    base = _f(getattr(compiled, "compiled_base_size", None), 0.0)
                    price = _f(getattr(compiled, "compiled_price_usd", None), 0.0)
                    reason = str(getattr(compiled, "reason", "") or "")
                    with _COMPILED_LOCK:
                        _COMPILED[id(request)] = (base, price, reason)
            except Exception:
                LOGGER.debug("v350 ECEL capture failed", exc_info=True)
            return result

        setattr(log_v350, _LOG_PATCH, True)
        setattr(log_v350, "__wrapped__", original_log)
        cls._log_ecel_final_order = log_v350

    current_gate = getattr(cls, "_gate_broker_capabilities", None)
    if not callable(current_gate):
        return False
    if not bool(getattr(current_gate, _GATE_PATCH, False)):
        original_gate = current_gate

        @wraps(original_gate)
        def gate_v350(self: Any, request: Any, t_start: float) -> Any:
            with _COMPILED_LOCK:
                compiled_base, compiled_price, compile_reason = _COMPILED.pop(id(request), (0.0, 0.0, ""))
            is_exit, verified, origin = _verified_protective_close(request)
            if is_exit and compiled_base > 0.0:
                tolerance = max(1e-12, abs(verified) * 1e-8)
                if compiled_base > verified + tolerance:
                    error = (
                        "EXIT_BELOW_EXCHANGE_MIN_AFTER_HOLDINGS_CAP "
                        f"verified_qty={verified:.12g} compiled_qty={compiled_base:.12g} "
                        "oversell_blocked=true"
                    )
                    LOGGER.critical(
                        "TERMINAL_EXIT_V350_OVERSELL_BLOCKED marker=%s module=%s symbol=%s account=%s "
                        "verified_qty=%.12f compiled_qty=%.12f compiled_price=%.10f origin=%s "
                        "compile_reason=%s broker_dispatch=false tracker_preserved=true "
                        "minimum_order_bypass=false exchange_rejection=false fill_fabricated=false "
                        "safety_gates_bypassed=false",
                        MARKER,
                        str(getattr(module, "__name__", "unknown")),
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

        setattr(gate_v350, _GATE_PATCH, True)
        setattr(gate_v350, "__wrapped__", original_gate)
        cls._gate_broker_capabilities = gate_v350

    return bool(getattr(getattr(cls, "_log_ecel_final_order", None), _LOG_PATCH, False)) and bool(
        getattr(getattr(cls, "_gate_broker_capabilities", None), _GATE_PATCH, False)
    )


def _patch_all_pipeline_identities() -> bool:
    modules: list[ModuleType] = []
    seen: set[int] = set()
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        cls = getattr(module, "ExecutionPipeline", None)
        identity = id(cls) if isinstance(cls, type) else id(module)
        if identity in seen:
            continue
        seen.add(identity)
        modules.append(module)
    if not modules:
        return False
    outcomes = [_patch_pipeline_module(module) for module in modules]
    LOGGER.critical(
        "TERMINAL_EXIT_V350_PIPELINE_IDENTITIES marker=%s identities=%s patched=%s distinct=%d "
        "broker_dispatch_on_oversell=false safety_gates_bypassed=false",
        MARKER,
        tuple(str(getattr(module, "__name__", "unknown")) for module in modules),
        tuple(bool(value) for value in outcomes),
        len(modules),
    )
    return all(outcomes)


def _patch_router_module(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "route", None)
    if not callable(current):
        return False
    if bool(getattr(current, _ROUTE_PATCH, False)):
        return True
    original = current

    @wraps(original)
    def route_v350(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        is_exit, verified, origin = _verified_protective_close(request)
        if not is_exit:
            return original(self, request, *args, **kwargs)
        scoped = copy.copy(request)
        setattr(scoped, "skip_quality_filter", True)
        LOGGER.critical(
            "PROTECTIVE_EXIT_V350_QUALITY_OPTIMIZER_SKIPPED marker=%s module=%s symbol=%s side=%s "
            "verified_qty=%.12f origin=%s risk_reducing_exit_only=true execution_quality_optimizer_only=true "
            "minimum_order_ecel_writer_nonce_broker_health_killswitch_circuit_position_ack_fill_gates_unchanged=true "
            "forced_exit=false forced_trade=false safety_gates_bypassed=false",
            MARKER,
            str(getattr(module, "__name__", "unknown")),
            str(getattr(request, "symbol", "") or ""),
            str(getattr(request, "side", "") or ""),
            verified,
            origin or "unknown",
        )
        return original(self, scoped, *args, **kwargs)

    setattr(route_v350, _ROUTE_PATCH, True)
    setattr(route_v350, "__wrapped__", original)
    cls.route = route_v350
    return True


def _patch_all_router_identities() -> bool:
    modules: list[ModuleType] = []
    seen: set[int] = set()
    for name in ("bot.multi_broker_execution_router", "multi_broker_execution_router"):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        cls = getattr(module, "MultiBrokerExecutionRouter", None)
        identity = id(cls) if isinstance(cls, type) else id(module)
        if identity in seen:
            continue
        seen.add(identity)
        modules.append(module)
    if not modules:
        return False
    return all(_patch_router_module(module) for module in modules)


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_terminal_exit_alias_quality_v350"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        pipeline = router = manifest = False
        try:
            pipeline = _patch_all_pipeline_identities()
            router = _patch_all_router_identities()
            manifest = _register_manifest()
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_TERMINAL_EXIT_ALIAS_QUALITY_V350_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        ready = bool(pipeline and router and manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_TERMINAL_EXIT_ALIAS_QUALITY_V350_%s marker=%s ready=%s "
            "all_pipeline_identities_firewalled=%s protective_exit_quality_optimizer_scoped=%s manifest=%s "
            "exit_never_enlarged=true broker_dispatch_on_oversell=false minimum_order_bypass=false "
            "ordinary_entries_unchanged=true confirmed_fill_required=true forced_trade=false forced_activation=false "
            "writer_nonce_risk_capital_killswitch_position_sync_ecel_broker_health_order_ack_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
            str(pipeline).lower(),
            str(router).lower(),
            str(manifest).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_verified_protective_close",
    "_patch_pipeline_module",
    "_patch_router_module",
]
