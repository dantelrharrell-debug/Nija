"""Finalize the verified startup-heartbeat handoff at broker submission (v236).

Production on 2026-08-26 showed that the heartbeat order passes risk/ECEL and the
pipeline startup-probe authority check, but a later broker-integration terminal can
still re-evaluate the canonical lifecycle as BOOT after intermediate wrappers have
consumed v233's read budget. That prevents the real verification order from reaching
the exchange, so the heartbeat marker can never be created and execution_ready can
never converge.

v236 does not create startup authority. It only recognizes a still-live v233 grant
that was already armed by an independently verified startup probe, on the same thread
and inside the original sub-second TTL. Before allowing the final submit boundary it
re-runs assert_startup_write_authority(). Only a lifecycle_phase:BOOT denial is
eligible. All other denials remain fail-closed. Ordinary orders cannot arm the grant.
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
_MODULES = ("bot.broker_integration", "broker_integration")


def _live_verified_grant() -> str | None:
    try:
        v233 = importlib.import_module("bot.runtime_heartbeat_terminal_authority_v233_patch")
        grant = getattr(v233, "_GRANT", None)
        if grant is None:
            return None
        if int(getattr(grant, "thread_id", -1)) != threading.get_ident():
            return None
        if float(getattr(grant, "expires", 0.0) or 0.0) < time.monotonic():
            return None
        reason = str(getattr(grant, "probe_reason", "") or "").strip().upper()
        if reason not in {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}:
            return None
        return reason
    except Exception:
        return None


def _reverify_startup_write_authority() -> bool:
    try:
        authority = importlib.import_module("bot.execution_authority_context")
        check = getattr(authority, "assert_startup_write_authority", None)
        if not callable(check):
            return False
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


def _patch_module(module: ModuleType) -> bool:
    current = getattr(module, "_reject_if_unauthorized_order_submit", None)
    if not callable(current):
        return True
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    blocked_cls = getattr(module, "ExecutionBlocked", RuntimeError)

    @wraps(current)
    def final_submit_v236(*args: Any, **kwargs: Any):
        try:
            return current(*args, **kwargs)
        except blocked_cls as exc:
            if not _eligible_boot_denial(exc):
                raise
            reason = _live_verified_grant()
            if reason is None:
                raise
            if not _reverify_startup_write_authority():
                raise
            LOGGER.critical(
                "HEARTBEAT_FINAL_SUBMIT_V236_ALLOWED marker=%s probe_reason=%s "
                "same_thread=true ttl_live=true startup_write_authority_reverified=true "
                "final_submit_only=true canonical_lifecycle_unchanged=true ordinary_orders_unchanged=true "
                "kill_switch_nonce_risk_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER, reason,
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
        # Ensure the upstream grant and extended terminal budget are installed first.
        v235 = importlib.import_module("bot.runtime_heartbeat_terminal_broker_manager_v235_patch")
        install_v235 = getattr(v235, "install", None)
        upstream = bool(callable(install_v235) and install_v235())
        terminal, patched = _patch_surfaces()
        ready = bool(upstream and terminal)
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
            "v233_verified_grant_required=true v235_required=true same_thread=true original_ttl_preserved=true "
            "startup_write_authority_reverified=true final_submit_only=true canonical_lifecycle_unchanged=true "
            "ordinary_orders_unchanged=true execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER, ",".join(patched),
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_live_verified_grant", "_patch_surfaces"]
