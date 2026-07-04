from __future__ import annotations

import importlib
import inspect
import logging
import os
import threading
import time
from typing import Any, Optional, Dict

logger = logging.getLogger("nija.dispatch_scope_bridge_patch")

_PATCHED = False
_PATCH_LOCK = threading.Lock()
_MARKER = "20260704d"

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


def _decision_first_failed(decision: Any) -> str:
    return str(
        getattr(decision, "first_failed_gate", "")
        or getattr(decision, "reason_detail", "")
        or getattr(decision, "reason", "")
        or ""
    ).strip()


def _dispatch_scope_only_block(decision: Any) -> bool:
    """True when the only actionable failure is the broker-layer scope marker.

    The authority gate order evaluates ``dispatch.enabled`` before
    ``stability.allowed``.  When the broker adapter is called from the canonical
    execution stack but through a duplicate import path, ``has_execution_authority``
    can be false at the broker layer even though live state, lease, nonce,
    heartbeat, broker health, and circuit gates are already valid.  That should
    be repaired as a scope bridge, not treated as a broker rejection.

    This intentionally does not bypass lifecycle, writer lease, generation,
    nonce, heartbeat, broker health, circuit breaker, dry-run/paper, or
    LIVE_CAPITAL_VERIFIED gates.
    """
    failed = _decision_first_failed(decision).lower()
    if "dispatch.enabled" not in failed and "dispatch_scope_missing" not in failed:
        return False

    return bool(
        _env_truthy("LIVE_CAPITAL_VERIFIED")
        and not _env_truthy("DRY_RUN_MODE")
        and not _env_truthy("PAPER_MODE")
        and str(os.getenv("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper() == "LIVE_ACTIVE"
        and _env_truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY")
        and bool(getattr(decision, "state_live_active", False))
        and bool(getattr(decision, "lease_valid", False))
        and bool(getattr(decision, "lease_generation_current", False))
        and bool(getattr(decision, "nonce_ready", False))
        and bool(getattr(decision, "heartbeat_fresh", False))
        and bool(getattr(decision, "heartbeat_stage_sufficient", False))
        and bool(getattr(decision, "broker_health_ok", False))
        and bool(getattr(decision, "circuit_breaker_closed", False))
        and str(getattr(decision, "lifecycle_phase", "")).upper() == "LIVE"
    )


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
                decision,
                symbol=symbol,
                side=side,
                size=size,
                terminal_surface=terminal_surface,
                block_reason_code="dispatch_scope_bridged",
                block_reason_detail="dispatch.enabled:bridged_by_canonical_execution_stack",
                first_failed_gate="dispatch.enabled",
            )
        except Exception:
            pass
    logger.critical(
        "DISPATCH_SCOPE_BRIDGE_APPLIED marker=%s broker=%s symbol=%s side=%s size=%s reason=%s",
        _MARKER,
        broker_name,
        symbol,
        side,
        size,
        _decision_first_failed(decision),
    )
    print(
        f"[NIJA-PRINT] DISPATCH_SCOPE_BRIDGE_APPLIED marker={_MARKER} | broker={broker_name} symbol={symbol} side={side} size={size}",
        flush=True,
    )


def _patch_broker_integration_module(module: Any) -> bool:
    original = getattr(module, "_reject_if_unauthorized_order_submit", None)
    if not callable(original) or getattr(original, "_nija_dispatch_scope_bridge_v20260704d", False):
        return False

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
        if decision is not None and bool(getattr(decision, "allowed", False)):
            if callable(emit_trace):
                try:
                    emit_trace(
                        decision,
                        symbol=symbol,
                        side=side,
                        size=size,
                        terminal_surface="broker_integration",
                    )
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
                        emit_trace(
                            decision,
                            symbol=symbol,
                            side=side,
                            size=size,
                            terminal_surface="broker_integration_startup_probe",
                        )
                    except Exception:
                        pass
                logger.warning(
                    "Startup execution probe authorized before LIVE_ACTIVE "
                    "(broker=%s symbol=%s side=%s size=%s reason=%s)",
                    broker_name,
                    symbol,
                    side,
                    size,
                    probe_reason,
                )
                return None

        if decision is not None and callable(emit_trace):
            try:
                emit_trace(
                    decision,
                    symbol=symbol,
                    side=side,
                    size=size,
                    terminal_surface="broker_integration",
                )
            except Exception:
                pass
        reason = str(getattr(decision, "reason", "execution_authority_violation") if decision is not None else "execution_authority_unavailable")
        logger.critical(
            "🔒 Execution authority violation: order submission blocked "
            "| broker=%s symbol=%s side=%s size=%s reason=%s",
            broker_name,
            symbol,
            side,
            size,
            reason,
        )
        raise ExecutionBlocked(f"FATAL: Execution authority violation ({reason})")

    setattr(_patched_reject_if_unauthorized_order_submit, "_nija_dispatch_scope_bridge_v20260704d", True)
    setattr(_patched_reject_if_unauthorized_order_submit, "_nija_original", original)
    setattr(module, "_reject_if_unauthorized_order_submit", _patched_reject_if_unauthorized_order_submit)
    logger.warning("DISPATCH_SCOPE_BRIDGE_PATCHED marker=%s module=%s surface=broker_integration", _MARKER, getattr(module, "__name__", module))
    print(f"[NIJA-PRINT] DISPATCH_SCOPE_BRIDGE_PATCHED marker={_MARKER} | module={getattr(module, '__name__', module)} surface=broker_integration", flush=True)
    return True


def _patch_live_broker_adapters_module(module: Any) -> bool:
    original = getattr(module, "_authority_blocked", None)
    if not callable(original) or getattr(original, "_nija_dispatch_scope_bridge_v20260704d", False):
        return False

    can_execute = getattr(module, "can_execute", None)
    can_execute_startup_probe = getattr(module, "can_execute_startup_probe", None)
    emit_trace = getattr(module, "emit_pretrade_execution_validator_trace", None)

    def _patched_authority_blocked(broker_name: str, symbol: str, side: str, size: float) -> Optional[Dict[str, Any]]:
        decision = can_execute() if callable(can_execute) else None
        if decision is not None and bool(getattr(decision, "allowed", False)):
            if callable(emit_trace):
                try:
                    emit_trace(
                        decision,
                        symbol=symbol,
                        side=side,
                        size=size,
                        terminal_surface="live_broker_adapter",
                    )
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
                if callable(emit_trace) and decision is not None:
                    try:
                        emit_trace(
                            decision,
                            symbol=symbol,
                            side=side,
                            size=size,
                            terminal_surface="live_broker_adapter_startup_probe",
                        )
                    except Exception:
                        pass
                logger.warning(
                    "[Authority] startup probe authorized broker=%s symbol=%s side=%s size=%s reason=%s",
                    broker_name,
                    symbol,
                    side,
                    size,
                    probe_reason,
                )
                return None

        if decision is not None and callable(emit_trace):
            try:
                emit_trace(
                    decision,
                    symbol=symbol,
                    side=side,
                    size=size,
                    terminal_surface="live_broker_adapter",
                )
            except Exception:
                pass
        reason = str(getattr(decision, "reason", "execution_authority_unavailable") if decision is not None else "execution_authority_unavailable")
        logger.error(
            "[Authority] blocked broker=%s symbol=%s side=%s size=%s reason=%s",
            broker_name,
            symbol,
            side,
            size,
            reason,
        )
        return {
            "status": "ERROR",
            "error": f"Execution blocked: {reason}",
            "broker": broker_name,
        }

    setattr(_patched_authority_blocked, "_nija_dispatch_scope_bridge_v20260704d", True)
    setattr(_patched_authority_blocked, "_nija_original", original)
    setattr(module, "_authority_blocked", _patched_authority_blocked)
    logger.warning("DISPATCH_SCOPE_BRIDGE_PATCHED marker=%s module=%s surface=live_broker_adapters", _MARKER, getattr(module, "__name__", module))
    print(f"[NIJA-PRINT] DISPATCH_SCOPE_BRIDGE_PATCHED marker={_MARKER} | module={getattr(module, '__name__', module)} surface=live_broker_adapters", flush=True)
    return True


def _try_patch_once() -> bool:
    patched_any = False
    for name in ("bot.broker_integration", "broker_integration"):
        try:
            module = importlib.import_module(name)
            patched_any = _patch_broker_integration_module(module) or patched_any
        except Exception as exc:
            logger.debug("dispatch scope bridge patch deferred for %s: %s", name, exc)
    for name in ("bot.live_broker_adapters", "live_broker_adapters"):
        try:
            module = importlib.import_module(name)
            patched_any = _patch_live_broker_adapters_module(module) or patched_any
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
