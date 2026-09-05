"""Revoke stale local LIVE authority when canonical execution proof is absent (v362).

Fresh production evidence on 2026-09-04 showed the local TradingStateMachine
reporting ``LIVE_ACTIVE`` while the canonical readiness table still had
``execution_ready=False`` and v361 correctly reported confirmed-fill execution
proof as pending.  The coordinator remained fail-closed, but legacy
"already LIVE_ACTIVE" idempotency paths could reassert local execution flags
before the canonical proof was revalidated.

v362 closes that stale-liveness gap.  It does not create execution proof or
readiness.  When a local LIVE_ACTIVE state is observed without canonical
``execution_ready`` proof, it atomically demotes only the local FSM to
LIVE_PENDING_CONFIRMATION and revokes local dispatch flags.  The next cycle
must pass the unchanged canonical activation/proof chain naturally.

The stale-LIVE guard also covers ordinary ``get_current_state()`` reads so a
locally stale LIVE_ACTIVE label cannot leak into reconciliation or monitoring
between activation attempts.  Read-time demotion uses the same fail-closed
canonical proof check and never promotes readiness or execution authority.

ACK/status/order-id remains insufficient for fill proof.  Writer, nonce, risk,
capital, position-sync, ECEL, broker-health, minimum-order, fill-verification,
kill-switch, rejection, quantity, and protective-exit gates are unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_stale_live_execution_proof_v362")
MARKER = "20260904-runtime-stale-live-execution-proof-v362"
_READY_FLAG = "NIJA_RUNTIME_STALE_LIVE_EXECUTION_PROOF_V362_READY"
_PATCH_ATTR = "_nija_stale_live_execution_proof_v362"
_PATCH_READ_ATTR = "_nija_stale_live_execution_proof_v362_read_guard"
_LOCK = threading.RLock()


def _canonical_execution_ready() -> tuple[bool, str]:
    """Read canonical execution readiness without mutating or repairing it."""
    try:
        try:
            readiness = importlib.import_module("bot.readiness_table")
        except ImportError:
            readiness = importlib.import_module("readiness_table")
        snapshot = getattr(readiness, "snapshot", None)
        if not callable(snapshot):
            return False, "readiness_snapshot_unavailable"
        table = dict(snapshot() or {})
        ready = bool(table.get("execution_ready", False))
        return ready, "canonical_execution_ready" if ready else "canonical_execution_proof_pending"
    except Exception as exc:
        return False, f"readiness_snapshot_error:{type(exc).__name__}"


def _revoke_stale_live_authority(sm: Any, tsm_module: Any, *, trigger: str) -> bool:
    """Demote stale local LIVE_ACTIVE when canonical execution proof is absent.

    Returns True only when a demotion was performed.  Missing/unreadable proof is
    treated fail-closed exactly like ``execution_ready=False``.
    """
    proof_ready, proof_detail = _canonical_execution_ready()
    if proof_ready:
        return False

    trading_state = getattr(tsm_module, "TradingState", None)
    live_active = getattr(trading_state, "LIVE_ACTIVE", None)
    pending = getattr(trading_state, "LIVE_PENDING_CONFIRMATION", None)
    if live_active is None or pending is None:
        LOGGER.critical(
            "STALE_LIVE_EXECUTION_PROOF_V362_REVOKE_FAILED marker=%s trigger=%s "
            "reason=trading_state_enum_unavailable fail_closed=true",
            MARKER,
            trigger,
        )
        return False

    lock = getattr(sm, "_lock", None)
    if lock is None:
        LOGGER.critical(
            "STALE_LIVE_EXECUTION_PROOF_V362_REVOKE_FAILED marker=%s trigger=%s "
            "reason=state_lock_unavailable fail_closed=true",
            MARKER,
            trigger,
        )
        return False

    changed = False
    with lock:
        if getattr(sm, "_current_state", None) != live_active:
            return False
        sm._current_state = pending
        sm._activation_committed = False
        sm._execution_authority = False
        sm._core_loop_owns_execution = True
        sm._can_dispatch_trades = False
        sm._pending_confirmation_since = time.monotonic()
        sm._last_pending_log_time = None
        sm._pending_timeout_reported = False
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = pending.value
        changed = True

    if changed:
        persist = getattr(sm, "_persist_state", None)
        if callable(persist):
            try:
                persist()
            except Exception:
                LOGGER.exception(
                    "STALE_LIVE_EXECUTION_PROOF_V362_PERSIST_FAILED marker=%s trigger=%s "
                    "runtime_state_remains_fail_closed=true",
                    MARKER,
                    trigger,
                )
        LOGGER.critical(
            "STALE_LIVE_EXECUTION_PROOF_V362_REVOKED marker=%s trigger=%s detail=%s "
            "from_state=LIVE_ACTIVE to_state=LIVE_PENDING_CONFIRMATION "
            "activation_committed=false execution_authority=false can_dispatch_trades=false "
            "execution_ready_unchanged=true execution_proof_fabricated=false ack_not_fill=true "
            "forced_activation=false kill_switch_unchanged=true rejection_latches_unchanged=true "
            "protective_exits_unchanged=true safety_gates_bypassed=false",
            MARKER,
            trigger,
            proof_detail,
        )
    return changed


def _patch_trading_state_machine() -> bool:
    module = importlib.import_module("bot.trading_state_machine")
    cls = getattr(module, "TradingStateMachine", None)
    if cls is None:
        return False

    commit_current = getattr(cls, "commit_activation", None)
    activate_current = getattr(cls, "activate_live_trading", None)
    read_current = getattr(cls, "get_current_state", None)
    if not callable(commit_current) or not callable(activate_current) or not callable(read_current):
        return False

    if not bool(getattr(commit_current, _PATCH_ATTR, False)):
        commit_original = commit_current

        @wraps(commit_original)
        def commit_activation_v362(self: Any, *args: Any, **kwargs: Any) -> bool:
            if _revoke_stale_live_authority(self, module, trigger="commit_activation"):
                # One fail-closed cycle after revocation.  The following cycle
                # re-enters the unchanged canonical activation proof chain.
                return False
            return bool(commit_original(self, *args, **kwargs))

        setattr(commit_activation_v362, _PATCH_ATTR, True)
        setattr(commit_activation_v362, "__wrapped__", commit_original)
        cls.commit_activation = commit_activation_v362

    if not bool(getattr(activate_current, _PATCH_ATTR, False)):
        activate_original = activate_current

        @wraps(activate_original)
        def activate_live_trading_v362(self: Any, *args: Any, **kwargs: Any) -> bool:
            if _revoke_stale_live_authority(self, module, trigger="activate_live_trading"):
                return False
            return bool(activate_original(self, *args, **kwargs))

        setattr(activate_live_trading_v362, _PATCH_ATTR, True)
        setattr(activate_live_trading_v362, "__wrapped__", activate_original)
        cls.activate_live_trading = activate_live_trading_v362

    if not bool(getattr(read_current, _PATCH_READ_ATTR, False)):
        read_original = read_current

        @wraps(read_original)
        def get_current_state_v362(self: Any, *args: Any, **kwargs: Any) -> Any:
            _revoke_stale_live_authority(self, module, trigger="get_current_state")
            return read_original(self, *args, **kwargs)

        setattr(get_current_state_v362, _PATCH_READ_ATTR, True)
        setattr(get_current_state_v362, "__wrapped__", read_original)
        cls.get_current_state = get_current_state_v362

    # If the singleton already exists, revoke stale state immediately without
    # constructing a new state machine as a side effect of installation.
    existing = getattr(module, "_state_machine", None)
    if existing is not None:
        _revoke_stale_live_authority(existing, module, trigger="install_existing_singleton")
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if isinstance(required, dict):
            required["runtime_stale_live_execution_proof_v362"] = _READY_FLAG
            return True
    except Exception:
        pass
    return False


def install_import_hook() -> bool:
    with _LOCK:
        try:
            ok = bool(_patch_trading_state_machine() and _patch_release_manifest())
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_STALE_LIVE_EXECUTION_PROOF_V362_INSTALL_FAILED marker=%s err=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            ok = False
        os.environ[_READY_FLAG] = "1" if ok else "0"
        if ok:
            LOGGER.critical(
                "RUNTIME_STALE_LIVE_EXECUTION_PROOF_V362_READY marker=%s ready=true "
                "canonical_execution_ready_required_for_local_live_authority=true "
                "stale_live_demotes_to_pending=true local_dispatch_revoked=true "
                "stale_live_read_guard=true ack_not_fill=true "
                "execution_ready_unchanged=true execution_proof_fabricated=false forced_activation=false "
                "writer_nonce_risk_capital_position_sync_ecel_broker_health_minimum_order_fill_gates_unchanged=true "
                "kill_switch_unchanged=true rejection_latches_unchanged=true exit_quantities_unchanged=true "
                "take_profit_preserved=true stop_loss_preserved=true trailing_take_profit_preserved=true "
                "trailing_stop_preserved=true auto_exit_reconciler_preserved=true safety_gates_bypassed=false",
                MARKER,
            )
        return ok


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_execution_ready",
    "_revoke_stale_live_authority",
    "_patch_trading_state_machine",
]
