"""
NIJA Writer Generation Tracker
================================

Authority lineage tracking via monotonic generation numbers.

Each time the bot acquires the distributed writer lock, the Lua lease script
atomically increments ``nija:lease:generation`` in Redis (the canonical
generation counter).  This module provides the validation layer that compares
the locally-cached generation (stored in ``NIJA_WRITER_LEASE_GENERATION``) to
the live Redis value before every trade execution.

If the two values diverge the bot has lost authority continuity — either the
lock expired and was re-acquired by another instance, or the lock was silently
lost.  The tracker detects this immediately and triggers the recovery protocol.

Redis key
---------
``NIJA_WRITER_GENERATION`` (env var) → Redis key name.
Default: ``nija:lease:generation``  (same key used by the Lua lease scripts in
``_PerKeyRedisBackend``).  Override via ``NIJA_LEASE_GENERATION_KEY``.

Recovery protocol
-----------------
On generation mismatch:

1. Log a CRITICAL event with both generation numbers.
2. Halt SEAK to stop all pending order acquisitions.
3. Attempt to re-acquire the distributed writer lock (with timeout).
4. If re-acquisition succeeds → increment generation, resume trading.
5. If re-acquisition fails → enter FAILED state (EMERGENCY_STOP).

Heartbeat integration
---------------------
``validate_generation_for_heartbeat()`` is called by
``authority_heartbeat._check_authority_once()`` on every heartbeat cycle.
A mismatch triggers immediate re-validation and is logged for the audit trail.

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("nija.writer_generation_tracker")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default Redis key for the generation counter.  Must match the Lua constant
# ``_LEASE_GENERATION_KEY`` in ``_PerKeyRedisBackend``.
_DEFAULT_GENERATION_REDIS_KEY = "nija:lease:generation"

# Env var that holds the locally-cached generation number (set by
# ``_publish_lock_acquired_state`` in ``_PerKeyRedisBackend``).
_LOCAL_GENERATION_ENV = "NIJA_WRITER_LEASE_GENERATION"

# How long to wait for lock re-acquisition during recovery (seconds).
_DEFAULT_REACQUIRE_TIMEOUT_S: float = 10.0

# Minimum seconds between consecutive mismatch log lines (audit throttle).
_MISMATCH_LOG_THROTTLE_S: float = 5.0

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_mismatch_lock = threading.Lock()
_last_mismatch_log_ts: float = 0.0
_mismatch_count: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generation_redis_key() -> str:
    """Return the Redis key used for the generation counter."""
    return (
        os.getenv("NIJA_LEASE_GENERATION_KEY", "").strip()
        or _DEFAULT_GENERATION_REDIS_KEY
    )


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "enabled", "on"}


def _connect_redis(timeout_s: int = 2):
    """Build a Redis client using the canonical authority connection helper."""
    try:
        from bot.redis_env import get_redis_url
    except ImportError:
        from redis_env import get_redis_url  # type: ignore[import]

    redis_url = get_redis_url()
    if not redis_url:
        return None, "redis_url_not_configured"

    try:
        try:
            from bot.execution_authority_context import _connect_redis_for_authority
        except ImportError:
            from execution_authority_context import _connect_redis_for_authority  # type: ignore[import]
        return _connect_redis_for_authority(redis_url, timeout_s=timeout_s), ""
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Core generation API
# ---------------------------------------------------------------------------


def get_local_generation() -> int:
    """Return the locally-cached generation number from the environment.

    This is the generation that was stored when the writer lock was last
    acquired by this process.  Returns 0 when not set.
    """
    raw = os.getenv(_LOCAL_GENERATION_ENV, "").strip()
    try:
        return max(0, int(raw)) if raw else 0
    except (TypeError, ValueError):
        return 0


def get_redis_generation() -> tuple[int, str]:
    """Read the current generation number from Redis.

    Returns
    -------
    (generation, error)
        ``generation`` is the current Redis value (0 on error or missing).
        ``error`` is an empty string on success, or a description of the
        failure.
    """
    client, err = _connect_redis(timeout_s=2)
    if client is None:
        return 0, err or "redis_unavailable"

    generation_key = _generation_redis_key()
    try:
        raw = client.get(generation_key)
        if raw is None:
            return 0, "generation_key_missing"
        return max(0, int(str(raw).strip())), ""
    except Exception as exc:
        return 0, f"redis_read_error:{exc}"


def validate_generation() -> tuple[bool, int, int, str]:
    """Compare the local generation against the live Redis value.

    Returns
    -------
    (ok, local_generation, redis_generation, error)
        ``ok`` is True when both values are positive and equal.
        ``error`` is empty on success, or describes the mismatch/failure.
    """
    local = get_local_generation()
    redis_gen, err = get_redis_generation()

    if err:
        return False, local, redis_gen, f"redis_read_failed:{err}"

    if local <= 0:
        return False, local, redis_gen, "local_generation_not_set"

    if redis_gen <= 0:
        return False, local, redis_gen, "redis_generation_not_set"

    if local != redis_gen:
        return (
            False,
            local,
            redis_gen,
            f"generation_mismatch:local={local} redis={redis_gen}",
        )

    return True, local, redis_gen, ""


# ---------------------------------------------------------------------------
# Mismatch audit logging
# ---------------------------------------------------------------------------


def _log_generation_mismatch(local: int, redis_gen: int, detail: str) -> None:
    """Log a generation mismatch event, throttled to avoid log storms."""
    global _last_mismatch_log_ts, _mismatch_count

    now = time.monotonic()
    with _mismatch_lock:
        _mismatch_count += 1
        count = _mismatch_count
        since_last = now - _last_mismatch_log_ts
        if since_last < _MISMATCH_LOG_THROTTLE_S and count > 1:
            return
        _last_mismatch_log_ts = now

    logger.critical(
        "WRITER_GENERATION_MISMATCH: authority lineage broken "
        "local_generation=%d redis_generation=%d detail=%s mismatch_count=%d",
        local,
        redis_gen,
        detail,
        count,
    )


# ---------------------------------------------------------------------------
# Recovery protocol
# ---------------------------------------------------------------------------


def attempt_lock_reacquisition(
    timeout_s: float = _DEFAULT_REACQUIRE_TIMEOUT_S,
) -> tuple[bool, int, str]:
    """Attempt to re-acquire the distributed writer lock after a generation mismatch.

    Steps
    -----
    1. Halt SEAK to stop all pending order acquisitions.
    2. Try to re-acquire the writer lease via the DistributedNonceManager.
    3. If successful, the Lua script atomically increments the generation
       counter and ``_publish_lock_acquired_state`` updates the env var.
    4. Return (success, new_generation, error).

    This function is intentionally conservative: it does NOT resume trading
    automatically.  The caller (``check_and_handle_generation_mismatch``) is
    responsible for deciding whether to resume or enter FAILED state.
    """
    # Step 1: Halt SEAK immediately to stop all new order acquisitions.
    try:
        try:
            from bot.single_execution_authority_kernel import get_seak
        except ImportError:
            from single_execution_authority_kernel import get_seak  # type: ignore[import]
        get_seak().emergency_halt("WRITER_GENERATION_MISMATCH: halting for lock re-acquisition")
        logger.critical(
            "WRITER_GENERATION_TRACKER: SEAK halted — stopping all order acquisitions "
            "pending lock re-acquisition"
        )
    except Exception as exc:
        logger.critical(
            "WRITER_GENERATION_TRACKER: could not halt SEAK during recovery: %s", exc
        )

    # Step 2: Attempt lock re-acquisition.
    platform_key = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
    )
    if not platform_key:
        return False, 0, "no_platform_key_for_reacquisition"

    deadline = time.monotonic() + timeout_s
    last_error = "timeout"

    while time.monotonic() < deadline:
        try:
            try:
                from bot.distributed_nonce_manager import (
                    get_distributed_nonce_manager,
                    make_api_key_id,
                )
            except ImportError:
                from distributed_nonce_manager import (  # type: ignore[import]
                    get_distributed_nonce_manager,
                    make_api_key_id,
                )

            key_id = make_api_key_id(platform_key)
            manager = get_distributed_nonce_manager()
            new_version = manager.ensure_writer_lock(key_id)

            # ``ensure_writer_lock`` calls ``_publish_lock_acquired_state``
            # which sets NIJA_WRITER_LEASE_GENERATION.  Read it back to confirm.
            new_local = get_local_generation()
            if new_local > 0:
                logger.critical(
                    "WRITER_GENERATION_TRACKER: lock re-acquired successfully "
                    "new_generation=%d",
                    new_local,
                )
                return True, new_local, ""

            # Fallback: use the version returned directly.
            if isinstance(new_version, int) and new_version > 0:
                os.environ[_LOCAL_GENERATION_ENV] = str(new_version)
                logger.critical(
                    "WRITER_GENERATION_TRACKER: lock re-acquired (version fallback) "
                    "new_generation=%d",
                    new_version,
                )
                return True, new_version, ""

            last_error = "reacquisition_returned_zero_version"
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "WRITER_GENERATION_TRACKER: lock re-acquisition attempt failed: %s", exc
            )
            time.sleep(0.5)

    return False, 0, f"lock_reacquisition_failed:{last_error}"


def check_and_handle_generation_mismatch() -> bool:
    """Full recovery protocol for a detected generation mismatch.

    Called when ``validate_generation()`` returns ``ok=False`` due to a
    mismatch (not a Redis read error).

    Protocol
    --------
    1. Log CRITICAL event with both generation numbers.
    2. Halt SEAK (stop all pending orders).
    3. Attempt lock re-acquisition with timeout.
    4. If successful → increment generation env var, resume SEAK, return True.
    5. If failed → force FSM to EMERGENCY_STOP, return False.

    Returns
    -------
    bool
        True when recovery succeeded and trading may resume.
        False when recovery failed and the bot has entered FAILED state.
    """
    ok, local, redis_gen, detail = validate_generation()
    if ok:
        # No mismatch — nothing to do.
        return True

    _log_generation_mismatch(local, redis_gen, detail)

    # Attempt re-acquisition.
    reacquired, new_generation, reacq_error = attempt_lock_reacquisition()

    if reacquired:
        logger.critical(
            "WRITER_GENERATION_TRACKER: recovery succeeded — "
            "new_generation=%d resuming trading",
            new_generation,
        )
        # Resume SEAK so trading can continue.
        try:
            try:
                from bot.single_execution_authority_kernel import get_seak
            except ImportError:
                from single_execution_authority_kernel import get_seak  # type: ignore[import]
            get_seak().resume(caller="writer_generation_tracker")
            logger.critical(
                "WRITER_GENERATION_TRACKER: SEAK resumed after successful lock re-acquisition"
            )
        except Exception as exc:
            logger.critical(
                "WRITER_GENERATION_TRACKER: could not resume SEAK after recovery: %s", exc
            )
        return True

    # Recovery failed — enter FAILED state.
    logger.critical(
        "WRITER_GENERATION_TRACKER: recovery FAILED — entering EMERGENCY_STOP "
        "local_generation=%d redis_generation=%d reacq_error=%s",
        local,
        redis_gen,
        reacq_error,
    )
    try:
        try:
            from bot.trading_state_machine import get_state_machine, TradingState
        except ImportError:
            from trading_state_machine import get_state_machine, TradingState  # type: ignore[import]

        sm = get_state_machine()
        reason = (
            f"WRITER_GENERATION_MISMATCH: local={local} redis={redis_gen} "
            f"reacq_error={reacq_error}"
        )
        try:
            sm.transition_to(TradingState.EMERGENCY_STOP, reason)
        except Exception as fsm_exc:
            logger.critical(
                "WRITER_GENERATION_TRACKER: FSM transition to EMERGENCY_STOP failed: %s",
                fsm_exc,
            )
            with sm._lock:
                sm._current_state = TradingState.EMERGENCY_STOP
                sm._activation_committed = False
                sm._execution_authority = False
                sm._can_dispatch_trades = False
    except Exception as exc:
        logger.critical(
            "WRITER_GENERATION_TRACKER: could not access FSM for EMERGENCY_STOP: %s", exc
        )

    return False


# ---------------------------------------------------------------------------
# Heartbeat integration
# ---------------------------------------------------------------------------


def validate_generation_for_heartbeat() -> tuple[bool, str]:
    """Validate generation number during a heartbeat cycle.

    Designed to be called from ``authority_heartbeat._check_authority_once()``.
    Returns ``(ok, error_message)`` in the same format as the heartbeat check.

    When a mismatch is detected:
    - Logs a CRITICAL audit event.
    - Returns ``(False, error_message)`` so the heartbeat failure counter
      increments and eventually triggers lockdown if the mismatch persists.

    Note: This function does NOT trigger the full recovery protocol on its own.
    The heartbeat monitor's lockdown callback handles recovery when the failure
    threshold is reached.  This keeps the heartbeat check fast and non-blocking.
    """
    # Skip generation check when Redis is not configured (fallback/single-instance mode).
    try:
        from bot.redis_env import get_redis_url
    except ImportError:
        from redis_env import get_redis_url  # type: ignore[import]

    if not get_redis_url():
        return True, ""

    # Skip when the lease has not been acquired yet (startup phase).
    _truthy = {"1", "true", "yes", "on", "enabled"}
    lease_acquired = os.environ.get("NIJA_WRITER_LEASE_ACQUIRED", "").strip() in _truthy
    is_fallback = os.environ.get("NIJA_WRITER_FENCING_TOKEN_FALLBACK", "").strip().lower() in _truthy
    if not lease_acquired and not is_fallback:
        return True, ""

    ok, local, redis_gen, detail = validate_generation()

    if not ok:
        # Only log mismatches (not Redis read errors) as CRITICAL.
        if "mismatch" in detail:
            _log_generation_mismatch(local, redis_gen, detail)
            logger.critical(
                "WRITER_GENERATION_TRACKER: heartbeat generation mismatch detected — "
                "triggering re-validation local=%d redis=%d",
                local,
                redis_gen,
            )
        else:
            logger.warning(
                "WRITER_GENERATION_TRACKER: heartbeat generation check failed (non-mismatch): %s",
                detail,
            )
        return False, f"generation_mismatch:{detail}"

    logger.debug(
        "WRITER_GENERATION_TRACKER: heartbeat generation OK generation=%d", local
    )
    return True, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "get_local_generation",
    "get_redis_generation",
    "validate_generation",
    "validate_generation_for_heartbeat",
    "attempt_lock_reacquisition",
    "check_and_handle_generation_mismatch",
]
