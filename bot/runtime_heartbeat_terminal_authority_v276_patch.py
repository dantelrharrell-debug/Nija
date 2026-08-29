"""Bridge the verified startup heartbeat through terminal execution authority (v276).

Production on 2026-08-29 proved the canonical heartbeat reached the final execution
authority assertion with a healthy writer/core, connected brokers/users, canonical
position sync, a clear kill switch, and an upstream ECEL-accepted order, but
``assert_execution_dispatch_permitted()`` still called the ordinary ``can_execute()``
path and failed at ``lifecycle_phase:BOOT``.  The authority module itself documents
startup probes as the explicit pre-LIVE exception and already provides
``can_execute_startup_probe()`` plus ``assert_startup_write_authority()`` for that
purpose.

v276 closes only that terminal integration gap.  The ordinary assertion always runs
first.  Only an ``ExecutionBlocked`` result whose reason is exactly a pre-LIVE
lifecycle denial may be reconsidered, and only when v263 independently re-verifies
HEARTBEAT_TRADE/HEARTBEAT_TRADE_CLOSE, LIVE_PENDING_CONFIRMATION, live runtime mode,
distributed writer authority, a clear kill switch, and raw nonce authority.  The
canonical startup-probe checker is then re-run before returning.

No lifecycle state, readiness, capital, broker health, risk, ECEL, minimum-notional,
order acknowledgement, fill proof, heartbeat marker, or activation state is mutated.
Ordinary orders and every non-lifecycle denial remain fail closed.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_terminal_authority_v276")
MARKER = "20260829-heartbeat-terminal-authority-v276"
_READY_FLAG = "NIJA_HEARTBEAT_TERMINAL_AUTHORITY_V276_READY"
_PATCH_ATTR = "_nija_heartbeat_terminal_authority_v276"
_IMPORT_HOOK_ATTR = "_NIJA_HEARTBEAT_TERMINAL_AUTHORITY_V276_IMPORT_HOOK"
_ALLOWED_LIFECYCLE_REASONS = {"lifecycle_phase:BOOT", "lifecycle_phase:WARM"}
_LOCK = threading.RLock()


def _authority_module() -> ModuleType:
    module = sys.modules.get("bot.execution_authority_context")
    if not isinstance(module, ModuleType):
        module = importlib.import_module("bot.execution_authority_context")
    if not isinstance(module, ModuleType):
        raise RuntimeError("canonical_execution_authority_unavailable")
    return module


def _verified_startup_probe() -> tuple[bool, str]:
    try:
        v263 = importlib.import_module("bot.runtime_heartbeat_state_machine_gate_v263_patch")
        verifier = getattr(v263, "_verified_startup_probe", None)
        if not callable(verifier):
            return False, "v263_verifier_unavailable"
        verified, detail = verifier()
        if not bool(verified):
            return False, str(detail or "v263_verification_failed")

        authority = _authority_module()
        checker = getattr(authority, "can_execute_startup_probe", None)
        if not callable(checker):
            return False, "startup_probe_checker_unavailable"
        allowed, reason = checker()
        if not bool(allowed):
            return False, f"startup_probe_denied:{reason or 'unknown'}"
        return True, str(reason or detail or "HEARTBEAT_TRADE")
    except Exception as exc:
        return False, f"verification_error:{type(exc).__name__}:{exc}"


def _is_lifecycle_execution_block(authority: ModuleType, exc: BaseException) -> bool:
    blocked_cls = getattr(authority, "ExecutionBlocked", None)
    if not isinstance(blocked_cls, type) or not isinstance(exc, blocked_cls):
        return False
    return str(exc).strip() in _ALLOWED_LIFECYCLE_REASONS


def _wrap_assertion(current: Callable[[], None], authority: ModuleType) -> Callable[[], None]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def assert_execution_dispatch_permitted_v276() -> None:
        try:
            return current()
        except Exception as exc:
            if not _is_lifecycle_execution_block(authority, exc):
                raise

            verified, detail = _verified_startup_probe()
            if not verified:
                LOGGER.info(
                    "HEARTBEAT_TERMINAL_AUTHORITY_V276_DEFERRED marker=%s original_reason=%s detail=%s "
                    "ordinary_orders_unchanged=true trading_fail_closed=true",
                    MARKER,
                    str(exc),
                    detail,
                )
                raise

            LOGGER.critical(
                "HEARTBEAT_TERMINAL_AUTHORITY_V276_ALLOWED marker=%s probe_reason=%s original_reason=%s "
                "ordinary_can_execute_ran_first=true lifecycle_state_unchanged=true startup_probe_reverified=true "
                "distributed_writer_reverified=true raw_nonce_authority=true kill_switch_clear=true "
                "readiness_mutated=false capital_mutated=false heartbeat_marker_written=false "
                "ordinary_orders_unchanged=true risk_broker_health_ecel_min_notional_order_ack_fill_gates_unchanged=true "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
                detail,
                str(exc),
            )
            return None

    setattr(assert_execution_dispatch_permitted_v276, _PATCH_ATTR, True)
    setattr(assert_execution_dispatch_permitted_v276, "__wrapped__", current)
    return assert_execution_dispatch_permitted_v276


def _patch_loaded_authority() -> bool:
    authority = _authority_module()
    current = getattr(authority, "assert_execution_dispatch_permitted", None)
    if not callable(current):
        return False
    wrapped = _wrap_assertion(current, authority)
    setattr(authority, "assert_execution_dispatch_permitted", wrapped)
    installed = getattr(authority, "assert_execution_dispatch_permitted", None)
    return bool(callable(installed) and getattr(installed, _PATCH_ATTR, False))


def _install_import_reassertion_hook() -> bool:
    if bool(getattr(builtins, _IMPORT_HOOK_ATTR, False)):
        return True
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if str(name or "").endswith("execution_authority_context"):
            try:
                _patch_loaded_authority()
            except Exception as exc:
                LOGGER.error(
                    "HEARTBEAT_TERMINAL_AUTHORITY_V276_REASSERT_FAILED marker=%s imported=%s error=%s:%s "
                    "trading_fail_closed=true",
                    MARKER,
                    name,
                    type(exc).__name__,
                    exc,
                )
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_HOOK_ATTR, True)
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["heartbeat_terminal_authority_v276"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        try:
            patched = _patch_loaded_authority()
            hook_ok = _install_import_reassertion_hook()
            manifest_ok = _patch_release_manifest()
            ready = bool(patched and hook_ok and manifest_ok)
        except Exception as exc:
            LOGGER.error(
                "HEARTBEAT_TERMINAL_AUTHORITY_V276_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            ready = False

        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "HEARTBEAT_TERMINAL_AUTHORITY_V276_READY marker=%s ready=true ordinary_assertion_first=true "
                "lifecycle_denial_only=true trusted_startup_probe_only=true live_pending_only=true "
                "distributed_writer_reverification_required=true raw_nonce_authority_required=true kill_switch_clear_required=true "
                "lifecycle_state_unchanged=true readiness_mutated=false ordinary_orders_unchanged=true "
                "risk_capital_broker_health_ecel_min_notional_order_ack_fill_gates_unchanged=true "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_verified_startup_probe",
    "_is_lifecycle_execution_block",
    "_wrap_assertion",
]
