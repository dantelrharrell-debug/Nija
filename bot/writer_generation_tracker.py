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

Generation sync recovery (heartbeat path)
------------------------------------------
When ``NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED=true``, a lighter-weight
recovery path is available during heartbeat validation.  Instead of immediately
triggering a full lock re-acquisition (which halts SEAK), the sync recovery:

1. Reads the current generation from Redis.
2. Resets the local ``NIJA_WRITER_LEASE_GENERATION`` env var to match Redis.
3. Clears any stale heartbeat failure state.
4. Logs a ``GENERATION_SYNC_RECOVERY`` event with before/after values.
5. Returns ``(True, "")`` so the heartbeat cycle continues without lockdown.

This self-healing path handles the common case where the local counter drifted
due to a transient Redis write failure or a deployment that did not cleanly
persist the generation.  It is safe because the Redis value is always the
authoritative source of truth — resetting local to match Redis restores
consistency without requiring a full lock re-acquisition.

Heartbeat integration
---------------------
``validate_generation_for_heartbeat()`` is called by
``authority_heartbeat._check_authority_once()`` on every heartbeat cycle.
A mismatch triggers immediate re-validation and is logged for the audit trail.

Configuration
-------------
NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED : Enable lightweight generation sync
    recovery during heartbeat validation (default: false).  When true, a
    generation mismatch resets the local counter to the Redis value and
    continues the heartbeat cycle rather than failing it.
NIJA_GENERATION_MISMATCH_AUTO_CLEAR_STALE : Enable auto-clear of stale
    generation state when the mismatch delta exceeds the configured threshold
    (default: false).  Analogous to NIJA_AUTO_CLEAR_STALE_RAILWAY_LOCK.
NIJA_GENERATION_MISMATCH_DELTA_THRESHOLD  : Minimum absolute difference between
    local and Redis generations that qualifies as a "large" mismatch eligible
    for auto-clear (default: 100).

Author: NIJA Trading Systems
Version: 1.1
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

# Minimum absolute delta between local and Redis generations that qualifies
# as a "large" mismatch eligible for auto-clear recovery.
_DEFAULT_MISMATCH_DELTA_THRESHOLD: int = 100

# Divergence threshold above which the "nuclear option" full reset is applied
# unconditionally, regardless of NIJA_GENERATION_MISMATCH_AUTO_CLEAR_STALE.
# A delta of 882339 vs 753 (≈881586) is orders of magnitude above this.
_NUCLEAR_RESET_DELTA_THRESHOLD: int = 1000

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_mismatch_lock = threading.Lock()
_last_mismatch_log_ts: float = 0.0
_mismatch_count: int = 0

# Tracks the last generation sync recovery timestamp to prevent rapid loops.
_last_sync_recovery_ts: float = 0.0
_sync_recovery_count: int = 0
_SYNC_RECOVERY_COOLDOWN_S: float = 30.0


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
# Generation sync recovery (lightweight heartbeat path)
# ---------------------------------------------------------------------------


def reset_generation_to_redis() -> tuple[bool, str]:
    """Force-reset the local generation counter to the current Redis value.

    This is the authoritative recovery entry point for severe generation
    divergence (e.g. local=882339 vs redis=753).  It reads the live Redis
    generation, resets ``NIJA_WRITER_LEASE_GENERATION`` to match, clears any
    stale watermark / expected-generation constraints, and logs a full audit
    trail of the before/after values.

    Unlike ``attempt_generation_sync_recovery()``, this function:
    - Does **not** require ``NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED=true``.
    - Does **not** enforce the sync-recovery cooldown.
    - Is safe to call unconditionally when the divergence is catastrophic.

    Returns
    -------
    (success, message)
        ``success=True`` when the local generation was successfully reset to
        the Redis value.  ``message`` contains a full audit description.
    """
    local_before = get_local_generation()
    redis_gen, err = get_redis_generation()

    if err:
        msg = (
            f"GENERATION_RESET_FAILED: could not read Redis generation "
            f"local_before={local_before} error={err}"
        )
        logger.critical(msg)
        return False, msg

    if redis_gen <= 0:
        msg = (
            f"GENERATION_RESET_FAILED: Redis generation is unusable "
            f"local_before={local_before} redis_gen={redis_gen}"
        )
        logger.critical(msg)
        return False, msg

    delta = abs(local_before - redis_gen)

    # Reset the primary local generation env var.
    os.environ[_LOCAL_GENERATION_ENV] = str(redis_gen)

    # Clear the monotonic watermark so the new value is not rejected as a
    # regression by any downstream monotonic-check logic.
    old_watermark = os.environ.get("NIJA_WRITER_LEASE_GENERATION_LAST", "<unset>")
    os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = str(redis_gen)

    # Clear any stale expected-generation constraint from a previous cycle.
    stale_expected = os.environ.get("NIJA_WRITER_LEASE_GENERATION_EXPECTED", "").strip()
    if stale_expected and stale_expected != str(redis_gen):
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION_EXPECTED", None)
        logger.warning(
            "GENERATION_RESET: cleared stale NIJA_WRITER_LEASE_GENERATION_EXPECTED=%s "
            "(now synced to redis=%d)",
            stale_expected,
            redis_gen,
        )

    logger.critical(
        "GENERATION_RESET: local generation force-reset to Redis value "
        "local_before=%d local_after=%d redis=%d delta=%d "
        "watermark_before=%s watermark_after=%d",
        local_before,
        redis_gen,
        redis_gen,
        delta,
        old_watermark,
        redis_gen,
    )

    msg = (
        f"generation_reset_ok local_before={local_before} local_after={redis_gen} "
        f"redis={redis_gen} delta={delta}"
    )
    return True, msg


def attempt_generation_sync_recovery(local: int, redis_gen: int) -> tuple[bool, str]:
    """Lightweight generation sync recovery for the heartbeat path.

    When ``NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED=true``, resets the local
    generation counter to match the authoritative Redis value.  This is a
    non-destructive operation — it does not halt SEAK or trigger a full lock
    re-acquisition.  It is safe because Redis is always the source of truth.

    Parameters
    ----------
    local:
        The locally-cached generation value that is out of sync.
    redis_gen:
        The current authoritative generation value from Redis.

    Returns
    -------
    (recovered, message)
        ``recovered=True`` when the local generation was successfully reset.
        ``message`` describes the outcome for logging.
    """
    global _last_sync_recovery_ts, _sync_recovery_count

    # Validate that the Redis generation is a positive, usable value before
    # any flag checks so we can apply the nuclear option unconditionally.
    if redis_gen <= 0:
        return False, f"redis_generation_unusable redis_gen={redis_gen}"

    delta = abs(local - redis_gen)

    # ── Nuclear option ────────────────────────────────────────────────────────
    # When the divergence is catastrophically large (e.g. local=882339 vs
    # redis=753, delta≈881586), bypass the recovery-enabled flag and the
    # cooldown entirely and delegate to reset_generation_to_redis().  This
    # handles the case where NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED was not
    # set and the lightweight path would have returned "recovery_disabled".
    if delta >= _NUCLEAR_RESET_DELTA_THRESHOLD:
        logger.critical(
            "GENERATION_SYNC_RECOVERY: NUCLEAR OPTION triggered — "
            "divergence delta=%d exceeds threshold=%d "
            "(local=%d redis=%d) — forcing full generation reset",
            delta,
            _NUCLEAR_RESET_DELTA_THRESHOLD,
            local,
            redis_gen,
        )
        success, reset_msg = reset_generation_to_redis()
        if success:
            with _mismatch_lock:
                _last_sync_recovery_ts = time.monotonic()
                _sync_recovery_count += 1
                count = _sync_recovery_count
            return True, (
                f"nuclear_reset_applied delta={delta} "
                f"threshold={_NUCLEAR_RESET_DELTA_THRESHOLD} "
                f"recovery_count={count} {reset_msg}"
            )
        return False, f"nuclear_reset_failed: {reset_msg}"

    if not _env_truthy("NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED"):
        return False, "recovery_disabled"

    # Enforce cooldown to prevent rapid recovery loops.
    now = time.monotonic()
    with _mismatch_lock:
        since_last = now - _last_sync_recovery_ts
        if since_last < _SYNC_RECOVERY_COOLDOWN_S and _sync_recovery_count > 0:
            return False, (
                f"recovery_cooldown_active cooldown_remaining_s="
                f"{_SYNC_RECOVERY_COOLDOWN_S - since_last:.1f}"
            )

    # Check for large-delta auto-clear eligibility.

    try:
        delta_threshold = max(
            1,
            int(os.getenv("NIJA_GENERATION_MISMATCH_DELTA_THRESHOLD", "") or _DEFAULT_MISMATCH_DELTA_THRESHOLD),
        )
    except (TypeError, ValueError):
        delta_threshold = _DEFAULT_MISMATCH_DELTA_THRESHOLD

    is_large_mismatch = delta >= delta_threshold
    auto_clear_enabled = _env_truthy("NIJA_GENERATION_MISMATCH_AUTO_CLEAR_STALE")

    logger.critical(
        "GENERATION_SYNC_RECOVERY: initiating generation sync "
        "local_before=%d redis=%d delta=%d is_large_mismatch=%s auto_clear_enabled=%s",
        local,
        redis_gen,
        delta,
        is_large_mismatch,
        auto_clear_enabled,
    )

    # For very large mismatches with auto-clear enabled, also reset the
    # "last seen" generation watermark so the monotonic regression check
    # does not block the newly synced value.
    if is_large_mismatch and auto_clear_enabled:
        old_last = os.environ.get("NIJA_WRITER_LEASE_GENERATION_LAST", "0")
        os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = str(redis_gen)
        logger.warning(
            "GENERATION_SYNC_RECOVERY: NIJA_GENERATION_MISMATCH_AUTO_CLEAR_STALE=true — "
            "cleared stale generation watermark "
            "NIJA_WRITER_LEASE_GENERATION_LAST %s → %d (delta=%d threshold=%d)",
            old_last,
            redis_gen,
            delta,
            delta_threshold,
        )

    # Reset local generation to match Redis.
    old_local = os.environ.get(_LOCAL_GENERATION_ENV, "<unset>")
    os.environ[_LOCAL_GENERATION_ENV] = str(redis_gen)

    # Also clear any stale expected-generation constraint that may have been
    # set by a previous deployment cycle.
    stale_expected = os.environ.get("NIJA_WRITER_LEASE_GENERATION_EXPECTED", "").strip()
    if stale_expected and stale_expected != str(redis_gen):
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION_EXPECTED", None)
        logger.warning(
            "GENERATION_SYNC_RECOVERY: cleared stale NIJA_WRITER_LEASE_GENERATION_EXPECTED=%s "
            "(now synced to redis=%d)",
            stale_expected,
            redis_gen,
        )

    with _mismatch_lock:
        _last_sync_recovery_ts = time.monotonic()
        _sync_recovery_count += 1
        count = _sync_recovery_count

    logger.critical(
        "GENERATION_SYNC_RECOVERY: local generation reset "
        "local_before=%s local_after=%d redis=%d delta=%d recovery_count=%d",
        old_local,
        redis_gen,
        redis_gen,
        delta,
        count,
    )

    return True, (
        f"generation_synced local_before={old_local} local_after={redis_gen} "
        f"redis={redis_gen} delta={delta} recovery_count={count}"
    )


# ---------------------------------------------------------------------------
# Heartbeat integration
# ---------------------------------------------------------------------------


def validate_generation_for_heartbeat() -> tuple[bool, str]:
    """Validate generation number during a heartbeat cycle.

    Designed to be called from ``authority_heartbeat._check_authority_once()``.
    Returns ``(ok, error_message)`` in the same format as the heartbeat check.

    When a mismatch is detected:
    - Logs a CRITICAL audit event with both local and Redis generation values.
    - If ``NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED=true``, attempts a
      lightweight generation sync recovery (resets local to Redis value) and
      returns ``(True, "")`` so the heartbeat cycle continues without lockdown.
    - Otherwise returns ``(False, error_message)`` so the heartbeat failure
      counter increments and eventually triggers lockdown if the mismatch
      persists.

    Diagnostics logged on every mismatch:
    - Local generation value
    - Redis generation value
    - Absolute delta between the two
    - Redis connection state
    - Recovery eligibility and outcome
    """
    # Skip generation check when Redis is not configured (fallback/single-instance mode).
    try:
        from bot.redis_env import get_redis_url
    except ImportError:
        from redis_env import get_redis_url  # type: ignore[import]

    redis_url = get_redis_url()
    if not redis_url:
        return True, ""

    # Skip when the lease has not been acquired yet (startup phase).
    _truthy = {"1", "true", "yes", "on", "enabled"}
    lease_acquired = os.environ.get("NIJA_WRITER_LEASE_ACQUIRED", "").strip() in _truthy
    is_fallback = os.environ.get("NIJA_WRITER_FENCING_TOKEN_FALLBACK", "").strip().lower() in _truthy
    if is_fallback:
        return True, ""
    if not lease_acquired:
        return True, ""

    ok, local, redis_gen, detail = validate_generation()

    if not ok:
        # Determine whether this is a true mismatch or a Redis read error.
        is_mismatch = "mismatch" in detail

        # Always log detailed diagnostics on any generation check failure.
        redis_reachable = redis_url is not None
        try:
            client, _conn_err = _connect_redis(timeout_s=2)
            redis_reachable = client is not None and not _conn_err
        except Exception:
            redis_reachable = False

        logger.critical(
            "WRITER_GENERATION_TRACKER: heartbeat generation check FAILED "
            "local=%d redis=%d delta=%d is_mismatch=%s redis_reachable=%s detail=%s "
            "recovery_enabled=%s",
            local,
            redis_gen,
            abs(local - redis_gen),
            is_mismatch,
            redis_reachable,
            detail,
            _env_truthy("NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED"),
        )

        if is_mismatch:
            _log_generation_mismatch(local, redis_gen, detail)
            logger.critical(
                "WRITER_GENERATION_TRACKER: heartbeat generation mismatch detected — "
                "local=%d redis=%d delta=%d — attempting sync recovery",
                local,
                redis_gen,
                abs(local - redis_gen),
            )

            # Attempt lightweight sync recovery when enabled.
            recovered, recovery_msg = attempt_generation_sync_recovery(local, redis_gen)
            if recovered:
                logger.critical(
                    "WRITER_GENERATION_TRACKER: GENERATION_SYNC_RECOVERY succeeded — "
                    "heartbeat cycle continuing without lockdown. %s",
                    recovery_msg,
                )
                return True, ""

            logger.warning(
                "WRITER_GENERATION_TRACKER: generation sync recovery not applied (%s) — "
                "heartbeat failure will be counted",
                recovery_msg,
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
    "reset_generation_to_redis",
    "attempt_generation_sync_recovery",
    "attempt_lock_reacquisition",
    "check_and_handle_generation_mismatch",
]
