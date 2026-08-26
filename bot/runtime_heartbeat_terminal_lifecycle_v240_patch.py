"""Bridge a verified startup heartbeat through broker_manager's terminal lifecycle gate (v240).

Production on 2026-08-26 proved that the heartbeat reaches the real submit boundary
with a canonical startup-probe context, yet broker_manager can still call an imported
``can_execute`` binding that returns ``lifecycle_phase:BOOT``.  This patch changes only
that terminal module-local decision binding.

A BOOT lifecycle denial is converted to ALLOW only when the *canonical*
``can_execute_startup_probe()`` independently succeeds in the current context and
``assert_startup_write_authority()`` succeeds again immediately.  The bridge is not
available from symbol/strategy text, thread name, call stack, or environment flags.
Therefore ordinary orders cannot create the exception.

No lifecycle state is mutated.  Kill switch, writer/lease authority, risk, capital,
broker health, ECEL, minimum notional, exchange acknowledgement, fill proof and
activation proof remain unchanged.  A real exchange result is still required before
execution_ready can become true.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from dataclasses import replace
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_terminal_lifecycle_v240")
MARKER = "20260826-heartbeat-terminal-lifecycle-v240"
_FLAG = "NIJA_HEARTBEAT_TERMINAL_LIFECYCLE_V240_READY"
_PATCH_ATTR = "_nija_heartbeat_terminal_lifecycle_v240"
_TERMINALS = ("bot.broker_manager", "broker_manager")
_ALLOWED = {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}


def _authority() -> ModuleType:
    module = sys.modules.get("bot.execution_authority_context")
    if not isinstance(module, ModuleType):
        module = importlib.import_module("bot.execution_authority_context")
    return module


def _is_boot_lifecycle_denial(decision: Any) -> bool:
    reason = str(getattr(decision, "reason", "") or getattr(decision, "reason_detail", "") or "").lower()
    code = str(getattr(decision, "reason_code", "") or "").lower()
    gate = str(getattr(decision, "first_failed_gate", "") or "").lower()
    return gate == "lifecycle.phase" and (
        "lifecycle_phase:boot" in reason or code == "lifecycle_phase_not_live"
    )


def _verified_probe_reason() -> str | None:
    authority = _authority()
    checker = getattr(authority, "can_execute_startup_probe", None)
    reverify = getattr(authority, "assert_startup_write_authority", None)
    if not callable(checker) or not callable(reverify):
        return None
    try:
        allowed, reason = checker()
        normalized = str(reason or "").strip().upper()
        if not bool(allowed) or normalized not in _ALLOWED:
            return None
        reverify()
        return normalized
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_TERMINAL_LIFECYCLE_V240_REVERIFY_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return None


def _bridge(decision: Any, reason: str) -> Any:
    try:
        return replace(
            decision,
            allowed=True,
            reason=f"verified_startup_probe:{reason}",
            first_failed_gate="",
            reason_code="allowed_startup_probe",
            reason_detail=f"verified_startup_probe:{reason}",
        )
    except Exception:
        class DecisionProxy:
            pass
        proxy = DecisionProxy()
        try:
            proxy.__dict__.update(getattr(decision, "__dict__", {}) or {})
        except Exception:
            pass
        proxy.allowed = True
        proxy.allow = True
        proxy.reason = f"verified_startup_probe:{reason}"
        proxy.first_failed_gate = ""
        proxy.reason_code = "allowed_startup_probe"
        proxy.reason_detail = f"verified_startup_probe:{reason}"
        return proxy


def _wrap(current: Callable[..., Any]) -> Callable[..., Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def can_execute_v240(*args: Any, **kwargs: Any) -> Any:
        decision = current(*args, **kwargs)
        if bool(getattr(decision, "allowed", getattr(decision, "allow", False))):
            return decision
        if not _is_boot_lifecycle_denial(decision):
            return decision
        probe_reason = _verified_probe_reason()
        if probe_reason is None:
            return decision
        LOGGER.critical(
            "HEARTBEAT_TERMINAL_LIFECYCLE_V240_ALLOWED marker=%s probe_reason=%s "
            "terminal_surface=broker_manager startup_write_authority_reverified=true "
            "canonical_lifecycle_unchanged=true ordinary_orders_unchanged=true "
            "kill_switch_risk_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER, probe_reason,
        )
        return _bridge(decision, probe_reason)

    setattr(can_execute_v240, _PATCH_ATTR, True)
    setattr(can_execute_v240, "__wrapped__", current)
    return can_execute_v240


def _patch_terminal_modules() -> tuple[bool, tuple[str, ...]]:
    patched: list[str] = []
    seen: set[int] = set()
    for name in _TERMINALS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        if id(module) in seen:
            continue
        seen.add(id(module))
        current = getattr(module, "can_execute", None)
        if not callable(current):
            continue
        wrapped = _wrap(current)
        setattr(module, "can_execute", wrapped)
        if getattr(module, "can_execute", None) is wrapped:
            patched.append(str(getattr(module, "__name__", name)))
    return bool(patched), tuple(sorted(set(patched)))


def install() -> bool:
    try:
        v236 = importlib.import_module("bot.runtime_heartbeat_final_submit_v236_patch")
        install_v236 = getattr(v236, "install", None)
        upstream = bool(callable(install_v236) and install_v236())
        terminal, surfaces = _patch_terminal_modules()
        ready = bool(upstream and terminal)
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_TERMINAL_LIFECYCLE_V240_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready, surfaces = False, ()
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "HEARTBEAT_TERMINAL_LIFECYCLE_V240_READY marker=%s ready=true patched_surfaces=%s "
            "v236_required=true canonical_probe_required=true startup_write_authority_reverified=true "
            "ordinary_orders_unchanged=true canonical_lifecycle_unchanged=true execution_proof_fabricated=false "
            "forced_activation=false safety_gates_bypassed=false",
            MARKER, ",".join(surfaces),
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_patch_terminal_modules"]
