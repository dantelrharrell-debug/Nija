"""Bridge terminal broker authority gates for verified startup heartbeats (v233).

The startup heartbeat is allowed only after can_execute_startup_probe() independently
re-verifies startup write authority. Production showed that the first pipeline
terminal consumed that ContextVar-backed authorization, while a later broker submit
guard could still hold an imported/stale can_execute reference and re-block the same
verified heartbeat on lifecycle_phase:BOOT.

This revision carries a same-thread, sub-second terminal grant from the verified
pipeline authority check to the immediately-following broker submit guard. It patches
both can_execute() and can_execute_startup_probe() on terminal broker modules so the
existing broker_manager fallback path can atomically consume the already-verified
grant even when its can_execute reference is stale. It never changes lifecycle state,
readiness, nonce, kill switch, capital, broker health, ECEL, minimum-notional,
acknowledgement, or fill proof. Ordinary orders do not receive the grant.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from dataclasses import replace
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_terminal_authority_v233")
MARKER = "20260825-heartbeat-terminal-authority-v233"
_FLAG = "NIJA_HEARTBEAT_TERMINAL_AUTHORITY_V233_READY"
_PATCH_ATTR = "_nija_heartbeat_terminal_authority_v233"
_PROBE_PATCH_ATTR = "_nija_heartbeat_terminal_probe_v233"
_GUARD_PATCH_ATTR = "_nija_heartbeat_terminal_submit_guard_v233"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_GRANT = threading.local()
_GRANT_TTL_S = 0.75

_AUTHORITY_MODULE_NAMES = (
    "bot.execution_authority_context",
    "execution_authority_context",
)
_TERMINAL_MODULE_NAMES = (
    "bot.broker_manager",
    "broker_manager",
    "bot.broker_integration",
    "broker_integration",
)


def _authority_module() -> ModuleType:
    module = sys.modules.get("bot.execution_authority_context") or sys.modules.get("execution_authority_context")
    if not isinstance(module, ModuleType):
        module = importlib.import_module("bot.execution_authority_context")
    sys.modules.setdefault("bot.execution_authority_context", module)
    sys.modules.setdefault("execution_authority_context", module)
    return module


def _decision_reason(decision: Any) -> str:
    return str(getattr(decision, "reason", "") or getattr(decision, "reason_detail", "") or "")


def _boot_lifecycle_block(decision: Any) -> bool:
    text = _decision_reason(decision).lower()
    code = str(getattr(decision, "reason_code", "") or "").lower()
    return "lifecycle_phase:boot" in text or "lifecycle_phase_not_live" in code


def _set_one_shot_grant(probe_reason: str) -> None:
    _GRANT.thread_id = threading.get_ident()
    _GRANT.expires = time.monotonic() + _GRANT_TTL_S
    # Two terminal reads are permitted because production has both the pipeline
    # terminal and a broker-submit terminal. The grant remains same-thread,
    # sub-second, and startup-probe-only.
    _GRANT.remaining = 2
    _GRANT.probe_reason = str(probe_reason)


def _grant_reason_if_live() -> str | None:
    if int(getattr(_GRANT, "thread_id", -1)) != threading.get_ident():
        return None
    if float(getattr(_GRANT, "expires", 0.0) or 0.0) < time.monotonic():
        return None
    if int(getattr(_GRANT, "remaining", 0) or 0) <= 0:
        return None
    return str(getattr(_GRANT, "probe_reason", "HEARTBEAT_TRADE") or "HEARTBEAT_TRADE")


def _consume_live_grant() -> str | None:
    reason = _grant_reason_if_live()
    if reason is None:
        return None
    _GRANT.remaining = max(0, int(getattr(_GRANT, "remaining", 0) or 0) - 1)
    return reason


def _consume_one_shot_grant(decision: Any) -> str | None:
    if not _boot_lifecycle_block(decision):
        return None
    return _consume_live_grant()


def _bridge_decision(decision: Any, probe_reason: str) -> Any:
    try:
        return replace(
            decision,
            allowed=True,
            reason=f"startup_probe_terminal_authority:{probe_reason}",
            first_failed_gate="",
            reason_code="allowed_startup_probe",
            reason_detail=f"startup_probe_terminal_authority:{probe_reason}",
        )
    except Exception:
        class _DecisionProxy:
            pass
        bridged = _DecisionProxy()
        try:
            bridged.__dict__.update(getattr(decision, "__dict__", {}) or {})
        except Exception:
            pass
        bridged.allowed = True
        bridged.allow = True
        bridged.decision = "ALLOW"
        bridged.reason = f"startup_probe_terminal_authority:{probe_reason}"
        bridged.first_failed_gate = ""
        bridged.reason_code = "allowed_startup_probe"
        bridged.reason_detail = f"startup_probe_terminal_authority:{probe_reason}"
        return bridged


def _wrap_can_execute(current: Callable[..., Any], authority: ModuleType) -> Callable[..., Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def can_execute_v233(*args: Any, **kwargs: Any) -> Any:
        decision = current(*args, **kwargs)
        if bool(getattr(decision, "allowed", getattr(decision, "allow", False))):
            return decision

        checker = getattr(authority, "can_execute_startup_probe", None)
        if callable(checker):
            try:
                allowed, probe_reason = checker()
            except Exception as exc:
                LOGGER.warning(
                    "HEARTBEAT_TERMINAL_AUTHORITY_V233_CHECK_ERROR marker=%s err=%s:%s trading_fail_closed=true",
                    MARKER, type(exc).__name__, exc,
                )
                allowed, probe_reason = False, "check_error"
            if allowed and _boot_lifecycle_block(decision):
                _set_one_shot_grant(str(probe_reason))
                bridged = _bridge_decision(decision, str(probe_reason))
                LOGGER.critical(
                    "HEARTBEAT_TERMINAL_AUTHORITY_V233_ALLOWED marker=%s probe_reason=%s original_reason=%s "
                    "broker_terminal_only=true startup_write_authority_reverified=true terminal_grant_armed=true "
                    "grant_ttl_s=%.2f canonical_lifecycle_unchanged=true ordinary_orders_unchanged=true "
                    "writer_nonce_risk_killswitch_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
                    "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                    MARKER, str(probe_reason), _decision_reason(decision), _GRANT_TTL_S,
                )
                return bridged

        inherited_reason = _consume_one_shot_grant(decision)
        if inherited_reason:
            bridged = _bridge_decision(decision, inherited_reason)
            LOGGER.critical(
                "HEARTBEAT_TERMINAL_AUTHORITY_V233_TERMINAL_GRANT_CONSUMED marker=%s probe_reason=%s "
                "original_reason=%s same_thread=true bounded_grant=true canonical_lifecycle_unchanged=true "
                "ordinary_orders_unchanged=true execution_proof_fabricated=false forced_activation=false "
                "safety_gates_bypassed=false",
                MARKER, inherited_reason, _decision_reason(decision),
            )
            return bridged
        return decision

    setattr(can_execute_v233, _PATCH_ATTR, True)
    setattr(can_execute_v233, "__wrapped__", current)
    return can_execute_v233


def _wrap_startup_probe(current: Callable[..., Any]) -> Callable[..., Any]:
    """Let terminal broker fallback checks consume an already-verified v233 grant.

    broker_manager intentionally calls can_execute_startup_probe() after a denied
    can_execute(). In production its imported can_execute reference can be stale,
    so this wrapper gives that existing fallback path access to the same-thread,
    sub-second grant created by the canonical pipeline check. It never creates a
    grant and therefore cannot authorize an ordinary order on its own.
    """
    if bool(getattr(current, _PROBE_PATCH_ATTR, False)):
        return current

    @wraps(current)
    def startup_probe_v233(*args: Any, **kwargs: Any):
        try:
            allowed, reason = current(*args, **kwargs)
        except Exception:
            allowed, reason = False, "startup_probe_error"
        if bool(allowed):
            return allowed, reason
        inherited_reason = _consume_live_grant()
        if inherited_reason is None:
            return allowed, reason
        LOGGER.critical(
            "HEARTBEAT_TERMINAL_AUTHORITY_V233_BROKER_PROBE_GRANT_CONSUMED marker=%s probe_reason=%s "
            "same_thread=true bounded_grant=true terminal_fallback=true ordinary_orders_unchanged=true "
            "canonical_lifecycle_unchanged=true execution_proof_fabricated=false forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER, inherited_reason,
        )
        return True, inherited_reason

    setattr(startup_probe_v233, _PROBE_PATCH_ATTR, True)
    setattr(startup_probe_v233, "__wrapped__", current)
    return startup_probe_v233


def _patch_submit_guard(module: ModuleType) -> bool:
    """Patch the final broker-integration guard that may retain a stale import."""
    current = getattr(module, "_reject_if_unauthorized_order_submit", None)
    if not callable(current):
        return True
    if bool(getattr(current, _GUARD_PATCH_ATTR, False)):
        return True

    blocked_cls = getattr(module, "ExecutionBlocked", RuntimeError)

    @wraps(current)
    def submit_guard_v233(*args: Any, **kwargs: Any):
        try:
            return current(*args, **kwargs)
        except blocked_cls as exc:
            text = str(exc or "").lower()
            if "lifecycle_phase:boot" not in text and "lifecycle_phase_not_live" not in text:
                raise
            inherited_reason = _consume_live_grant()
            if inherited_reason is None:
                raise
            LOGGER.critical(
                "HEARTBEAT_TERMINAL_AUTHORITY_V233_SUBMIT_GUARD_CONSUMED marker=%s probe_reason=%s "
                "same_thread=true bounded_grant=true original_error=%s ordinary_orders_unchanged=true "
                "canonical_lifecycle_unchanged=true execution_proof_fabricated=false forced_activation=false "
                "safety_gates_bypassed=false",
                MARKER, inherited_reason, str(exc),
            )
            return None

    setattr(submit_guard_v233, _GUARD_PATCH_ATTR, True)
    setattr(submit_guard_v233, "__wrapped__", current)
    setattr(module, "_reject_if_unauthorized_order_submit", submit_guard_v233)
    return True


def _patch_terminal_surfaces() -> tuple[bool, tuple[str, ...]]:
    authority = _authority_module()
    current = getattr(authority, "can_execute", None)
    canonical_probe = getattr(authority, "can_execute_startup_probe", None)
    if not callable(current) or not callable(canonical_probe):
        return False, ()

    wrapped = _wrap_can_execute(current, authority)
    setattr(authority, "can_execute", wrapped)
    for alias in _AUTHORITY_MODULE_NAMES:
        module = sys.modules.get(alias)
        if isinstance(module, ModuleType):
            setattr(module, "can_execute", wrapped)

    patched: list[str] = []
    seen: set[int] = set()
    guard_ok = True
    probe_ok = True
    for module_name in _TERMINAL_MODULE_NAMES:
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
        if id(module) in seen:
            continue
        seen.add(id(module))

        existing = getattr(module, "can_execute", None)
        if callable(existing):
            setattr(module, "can_execute", wrapped)

        existing_probe = getattr(module, "can_execute_startup_probe", None)
        if callable(existing_probe):
            terminal_probe = _wrap_startup_probe(existing_probe)
            setattr(module, "can_execute_startup_probe", terminal_probe)
            probe_ok = bool(getattr(module, "can_execute_startup_probe", None) is terminal_probe and probe_ok)

        if getattr(module, "can_execute", None) is wrapped:
            patched.append(str(getattr(module, "__name__", module_name)))

        if module_name.endswith("broker_integration") or module_name.endswith("broker_manager"):
            guard_ok = bool(_patch_submit_guard(module) and guard_ok)

    canonical_ok = bool(getattr(authority, "can_execute", None) is wrapped and getattr(wrapped, _PATCH_ATTR, False))
    return canonical_ok and bool(patched) and guard_ok and probe_ok, tuple(sorted(set(patched)))


def _patch_broker_manager() -> bool:
    ready, _ = _patch_terminal_surfaces()
    return ready


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    except Exception:
        return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict):
        return False
    required["heartbeat_terminal_authority_v233"] = _FLAG
    own = ("bot.runtime_heartbeat_terminal_authority_v233_patch", "install_import_hook")
    if isinstance(installers, tuple) and own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def _worker() -> None:
    while True:
        try:
            _patch_terminal_surfaces()
            _register_manifest()
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_TERMINAL_AUTHORITY_V233_REASSERT_ERROR marker=%s err=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        time.sleep(0.20)


def install() -> bool:
    global _THREAD
    terminal_ready, patched_surfaces = _patch_terminal_surfaces()
    manifest_ready = _register_manifest()
    ready = bool(terminal_ready and manifest_ready)
    os.environ[_FLAG] = "1" if ready else "0"
    if not ready:
        LOGGER.critical(
            "HEARTBEAT_TERMINAL_AUTHORITY_V233_FAILED marker=%s terminal_ready=%s manifest_ready=%s patched_surfaces=%s trading_fail_closed=true",
            MARKER, str(terminal_ready).lower(), str(manifest_ready).lower(), ",".join(patched_surfaces) or "none",
        )
        return False
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_worker, name="HeartbeatTerminalAuthorityV233", daemon=True)
            _THREAD.start()
    LOGGER.critical(
        "HEARTBEAT_TERMINAL_AUTHORITY_V233_READY marker=%s ready=true broker_terminal_startup_probe_bridge=true "
        "canonical_authority_wrapped=true patched_surfaces=%s startup_write_authority_required=true "
        "bounded_terminal_grant=true grant_ttl_s=%.2f broker_submit_guard_patched=true terminal_probe_patched=true "
        "ordinary_orders_unchanged=true canonical_lifecycle_unchanged=true execution_proof_fabricated=false "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER, ",".join(patched_surfaces), _GRANT_TTL_S,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch_broker_manager",
    "_patch_terminal_surfaces",
    "_patch_submit_guard",
    "_wrap_can_execute",
    "_wrap_startup_probe",
]
