"""Canonical writer-epoch destruction telemetry and invariant enforcement.

This module provides two key primitives:

1. ``emit_writer_epoch_ended`` — emit the single canonical ``WRITER_EPOCH_ENDED``
   event exactly once when a positive writer generation transitions to 0.  Every
   writer-authority-clearing path must call this function before any component
   can observe ``expected_generation=0``.

2. ``check_writer_epoch_invariant`` — verify that the generation→0 transition
   occurred through a sanctioned path (explicit canonical shutdown, proven
   terminal lease/fencing loss, canonical startup failure, or controlled
   handoff/re-election).  Any other transition emits ``WRITER_EPOCH_INVARIANT_VIOLATION``
   and fails closed.

Non-regression contract
-----------------------
* ``generation=0`` blocks heartbeat re-anchor (HEARTBEAT_V42_REANCHOR_BLOCKED
  is preserved upstream).
* This module never synthesises a generation value, never re-anchors a heartbeat,
  never enables execution, and never recovers Kraken nonce authority.
* Positive generation may only come from a newly-acquired canonical Redis writer
  lease — this module has no role in that path.

Thread safety
-------------
The ``_EPOCH_LOCK`` guards the single-emission guarantee so concurrent callers
cannot race and emit duplicate events.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("nija.writer_epoch_telemetry")

# ---------------------------------------------------------------------------
# Epoch-ended single-emission guard
# ---------------------------------------------------------------------------

_EPOCH_LOCK = threading.Lock()
_epoch_ended_emitted: bool = False
_epoch_ended_generation_before: int = 0

# ---------------------------------------------------------------------------
# Sanctioned transition reasons
# ---------------------------------------------------------------------------

_SANCTIONED_REASONS = frozenset({
    # 1. explicit canonical terminal shutdown
    "terminal_shutdown",
    "intentional_release",
    "process_exit_requested",
    "controlled_shutdown",
    "shutdown_requested",
    # 2. proven terminal writer lease/fencing loss
    "lease_no_longer_owned",
    "lease_deleted",
    "lease_expired",
    "fencing_token_invalid",
    "fencing_invalid",
    "generation_changed",
    "generation_mismatch",
    "authority_lost",
    "authority_LOST",
    "compare_delete_failed",
    "compare_and_delete_failed",
    "writer_lease_lost",
    "writer_authority_lost",
    # 3. canonical startup failure
    "startup_failure",
    "canonical_startup_failure",
    "bootstrap_failure",
    "startup_authority_failed",
    # 4. controlled handoff/re-election
    "controlled_handoff",
    "re_election",
    "reelection",
    "handoff_complete",
})


def _is_sanctioned(reason: str) -> bool:
    """Return True if *reason* matches a sanctioned transition path."""
    lower = str(reason or "").lower()
    for kw in _SANCTIONED_REASONS:
        if kw.lower() in lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Internal helpers — read env-state snapshot at time of transition
# ---------------------------------------------------------------------------

def _bool_env(name: str) -> bool:
    _true = {"1", "true", "yes", "on", "enabled", "y"}
    return str(os.environ.get(name, "") or "").strip().lower() in _true


def _read_epoch_context() -> dict[str, Any]:
    """Capture a snapshot of writer-authority env state for the event payload."""
    try:
        try:
            from bot.heartbeat_state import get_heartbeat_state
        except ImportError:
            from heartbeat_state import get_heartbeat_state  # type: ignore[import]
        hs = get_heartbeat_state()
        snap = hs.snapshot()
        heartbeat_active_before = bool(snap.healthy)
    except Exception:
        heartbeat_active_before = _bool_env("NIJA_WRITER_HEARTBEAT_ACTIVE")

    try:
        try:
            from bot.terminal_writer_loss_latch import is_latched
        except ImportError:
            from terminal_writer_loss_latch import is_latched  # type: ignore[import]
        terminal_loss_latched = is_latched()
    except Exception:
        terminal_loss_latched = False

    try:
        try:
            from bot.entrypoint_writer_authority import get_entrypoint_writer_authority
        except ImportError:
            from entrypoint_writer_authority import get_entrypoint_writer_authority  # type: ignore[import]
        ea = get_entrypoint_writer_authority()
        core_thread = getattr(ea, "_core_thread", None)
        if core_thread is not None:
            core_alive = bool(getattr(core_thread, "is_alive", lambda: False)())
        else:
            core_alive = _bool_env("NIJA_CORE_THREAD_ALIVE")
        core_registered = bool(
            getattr(ea, "_core_thread_registered", False)
            or core_alive
        )
    except Exception:
        core_alive = _bool_env("NIJA_CORE_THREAD_ALIVE")
        core_registered = core_alive

    startup_phase = str(os.environ.get("NIJA_STARTUP_PHASE", "") or "unknown")
    runtime_state = str(os.environ.get("NIJA_WRITER_STATE", "") or "UNKNOWN").strip().upper()
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    generation_env = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    lease_owned = _bool_env("NIJA_WRITER_LEASE_ACQUIRED")

    return {
        "startup_phase": startup_phase,
        "runtime_state": runtime_state,
        "token_present_before": bool(token),
        "lease_owned_before": lease_owned,
        "heartbeat_active_before": heartbeat_active_before,
        "core_alive": core_alive,
        "core_registered": core_registered,
        "shutdown_requested": _bool_env("NIJA_SHUTDOWN_REQUESTED"),
        "terminal_loss_latched": terminal_loss_latched,
        "_generation_env_before": generation_env,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def emit_writer_epoch_ended(
    *,
    reason: str,
    source: str,
    generation_before: Optional[int] = None,
) -> bool:
    """Emit ``WRITER_EPOCH_ENDED`` exactly once for a positive→0 generation transition.

    Parameters
    ----------
    reason:
        Canonical reason string (e.g. ``"lease_no_longer_owned"``).
    source:
        Caller identifier (e.g. ``"terminal_writer_loss_latch"``).
    generation_before:
        The positive generation that is being destroyed.  If ``None``, read from
        the current environment.

    Returns
    -------
    bool
        ``True`` if this call emitted the event (first call for a positive
        generation), ``False`` if the event was already emitted or there was no
        positive generation to destroy.
    """
    global _epoch_ended_emitted, _epoch_ended_generation_before

    # Resolve generation_before
    if generation_before is None:
        try:
            generation_before = int(
                str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "0").strip() or "0"
            )
        except (TypeError, ValueError):
            generation_before = 0

    if generation_before <= 0:
        # Nothing to destroy — generation was already 0 or unknown.
        logger.debug(
            "WRITER_EPOCH_ENDED_SKIP reason=no_positive_generation "
            "generation_before=%d source=%s",
            generation_before,
            source,
        )
        return False

    with _EPOCH_LOCK:
        if _epoch_ended_emitted:
            logger.warning(
                "WRITER_EPOCH_ENDED_ALREADY_EMITTED "
                "first_generation=%d new_attempt_generation=%d "
                "source=%s reason=%s — no-op",
                _epoch_ended_generation_before,
                generation_before,
                source,
                reason,
            )
            return False

        ctx = _read_epoch_context()
        _epoch_ended_emitted = True
        _epoch_ended_generation_before = generation_before

    # Emit outside the lock so we don't hold it during potentially slow I/O.
    logger.critical(
        "WRITER_EPOCH_ENDED "
        "timestamp=%.6f "
        "source=%s "
        "reason=%s "
        "startup_phase=%s "
        "runtime_state=%s "
        "generation_before=%d "
        "generation_after=0 "
        "token_present_before=%s "
        "token_present_after=false "
        "lease_owned_before=%s "
        "lease_owned_after=false "
        "heartbeat_active_before=%s "
        "heartbeat_active_after=false "
        "core_alive=%s "
        "core_registered=%s "
        "shutdown_requested=%s "
        "terminal_loss_latched=%s",
        time.time(),
        source,
        reason,
        ctx["startup_phase"],
        ctx["runtime_state"],
        generation_before,
        str(ctx["token_present_before"]).lower(),
        str(ctx["lease_owned_before"]).lower(),
        str(ctx["heartbeat_active_before"]).lower(),
        str(ctx["core_alive"]).lower(),
        str(ctx["core_registered"]).lower(),
        str(ctx["shutdown_requested"]).lower(),
        str(ctx["terminal_loss_latched"]).lower(),
    )
    return True


def check_writer_epoch_invariant(
    *,
    reason: str,
    source: str,
    generation_before: int,
    core_alive_before: bool = False,
    core_registered_before: bool = False,
) -> bool:
    """Check the writer-epoch transition invariant and emit violation event if needed.

    The invariant states: if the system previously had ``generation G > 0`` AND
    ``core_thread_alive=True`` AND ``core_thread_registered=True``, then
    generation may become 0 only through a sanctioned transition path.

    Parameters
    ----------
    reason:
        The reason for the generation→0 transition.
    source:
        Caller identifier.
    generation_before:
        The generation value before the transition.
    core_alive_before:
        Whether the core thread was alive before the transition.
    core_registered_before:
        Whether the core thread was registered before the transition.

    Returns
    -------
    bool
        ``True`` if the transition is valid (sanctioned or invariant not applicable),
        ``False`` if the invariant was violated.
    """
    if generation_before <= 0:
        # Invariant only applies when there was a positive generation.
        return True

    if not (core_alive_before and core_registered_before):
        # Invariant only applies when core thread was alive AND registered.
        return True

    if _is_sanctioned(reason):
        logger.debug(
            "WRITER_EPOCH_INVARIANT_CHECK sanctioned "
            "generation_before=%d reason=%s source=%s "
            "core_alive_before=%s core_registered_before=%s",
            generation_before,
            reason,
            source,
            core_alive_before,
            core_registered_before,
        )
        return True

    # Invariant violated — fail closed.
    logger.critical(
        "WRITER_EPOCH_INVARIANT_VIOLATION "
        "generation_before=%d "
        "reason=%s "
        "source=%s "
        "core_alive_before=%s "
        "core_registered_before=%s "
        "sanctioned=false "
        "action=fail_closed",
        generation_before,
        reason,
        source,
        core_alive_before,
        core_registered_before,
    )
    # Enforce fail-closed: suppress execution authority.
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
    return False


def is_epoch_ended_emitted() -> bool:
    """Return True if WRITER_EPOCH_ENDED has already been emitted this process lifetime."""
    return _epoch_ended_emitted


def reset_for_test() -> None:
    """Reset module state for unit tests only.  Never call in production."""
    global _epoch_ended_emitted, _epoch_ended_generation_before
    with _EPOCH_LOCK:
        _epoch_ended_emitted = False
        _epoch_ended_generation_before = 0


__all__ = [
    "emit_writer_epoch_ended",
    "check_writer_epoch_invariant",
    "is_epoch_ended_emitted",
    "reset_for_test",
]
