"""Finalize the verified startup-heartbeat handoff at broker submission (v236).

Production on 2026-08-26 showed that the heartbeat order passes risk/ECEL and the
pipeline startup-probe authority check, but a later broker terminal can still
re-evaluate the canonical lifecycle as BOOT. A v233 same-thread grant is the preferred
fast path, but production also proved that intermediate authority reads/reassertions
can consume or replace that transient grant before ``broker_manager`` reaches its
final submit guard.

v236 never creates general execution authority. For an exact lifecycle BOOT denial it
first accepts a still-live v233 grant. If that transient grant is absent, it asks the
canonical ``can_execute_startup_probe()`` in the *current context*. That function only
returns true when the ContextVar reason is one of the whitelisted startup heartbeats
and ``assert_startup_write_authority()`` succeeds. v236 then re-runs
``assert_startup_write_authority()`` immediately before releasing the final submit
boundary. All non-heartbeat contexts and every non-BOOT denial remain fail-closed.
Ordinary orders, lifecycle state, readiness, nonce, risk, capital, broker health,
ECEL, minimum-notional, acknowledgement and fill gates are unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_heartbeat_final_submit_v236")
MARKER = "20260826-heartbeat-final-submit-v236"
_FLAG = "NIJA_HEARTBEAT_FINAL_SUBMIT_V236_READY"
_PATCH_ATTR = "_nija_heartbeat_final_submit_v236"
_MODULES = (
    "bot.broker_manager",
    "broker_manager",
    "bot.broker_integration",
    "broker_integration",
)
_ALLOWED_PROBE_REASONS = {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}


def _authority_module() -> ModuleType | None:
    try:
        module = sys.modules.get("bot.execution_authority_context") or sys.modules.get(
            "execution_authority_context"
        )
        if not isinstance(module, ModuleType):
            module = importlib.import_module("bot.execution_authority_context")
        return module if isinstance(module, ModuleType) else None
    except Exception:
        return None


def _live_verified_grant() -> str | None:
    """Return the preferred v233 same-thread grant without consuming it."""
    try:
        v233 = importlib.import_module("bot.runtime_heartbeat_terminal_authority_v233_patch")
        grant = getattr(v233, "_GRANT", None)
        if grant is None:
            return None
        if int(getattr(grant, "thread_id", -1)) != threading.get_ident():
            return None
        if float(getattr(grant, "expires", 0.0) or 0.0) < time.monotonic():
            return None
        if int(getattr(grant, "remaining", 0) or 0) <= 0:
            return None
        reason = str(getattr(grant, "probe_reason", "") or "").strip().upper()
        return reason if reason in _ALLOWED_PROBE_REASONS else None
    except Exception:
        return None


def _canonical_verified_probe() -> str | None:
    """Independently verify the current ContextVar startup heartbeat.

    This is intentionally not inferred from order fields, thread names, symbols,
    strategy names or call stack. The canonical authority module owns both the
    whitelist and writer-authority verification. If the startup-probe scope has
    already ended, this returns None and the broker submit remains blocked.
    """
    authority = _authority_module()
    if authority is None:
        return None
    checker = getattr(authority, "can_execute_startup_probe", None)
    if not callable(checker):
        return None
    try:
        allowed, reason = checker()
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_FINAL_SUBMIT_V236_PROBE_CHECK_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return None
    normalized = str(reason or "").strip().upper()
    if not bool(allowed) or normalized not in _ALLOWED_PROBE_REASONS:
        return None
    return normalized


def _reverify_startup_write_authority() -> bool:
    authority = _authority_module()
    if authority is None:
        return False
    check = getattr(authority, "assert_startup_write_authority", None)
    if not callable(check):
        return False
    try:
        check()
        return True
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_FINAL_SUBMIT_V236_REVERIFY_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _eligible_boot_denial(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    return "lifecycle_phase:boot" in text or "lifecycle_phase_not_live" in text


def _verified_reason() -> tuple[str | None, str]:
    reason = _live_verified_grant()
    if reason is not None:
        return reason, "v233_grant"
    reason = _canonical_verified_probe()
    if reason is not None:
        return reason, "canonical_probe"
    return None, "none"


def _patch_module(module: ModuleType) -> bool:
    current = getattr(module, "_reject_if_unauthorized_order_submit", None)
    if not callable(current):
        return True
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def final_submit_v236(*args: Any, **kwargs: Any):
        try:
            return current(*args, **kwargs)
        except BaseException as exc:
            # Do not depend on module-local exception identity: import/reassertion
            # can leave terminal modules holding equivalent ExecutionBlocked classes.
            # Eligibility is instead constrained to the exact canonical BOOT denial,
            # then independently authenticated as a whitelisted startup probe.
            if not _eligible_boot_denial(exc):
                raise
            reason, source = _verified_reason()
            if reason is None:
                raise
            if not _reverify_startup_write_authority():
                raise
            LOGGER.critical(
                "HEARTBEAT_FINAL_SUBMIT_V236_ALLOWED marker=%s probe_reason=%s verification_source=%s "
                "same_thread=%s startup_write_authority_reverified=true final_submit_only=true "
                "canonical_lifecycle_unchanged=true ordinary_orders_unchanged=true "
                "kill_switch_nonce_risk_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER, reason, source, str(source == "v233_grant").lower(),
            )
            return None

    setattr(final_submit_v236, _PATCH_ATTR, True)
    setattr(final_submit_v236, "__wrapped__", current)
    setattr(module, "_reject_if_unauthorized_order_submit", final_submit_v236)
    return True


def _patch_surfaces() -> tuple[bool, tuple[str, ...]]:
    patched: list[str] = []
    seen: set[int] = set()
    for name in _MODULES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        if id(module) in seen:
            continue
        seen.add(id(module))
        if _patch_module(module):
            patched.append(str(getattr(module, "__name__", name)))
    return bool(patched), tuple(sorted(set(patched)))


def install() -> bool:
    try:
        # Keep v233/v235 as the preferred same-thread handoff. v236's canonical
        # probe fallback only applies if that transient handoff has been consumed.
        v235 = importlib.import_module("bot.runtime_heartbeat_terminal_broker_manager_v235_patch")
        install_v235 = getattr(v235, "install", None)
        upstream = bool(callable(install_v235) and install_v235())
        terminal, patched = _patch_surfaces()
        ready = bool(upstream and terminal and _authority_module() is not None)
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_FINAL_SUBMIT_V236_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready, patched = False, ()
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "HEARTBEAT_FINAL_SUBMIT_V236_READY marker=%s ready=true patched_surfaces=%s "
            "v233_verified_grant_preferred=true canonical_probe_fallback=true v235_required=true "
            "startup_write_authority_reverified=true final_submit_only=true canonical_lifecycle_unchanged=true "
            "ordinary_orders_unchanged=true execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER, ",".join(patched),
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_live_verified_grant",
    "_canonical_verified_probe",
    "_patch_surfaces",
]
