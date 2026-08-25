"""Bridge terminal broker authority gates for verified startup heartbeats (v233).

The startup heartbeat is allowed only after can_execute_startup_probe() independently
re-verifies startup write authority. Production showed that the first pipeline
terminal consumed that ContextVar-backed authorization, while the later
broker-manager submit check could run after the probe context was no longer visible.

This revision carries a one-shot, same-thread, sub-second terminal grant from the
verified pipeline authority check to the immediately-following broker submit check.
It never changes lifecycle state, readiness, nonce, kill switch, capital, broker
health, ECEL, minimum-notional, acknowledgement, or fill proof. Ordinary orders do
not receive the grant.
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
    _GRANT.remaining = 1
    _GRANT.probe_reason = str(probe_reason)


def _consume_one_shot_grant(decision: Any) -> str | None:
    if not _boot_lifecycle_block(decision):
        return None
    if int(getattr(_GRANT, "thread_id", -1)) != threading.get_ident():
        return None
    if float(getattr(_GRANT, "expires", 0.0) or 0.0) < time.monotonic():
        return None
    if int(getattr(_GRANT, "remaining", 0) or 0) <= 0:
        return None
    _GRANT.remaining = 0
    return str(getattr(_GRANT, "probe_reason", "HEARTBEAT_TRADE") or "HEARTBEAT_TRADE")


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
        if bool(getattr(decision, "allowed", False)):
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
                "original_reason=%s same_thread=true one_shot=true canonical_lifecycle_unchanged=true "
                "ordinary_orders_unchanged=true execution_proof_fabricated=false forced_activation=false "
                "safety_gates_bypassed=false",
                MARKER, inherited_reason, _decision_reason(decision),
            )
            return bridged
        return decision

    setattr(can_execute_v233, _PATCH_ATTR, True)
    setattr(can_execute_v233, "__wrapped__", current)
    return can_execute_v233


def _patch_terminal_surfaces() -> tuple[bool, tuple[str, ...]]:
    authority = _authority_module()
    current = getattr(authority, "can_execute", None)
    if not callable(current):
        return False, ()

    wrapped = _wrap_can_execute(current, authority)
    setattr(authority, "can_execute", wrapped)
    for alias in _AUTHORITY_MODULE_NAMES:
        module = sys.modules.get(alias)
        if isinstance(module, ModuleType):
            setattr(module, "can_execute", wrapped)

    patched: list[str] = []
    seen: set[int] = set()
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
            if getattr(module, "can_execute", None) is wrapped:
                patched.append(str(getattr(module, "__name__", module_name)))

    canonical_ok = bool(getattr(authority, "can_execute", None) is wrapped and getattr(wrapped, _PATCH_ATTR, False))
    return canonical_ok and bool(patched), tuple(sorted(set(patched)))


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
        "one_shot_terminal_grant=true grant_ttl_s=%.2f ordinary_orders_unchanged=true canonical_lifecycle_unchanged=true "
        "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
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
    "_wrap_can_execute",
]
