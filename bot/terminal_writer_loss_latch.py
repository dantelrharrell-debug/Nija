"""Idempotent process-level latch for terminal writer-authority loss.

The latch fires exactly once — the first authoritative terminal proof atomically:
  1. Records the reason, source, and timestamp.
  2. Revokes execution/nonce/authority readiness from readiness_table.
  3. Halts SEAK (single-execution-authority-kernel).
  4. Sets global shutdown intent.
  5. Requests process exit code 75 via bot_main.request_process_exit.
  6. Arms forced-restart timer as final bound.

Later calls to report_terminal_writer_loss() are no-ops that log already-latched status.

MUST differentiate terminal vs transient probe failures:
- Do NOT trigger terminal exit on single Redis timeout / exchange / balance errors.
- Require canonical terminal proofs: lease no longer owned, fencing invalid,
  generation changed, authority LOST, intentional lease release on core death, etc.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger("nija.terminal_writer_loss_latch")

# ---------------------------------------------------------------------------
# Process-level latch state
# ---------------------------------------------------------------------------
_LATCH_LOCK = threading.Lock()
_latched: bool = False
_latch_reason: str = ""
_latch_source: str = ""
_latch_timestamp: float = 0.0
_latch_writer_generation: str = ""

# Env flag: if set to "1" before the latch is needed, private I/O workers must
# check it and suppress new outbound private HTTP requests.
PRIVATE_IO_STOP_FLAG = "NIJA_PRIVATE_IO_STOP"


def is_latched() -> bool:
    """Return True if the terminal loss latch has already fired."""
    return _latched


def get_latch_info() -> dict:
    """Return a snapshot of the latch state (for diagnostics)."""
    with _LATCH_LOCK:
        return {
            "latched": _latched,
            "reason": _latch_reason,
            "source": _latch_source,
            "timestamp": _latch_timestamp,
            "writer_generation": _latch_writer_generation,
        }


def report_terminal_writer_loss(reason: str, source: str) -> bool:
    """Idempotent terminal-loss entry point.

    Returns True if this call fired the latch (first terminal proof).
    Returns False if the latch was already set (subsequent calls are no-ops).

    Parameters
    ----------
    reason : canonical terminal-loss reason string (e.g. "writer_authority_lost",
             "lease_no_longer_owned", "fencing_token_invalid", "generation_changed",
             "authority_LOST").
    source : identifying label for the caller (e.g. "on_lease_lost",
             "heartbeat_monitor", "authority_context").
    """
    global _latched, _latch_reason, _latch_source, _latch_timestamp, _latch_writer_generation

    with _LATCH_LOCK:
        if _latched:
            logger.critical(
                "WRITER_LOSS_CLASSIFICATION event=already_latched "
                "new_reason=%s new_source=%s "
                "first_reason=%s first_source=%s first_ts=%.3f — no-op",
                reason,
                source,
                _latch_reason,
                _latch_source,
                _latch_timestamp,
            )
            return False

        # Classify the reason — must be a canonical terminal proof, not a
        # transient probe failure.
        if not _is_terminal_proof(reason):
            logger.warning(
                "WRITER_LOSS_CLASSIFICATION event=transient_not_terminal "
                "reason=%s source=%s — not firing latch",
                reason,
                source,
            )
            return False

        _latched = True
        _latch_reason = str(reason or "unknown")
        _latch_source = str(source or "unknown")
        _latch_timestamp = time.time()
        _latch_writer_generation = os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "0"

    logger.critical(
        "WRITER_LOSS_CLASSIFICATION event=terminal_latched "
        "reason=%s source=%s ts=%.3f writer_generation=%s",
        _latch_reason,
        _latch_source,
        _latch_timestamp,
        _latch_writer_generation,
    )

    # ── Step 2: Revoke execution/nonce/authority readiness atomically ──────
    _revoke_readiness_on_terminal_loss(_latch_reason)

    # ── Step 3: Halt SEAK ──────────────────────────────────────────────────
    _halt_seak_on_terminal_loss(_latch_reason)

    # ── Step 4: Signal global shutdown + private-I/O stop ─────────────────
    os.environ[PRIVATE_IO_STOP_FLAG] = "1"
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
    _signal_global_shutdown()

    # ── Step 5: Request process exit code 75 ──────────────────────────────
    _request_exit_75(_latch_reason)

    # ── Step 6: Arm forced-restart timer as final bound ───────────────────
    _arm_forced_restart(_latch_reason)

    return True


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# Terminal reasons that unambiguously indicate the current process has lost
# writer authority.  Must be canonical, not transient probe failures.
_TERMINAL_REASON_KEYWORDS = frozenset({
    "writer_authority_lost",
    "lease_no_longer_owned",
    "lease_deleted",
    "lease_expired",
    "fencing_token_invalid",
    "fencing_invalid",
    "generation_changed",
    "generation_mismatch",
    "authority_lost",
    "authority_LOST",
    "intentional_release",
    "core_thread_died",
    "registration_deadline_exceeded",
    "terminal_shutdown",
    "compare_delete_failed",
    "compare_and_delete_failed",
    "writer_lease_lost",
})

_TRANSIENT_KEYWORDS = frozenset({
    "redis_timeout",
    "connection_timeout",
    "connection_refused",
    "exchange_error",
    "balance_error",
    "api_timeout",
    "network_error",
    "transient",
})


def _is_terminal_proof(reason: str) -> bool:
    """Return True only for canonical terminal-loss reasons."""
    lower = str(reason or "").lower()
    # A transient signal must not trigger terminal exit.
    for kw in _TRANSIENT_KEYWORDS:
        if kw in lower:
            return False
    # Must match at least one terminal keyword.
    for kw in _TERMINAL_REASON_KEYWORDS:
        if kw in lower:
            return True
    # Unknown reasons remain fail-closed (do not trigger latch automatically).
    # The caller should use explicit terminal reasons.
    return False


def _revoke_readiness_on_terminal_loss(reason: str) -> None:
    try:
        try:
            from bot.readiness_table import revoke_many
        except ImportError:
            from readiness_table import revoke_many  # type: ignore[import]
        revoke_many(
            ("authority_ready", "nonce_ready", "execution_ready"),
            reason=f"terminal_writer_loss:{reason}",
        )
    except Exception as exc:
        logger.critical(
            "TERMINAL_WRITER_LOSS_REVOKE_FAILED err=%s", exc, exc_info=True
        )


def _halt_seak_on_terminal_loss(reason: str) -> None:
    try:
        try:
            from bot.single_execution_authority_kernel import get_seak
        except ImportError:
            from single_execution_authority_kernel import get_seak  # type: ignore[import]
        seak = get_seak()
        if seak is not None:
            halt = getattr(seak, "emergency_halt", None)
            if callable(halt):
                halt(
                    f"terminal_writer_loss:{reason}",
                    source="terminal_writer_loss_latch",
                )
                logger.critical(
                    "SEAK_HALT_DIAGNOSTIC reason=terminal_writer_loss "
                    "source=terminal_writer_loss_latch "
                    "halt_reason=%s",
                    reason,
                )
    except Exception as exc:
        logger.critical(
            "TERMINAL_WRITER_LOSS_SEAK_HALT_FAILED err=%s", exc, exc_info=True
        )


def _signal_global_shutdown() -> None:
    try:
        try:
            from bot.bootstrap_utils import signal_shutdown
        except ImportError:
            from bootstrap_utils import signal_shutdown  # type: ignore[import]
        signal_shutdown()
    except Exception as exc:
        logger.debug(
            "TERMINAL_WRITER_LOSS_SHUTDOWN_SIGNAL_FAILED err=%s", exc, exc_info=True
        )


def _request_exit_75(reason: str) -> None:
    try:
        try:
            from bot.bot_main import request_process_exit
        except ImportError:
            from bot_main import request_process_exit  # type: ignore[import]
        request_process_exit(
            f"terminal_writer_loss:{reason}",
            exit_code=75,
            terminal_startup_failure=False,
        )
        logger.critical(
            "PROCESS_EXIT_REQUESTED exit_code=75 reason=terminal_writer_loss:%s "
            "restart_required=true",
            reason,
        )
    except Exception as exc:
        logger.critical(
            "TERMINAL_WRITER_LOSS_EXIT_REQUEST_FAILED err=%s — "
            "process may remain alive without forced exit",
            exc,
            exc_info=True,
        )


def _arm_forced_restart(reason: str) -> None:
    """Schedule os._exit(75) after a short grace period as final bound."""
    grace_s = 15.0
    try:
        grace_s = float(
            os.environ.get("NIJA_WRITER_AUTHORITY_RESTART_GRACE_S", "15") or 15
        )
    except (TypeError, ValueError):
        pass

    def _forced_exit() -> None:
        logger.critical(
            "WRITER_AUTHORITY_FORCED_RESTART reason=%s exit_code=75 "
            "(forced after %.1fs grace)",
            reason,
            grace_s,
        )
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass
        os._exit(75)

    timer = threading.Timer(grace_s, _forced_exit)
    timer.name = "terminal-writer-loss-forced-restart"
    timer.daemon = True
    timer.start()
    logger.critical(
        "WRITER_AUTHORITY_RESTART_SCHEDULED reason=terminal_writer_loss:%s "
        "grace_s=%.1f writer_unavailable=true",
        reason,
        grace_s,
    )


def private_io_suppressed(context: str = "") -> bool:
    """Return True when private I/O should be suppressed after terminal loss.

    Private-I/O workers (Kraken, etc.) must call this at every boundary and
    emit PRIVATE_IO_SUPPRESSED then return without performing the HTTP call.
    """
    if _latched or os.environ.get(PRIVATE_IO_STOP_FLAG) == "1":
        logger.critical(
            "PRIVATE_IO_SUPPRESSED context=%s latched=%s flag=%s",
            context,
            _latched,
            os.environ.get(PRIVATE_IO_STOP_FLAG),
        )
        return True
    return False


def reset_for_test() -> None:
    """Reset latch state for unit tests only.  Never call in production."""
    global _latched, _latch_reason, _latch_source, _latch_timestamp, _latch_writer_generation
    with _LATCH_LOCK:
        _latched = False
        _latch_reason = ""
        _latch_source = ""
        _latch_timestamp = 0.0
        _latch_writer_generation = ""
    os.environ.pop(PRIVATE_IO_STOP_FLAG, None)
