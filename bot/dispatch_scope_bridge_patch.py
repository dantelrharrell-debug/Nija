from __future__ import annotations

import importlib
import inspect
import logging
import os
import threading
import time
from types import SimpleNamespace
from typing import Any, Optional, Dict

logger = logging.getLogger("nija.dispatch_scope_bridge_patch")

_PATCHED = False
_PATCH_LOCK = threading.Lock()
_MARKER = "20260704e"

_ALLOWED_STACK_FILES = {
    "execution_pipeline.py",
    "multi_broker_execution_router.py",
    "execution_engine.py",
    "execution_state_controller.py",
    "usdt_kraken_ecel_routing_repair_patch.py",
    "coinbase_execution_failover_patch.py",
    "live_entry_runtime_fixes.py",
    "live_entry_completion_repair_patch.py",
    "decision_pipeline_runtime_patch.py",
}


def _env_truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "enabled", "on"}


def _in_canonical_execution_stack() -> bool:
    try:
        for frame in inspect.stack(context=0):
            filename = str(getattr(frame, "filename", "") or "").rsplit("/", 1)[-1]
            if filename in _ALLOWED_STACK_FILES:
                return True
    except Exception:
        return False
    return False


def _decision_gates(decision: Any) -> Dict[str, Any]:
    gates = getattr(decision, "gates", None)
    if isinstance(gates, dict):
        return gates
    try:
        gates = (getattr(decision, "__dict__", {}) or {}).get("gates")
        if isinstance(gates, dict):
            return gates
    except Exception:
        pass
    return {}


def _gate_bool(decision: Any, dotted_name: str, attr_name: str) -> bool:
    gates = _decision_gates(decision)
    if dotted_name in gates:
        return bool(gates.get(dotted_name))
    if attr_name in gates:
        return bool(gates.get(attr_name))
    return bool(getattr(decision, attr_name, False))


def _decision_first_failed(decision: Any) -> str:
    return str(
        getattr(decision, "first_failed_gate", "")
        or getattr(decision, "reason_detail", "")
        or getattr(decision, "reason_code", "")
        or getattr(decision, "reason", "")
        or ""
    ).strip()


def _decision_reason_code(decision: Any) -> str:
    return str(
        getattr(decision, "reason_code", "")
        or getattr(decision, "reason", "")
        or getattr(decision, "reason_detail", "")
        or ""
    ).strip()


def _dispatch_scope_only_block(decision: Any) -> bool:
    if decision is None:
        return False
    failed = _decision_first_failed(decision).lower()
    reason_code = _decision_reason_code(decision).lower()
    gates = _decision_gates(decision)
    dispatch_gate_present = "dispatch.enabled" in gates
    dispatch_enabled = bool(gates.get("dispatch.enabled", getattr(decision, "dispatch_enabled", False)))
    scope_gap = (
        "dispatch.enabled" in failed
        or "dispatch_scope_missing" in failed
        or "dispatch.enabled" in reason_code
        or "dispatch_scope_missing" in reason_code
        or (dispatch_gate_present and not dispatch_enabled)
    )
    if not scope_gap:
        return False

    lifecycle = str(getattr(decision, "lifecycle_phase", "") or "").strip().upper()
    return bool(
        _env_truthy("LIVE_CAPITAL_VERIFIED")
        and not _env_truthy("DRY_RUN_MODE")
        and not _env_truthy("PAPER_MODE")
        and str(os.getenv("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper() == "LIVE_ACTIVE"
        and _env_truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY")
        and _gate_bool(decision, "state.live_active", "state_live_active")
        and _gate_bool(decision, "lease.valid", "lease_valid")
        and _gate_bool(decision, "lease.generation_current", "lease_generation_current")
        and _gate_bool(decision, "nonce.authority", "nonce_ready")
        and _gate_bool(decision, "heartbeat.fresh", "heartbeat_fresh")
        and _gate_bool(decision, "heartbeat.stage_sufficient", "heartbeat_stage_sufficient")
        and _gate_bool(decision, "broker.health_ok", "broker_health_ok")
        and _gate_bool(decision, "circuit_breaker.closed", "circuit_breaker_closed")
        and lifecycle == "LIVE"
    )


def _allowed_decision_proxy(decision: Any) -> Any:
    try:
        data = dict(getattr(decision, "__dict__", {}) or {})
    except Exception:
        data = {}
    data.update({
        "allowed": True,
        "allow": True,
        "decision": "ALLOW",
        "reason": "dispatch_scope_bridged",
        "reason_code": "dispatch_scope_bridged",
        "reason_detail": "dispatch_scope_bridged",
        "first_failed_gate": "",
        "original_decision": decision,
    })
    return SimpleNamespace(**data)


def _emit_dispatch_scope_trace(
    *,
    broker_name: str,
    symbol: str,
    side: str,
    size: float,
    decision: Any,
    emit_trace: Any,
    terminal_surface: str,
) -> None:
    if callable(emit_trace):
        try:
            emit_trace(
                _allowed_decision_proxy(decision),
                symbol=symbol,
                side=side,
                size=size,
                terminal_surface=terminal_surface,
                block_reason_code="dispatch_scope_bridged",
                block_reason_detail="dispatch_scope_bridged",
                first_failed_gate="",
            )
        except Exception:
            pass
    logger.critical(
        "DISPATCH_SCOPE_BRIDGE_APPLIED marker=%s broker=%s symbol=%s side=%s size=%s terminal_surface=%s",
        _MARKER,
        broker_name,
        symbol,
        side,
        size,
        terminal_surface,
    )
    print(
        f"[NIJA-PRINT] DISPATCH_SCOPE_BRIDGE_APPLIED marker={_MARKER} | broker={broker_name} symbol={symbol} side={side} size={size} terminal_surface={terminal_surface}",
        flush=True,
    )


def _patch_can_execute_for_module(module: Any, surface: str) -> bool:
    original = getattr(module, "can_execute", None)
    if not callable(original) or getattr(original, "_nija_dispatch_scope_bridge_can_execute_v20260704e", False):
        return False

    def _patched_can_execute(*args: Any, **kwargs: Any) -> Any:
        decision = original(*args, **kwargs)
        if (
            decision is not None
            and not bool(getattr(decision, "allowed", getattr(decision, "allow", False)))
            and _dispatch_scope_only_block(decision)
            and _in_canonical_execution_stack()
        ):
            logger.critical(
                "DISPATCH_SCOPE_BRIDGE_CAN_EXECUTE_APPLIED marker=%s module=%s surface=%s",
                _MARKER,
                getattr(module, "__name__", module),
                surface,
            )
            print(
                f"[NIJA-PRINT] DISPATCH_SCOPE_BRIDGE_CAN_EXECUTE_APPLIED marker={_MARKER} | module={getattr(module, '__name__', module)} surface={surface}",
                flush=True,
            )
            return _allowed_decision_proxy(decision)
        return decision

    setattr(_patched_can_execute, "_nija_dispatch_scope_bridge_can_execute_v20260704e", True)
    setattr(_patched_can_execute, "_nija_original", original)
    setattr(module, "can_execute", _patched_can_execute)
    logger.warning("DISPATCH_SCOPE_BRIDGE_PATCHED marker=%s module=%s surface=%s.can_execute", _MARKER, getattr(module, "__name__", module), surface)
    print(f"[NIJA-PRINT] DISPATCH_SCOPE_BRIDGE_PATCHED marker={_MARKER} | module={getattr(module, '__name__', module)} surface={surface}.can_execute", flush=True)
    return True


def _patch_broker_integration_module(module: Any) -> bool:
    patched_any = _patch_can_execute_for_module(module, "broker_integration")
    original = getattr(module, "_reject_if_unauthorized_order_submit", None)
    if not callable(original) or getattr(original, "_nija_dispatch_scope_bridge_v20260704e", False):
        return patched_any

    can_execute = getattr(module, "can_execute", None)
    can_execute_startup_probe = getattr(module, "can_execute_startup_probe", None)
    emit_trace = getattr(module, "emit_pretrade_execution_validator_trace", None)
    ExecutionBlocked = getattr(module, "ExecutionBlocked", RuntimeError)

    def _patched_reject_if_unauthorized_order_submit(
        broker_name: str,
        symbol: str,
        side: str,
        size: float,
    ) -> Optional[Dict[str, Any]]:
        decision = can_execute() if callable(can_execute) else None
        if decision is not None and bool(getattr(decision, "allowed", getattr(decision, "allow", False))):
            if callable(emit_trace):
                try:
                    emit_trace(decision, symbol=symbol, side=side, size=size, terminal_surface="broker_integration")
                except Exception:
                    pass
            return None

        if decision is not None and _dispatch_scope_only_block(decision) and _in_canonical_execution_stack():
            _emit_dispatch_scope_trace(
                broker_name=broker_name,
                symbol=symbol,
                side=side,
                size=size,
                decision=decision,
                emit_trace=emit_trace,
                terminal_surface="broker_integration_dispatch_scope_bridge",
            )
            return None

        if callable(can_execute_startup_probe):
            try:
                probe_allowed, probe_reason = can_execute_startup_probe()
            except Exception:
                probe_allowed, probe_reason = False, "startup_probe_error"
            if probe_allowed:
                if callable(emit_trace) and decision is not None:
                    try:
                        emit_trace(decision, symbol=symbol, side=side, size=size, terminal_surface="broker_integration_startup_probe")
                    except Exception:
                        pass
                logger.warning(
                    "Startup execution probe authorized before LIVE_ACTIVE (broker=%s symbol=%s side=%s size=%s reason=%s)",
                    broker_name,
                    symbol,
                    side,
                    size,
                    probe_reason,
                )
                return None

        if decision is not None and callable(emit_trace):
            try:
                emit_trace(decision, symbol=symbol, side=side, size=size, terminal_surface="broker_integration")
            except Exception:
                pass
        reason = str(getattr(decision, "reason", "execution_authority_violation") if decision is not None else "execution_authority_unavailable")
        logger.critical(
            "Execution authority violation: order path stopped | broker=%s symbol=%s side=%s size=%s reason=%s",
            broker_name,
            symbol,
            side,
            size,
            reason,
        )
        raise ExecutionBlocked(f"FATAL: Execution authority violation ({reason})")

    setattr(_patched_reject_if_unauthorized_order_submit, "_nija_dispatch_scope_bridge_v20260704e", True)
    setattr(_patched_reject_if_unauthorized_order_submit, "_nija_original", original)
    setattr(module, "_reject_if_unauthorized_order_submit", _patched_reject_if_unauthorized_order_submit)
    logger.warning("DISPATCH_SCOPE_BRIDGE_PATCHED marker=%s module=%s surface=broker_integration.reject", _MARKER, getattr(module, "__name__", module))
    print(f"[NIJA-PRINT] DISPATCH_SCOPE_BRIDGE_PATCHED marker={_MARKER} | module={getattr(module, '__name__', module)} surface=broker_integration.reject", flush=True)
    return True


def _patch_broker_manager_module(module: Any) -> bool:
    return _patch_can_execute_for_module(module, "broker_manager")


def _patch_live_broker_adapters_module(module: Any) -> bool:
    patched_any = _patch_can_execute_for_module(module, "live_broker_adapters")
    original = getattr(module, "_authority_blocked", None)
    if not callable(original) or getattr(original, "_nija_dispatch_scope_bridge_v20260704e", False):
        return patched_any

    can_execute = getattr(module, "can_execute", None)
    can_execute_startup_probe = getattr(module, "can_execute_startup_probe", None)
    emit_trace = getattr(module, "emit_pretrade_execution_validator_trace", None)

    def _patched_authority_blocked(broker_name: str, symbol: str, side: str, size: float) -> Optional[Dict[str, Any]]:
        decision = can_execute() if callable(can_execute) else None
        if decision is not None and bool(getattr(decision, "allowed", getattr(decision, "allow", False))):
            if callable(emit_trace):
                try:
                    emit_trace(decision, symbol=symbol, side=side, size=size, terminal_surface="live_broker_adapter")
                except Exception:
                    pass
            return None

        if decision is not None and _dispatch_scope_only_block(decision) and _in_canonical_execution_stack():
            _emit_dispatch_scope_trace(
                broker_name=broker_name,
                symbol=symbol,
                side=side,
                size=size,
                decision=decision,
                emit_trace=emit_trace,
                terminal_surface="live_broker_adapter_dispatch_scope_bridge",
            )
            return None

        if callable(can_execute_startup_probe):
            try:
                probe_allowed, probe_reason = can_execute_startup_probe()
            except Exception:
                probe_allowed, probe_reason = False, "startup_probe_error"
            if probe_allowed:
                return None

        reason = str(getattr(decision, "reason", "execution_authority_unavailable") if decision is not None else "execution_authority_unavailable")
        logger.error("[Authority] blocked broker=%s symbol=%s side=%s size=%s reason=%s", broker_name, symbol, side, size, reason)
        return {"status": "ERROR", "error": f"Execution blocked: {reason}", "broker": broker_name}

    setattr(_patched_authority_blocked, "_nija_dispatch_scope_bridge_v20260704e", True)
    setattr(_patched_authority_blocked, "_nija_original", original)
    setattr(module, "_authority_blocked", _patched_authority_blocked)
    logger.warning("DISPATCH_SCOPE_BRIDGE_PATCHED marker=%s module=%s surface=live_broker_adapters.authority", _MARKER, getattr(module, "__name__", module))
    print(f"[NIJA-PRINT] DISPATCH_SCOPE_BRIDGE_PATCHED marker={_MARKER} | module={getattr(module, '__name__', module)} surface=live_broker_adapters.authority", flush=True)
    return True


def _try_patch_once() -> bool:
    patched_any = False
    for name in ("bot.broker_manager", "broker_manager"):
        try:
            patched_any = _patch_broker_manager_module(importlib.import_module(name)) or patched_any
        except Exception as exc:
            logger.debug("dispatch scope bridge broker-manager patch deferred for %s: %s", name, exc)
    for name in ("bot.broker_integration", "broker_integration"):
        try:
            patched_any = _patch_broker_integration_module(importlib.import_module(name)) or patched_any
        except Exception as exc:
            logger.debug("dispatch scope bridge broker-integration patch deferred for %s: %s", name, exc)
    for name in ("bot.live_broker_adapters", "live_broker_adapters"):
        try:
            patched_any = _patch_live_broker_adapters_module(importlib.import_module(name)) or patched_any
        except Exception as exc:
            logger.debug("dispatch scope bridge live-adapter patch deferred for %s: %s", name, exc)
    return patched_any


def _monitor_patch() -> None:
    deadline = time.monotonic() + 180.0
    while time.monotonic() < deadline:
        if _try_patch_once():
            return
        time.sleep(0.5)
    logger.warning("DISPATCH_SCOPE_BRIDGE_MONITOR_EXPIRED marker=%s", _MARKER)


def install_import_hook() -> None:
    global _PATCHED
    with _PATCH_LOCK:
        if _PATCHED:
            return
        _PATCHED = True
    _try_patch_once()
    thread = threading.Thread(target=_monitor_patch, name="dispatch-scope-bridge-patch", daemon=True)
    thread.start()
    logger.warning("DISPATCH_SCOPE_BRIDGE_INSTALL_COMPLETE marker=%s", _MARKER)
