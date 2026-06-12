"""
NIJA Graceful Handoff Protocol
================================

Implements lease-based distributed lock with generation tracking and graceful
shutdown for Railway restart scenarios.

When a Railway restart occurs (SIGTERM), the old instance:
  1. Stops accepting new trades
  2. Waits for in-flight trades to complete (timeout: NIJA_GRACEFUL_SHUTDOWN_TIMEOUT_S)
  3. Logs final state and positions
  4. Releases the distributed lock explicitly (does not wait for TTL)
  5. Exits cleanly

The new instance:
  1. Detects the old instance's lock in Redis
  2. Checks if the lock is still valid (TTL > 0)
  3. If valid, waits for the old instance to release (timeout: NIJA_HANDOFF_WAIT_TIMEOUT_S)
  4. If timeout, forcefully acquires the lock with a new generation number

Generation Tracking
-------------------
- Each lock acquisition increments the global generation counter in Redis
- All trades are tagged with the current generation number
- A mismatch between trade generation and current generation = stale trade

Configuration
-------------
NIJA_WRITER_LOCK_TTL_S          : Lock TTL in seconds (default: 30)
NIJA_WRITER_HEARTBEAT_INTERVAL_S: Heartbeat renewal interval (default: 5)
NIJA_GRACEFUL_SHUTDOWN_TIMEOUT_S: Max wait for in-flight trades on shutdown (default: 30)
NIJA_HANDOFF_WAIT_TIMEOUT_S     : Max wait for old instance to release lock (default: 60)

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("nija.graceful_handoff")

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_TRUTHY = {"1", "true", "yes", "on", "enabled"}


def _cfg_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.environ.get(name, str(default)) or str(default)))
    except (TypeError, ValueError):
        return default


def _cfg_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default)) or str(default)))
    except (TypeError, ValueError):
        return default


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Default configuration values
# ---------------------------------------------------------------------------

_DEFAULT_LOCK_TTL_S: float = 30.0
_DEFAULT_HEARTBEAT_INTERVAL_S: float = 5.0
_DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_S: float = 30.0
_DEFAULT_HANDOFF_WAIT_TIMEOUT_S: float = 60.0

# Redis key for the global generation counter
_GENERATION_KEY = "nija:lease:generation"

# Redis key prefix for the graceful-release signal
_RELEASE_SIGNAL_KEY = "nija:writer_lock:released"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class HandoffState:
    """Snapshot of the current handoff / lock state."""

    instance_id: str
    generation: int
    lock_key: str
    lock_ttl_s: float
    acquired_at: float
    last_heartbeat_at: float
    is_shutting_down: bool
    shutdown_started_at: Optional[float]
    in_flight_count: int


@dataclass
class AcquireResult:
    """Result of a lock acquisition attempt."""

    acquired: bool
    generation: int
    token: str
    instance_id: str
    waited_for_release: bool = False
    forced: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# In-flight trade tracker
# ---------------------------------------------------------------------------


class InFlightTracker:
    """Thread-safe counter for in-flight (open) trade operations.

    Callers wrap trade execution with ``track()`` so the graceful shutdown
    handler can wait for all in-flight operations to complete before releasing
    the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count: int = 0
        self._drained = threading.Event()
        self._drained.set()  # starts drained

    def increment(self) -> None:
        with self._lock:
            self._count += 1
            self._drained.clear()

    def decrement(self) -> None:
        with self._lock:
            self._count = max(0, self._count - 1)
            if self._count == 0:
                self._drained.set()

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def wait_drained(self, timeout_s: float) -> bool:
        """Block until count reaches zero or timeout expires.

        Returns True when drained, False on timeout.
        """
        return self._drained.wait(timeout=timeout_s)

    def track(self, fn: Callable[[], Any]) -> Any:
        """Execute *fn* while holding an in-flight slot."""
        self.increment()
        try:
            return fn()
        finally:
            self.decrement()


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


def _get_redis_client(timeout_s: int = 3):
    """Return a Redis client using the configured URL."""
    try:
        from bot.redis_env import get_redis_url
    except ImportError:
        from redis_env import get_redis_url  # type: ignore[import]

    redis_url = get_redis_url()
    if not redis_url:
        return None

    try:
        try:
            from bot.redis_runtime import connect_redis_with_fallback
        except ImportError:
            from redis_runtime import connect_redis_with_fallback  # type: ignore[import]

        client, _ = connect_redis_with_fallback(
            url=redis_url,
            decode_responses=True,
            socket_timeout=timeout_s,
            socket_connect_timeout=timeout_s,
            retries=1,
            delay_s=0.0,
            log=lambda msg: logger.debug("handoff redis: %s", msg),
        )
        return client
    except Exception as exc:
        logger.warning("GracefulHandoff: Redis client unavailable: %s", exc)
        return None


def _resolve_lock_key() -> str:
    """Return the configured writer lock key."""
    import hashlib

    scope = os.getenv("NIJA_WRITER_LOCK_SCOPE", "").strip()
    if not scope:
        raw = (
            os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
            or os.environ.get("KRAKEN_API_KEY", "").strip()
            or "default"
        )
        scope = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return os.getenv("NIJA_WRITER_LOCK_KEY", "").strip() or f"nija:writer_lock:{scope}"


def _resolve_meta_key() -> str:
    """Return the configured writer lock metadata key."""
    import hashlib

    scope = os.getenv("NIJA_WRITER_LOCK_SCOPE", "").strip()
    if not scope:
        raw = (
            os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
            or os.environ.get("KRAKEN_API_KEY", "").strip()
            or "default"
        )
        scope = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return (
        os.getenv("NIJA_WRITER_LOCK_META_KEY", "").strip()
        or f"nija:writer_lock_meta:{scope}"
    )


def _current_instance_id() -> str:
    """Return the stable instance identifier for this process."""
    try:
        from bot.instance_identity import current_instance_identity
    except ImportError:
        from instance_identity import current_instance_identity  # type: ignore[import]
    return current_instance_identity().get("instance_id", "") or f"pid-{os.getpid()}"


# ---------------------------------------------------------------------------
# Generation management
# ---------------------------------------------------------------------------


def _increment_generation(client) -> int:
    """Atomically increment and return the global lease generation counter."""
    try:
        new_gen = int(client.incr(_GENERATION_KEY))
        # Persist the generation without TTL — it must survive restarts.
        # The key is intentionally permanent so generation numbers are
        # monotonically increasing across all restarts.
        logger.info(
            "GracefulHandoff: generation incremented to %d (key=%s)",
            new_gen,
            _GENERATION_KEY,
        )
        return new_gen
    except Exception as exc:
        logger.warning("GracefulHandoff: generation increment failed: %s", exc)
        return 0


def _read_generation(client) -> int:
    """Read the current global lease generation counter."""
    try:
        raw = client.get(_GENERATION_KEY)
        if raw is None:
            return 0
        return int(str(raw).strip())
    except Exception as exc:
        logger.warning("GracefulHandoff: generation read failed: %s", exc)
        return 0


def get_current_generation() -> int:
    """Return the current lease generation from Redis (0 if unavailable)."""
    client = _get_redis_client()
    if client is None:
        return 0
    return _read_generation(client)


# ---------------------------------------------------------------------------
# Lock acquisition with handoff detection
# ---------------------------------------------------------------------------


def acquire_writer_lock_with_handoff(
    *,
    instance_id: Optional[str] = None,
    lock_ttl_s: Optional[float] = None,
    handoff_wait_timeout_s: Optional[float] = None,
) -> AcquireResult:
    """Acquire the distributed writer lock with graceful handoff detection.

    If the lock is currently held by another instance:
      1. Waits up to *handoff_wait_timeout_s* for the old instance to release.
      2. If the old instance releases cleanly, acquires with the next generation.
      3. If timeout expires, forcefully acquires with the next generation.

    Parameters
    ----------
    instance_id:
        Stable identifier for this instance (defaults to current_instance_id()).
    lock_ttl_s:
        Lock TTL in seconds (defaults to NIJA_WRITER_LOCK_TTL_S or 30s).
    handoff_wait_timeout_s:
        Max seconds to wait for old instance to release (defaults to
        NIJA_HANDOFF_WAIT_TIMEOUT_S or 60s).

    Returns
    -------
    AcquireResult with acquired=True on success.
    """
    _instance_id = instance_id or _current_instance_id()
    _ttl_s = lock_ttl_s or _cfg_float("NIJA_WRITER_LOCK_TTL_S", _DEFAULT_LOCK_TTL_S)
    _wait_timeout_s = handoff_wait_timeout_s or _cfg_float(
        "NIJA_HANDOFF_WAIT_TIMEOUT_S", _DEFAULT_HANDOFF_WAIT_TIMEOUT_S
    )
    _ttl_ms = int(_ttl_s * 1000)

    lock_key = _resolve_lock_key()
    meta_key = _resolve_meta_key()

    client = _get_redis_client()
    if client is None:
        logger.warning(
            "GracefulHandoff: Redis unavailable — cannot acquire distributed lock"
        )
        return AcquireResult(
            acquired=False,
            generation=0,
            token="",
            instance_id=_instance_id,
            error="redis_unavailable",
        )

    token = str(uuid.uuid4().hex)
    lock_value = f"{token}:{_instance_id}"
    waited_for_release = False
    forced = False

    # ── Check for existing lock ───────────────────────────────────────────────
    existing_raw = ""
    existing_ttl_ms = -2
    try:
        existing_raw = str(client.get(lock_key) or "")
        existing_ttl_ms = int(client.pttl(lock_key) or -2)
    except Exception as exc:
        logger.warning("GracefulHandoff: lock probe failed: %s", exc)

    if existing_raw and existing_ttl_ms > 0:
        # Another instance holds a valid lock — wait for graceful release.
        logger.info(
            "GracefulHandoff: lock held by another instance (ttl=%dms) — "
            "waiting up to %.0fs for graceful release (key=%s)",
            existing_ttl_ms,
            _wait_timeout_s,
            lock_key,
        )
        release_signal_key = f"{_RELEASE_SIGNAL_KEY}:{lock_key}"
        deadline = time.monotonic() + _wait_timeout_s
        released = False

        while time.monotonic() < deadline:
            # Check if the lock has been released (key gone or TTL expired).
            try:
                current_raw = str(client.get(lock_key) or "")
                current_ttl = int(client.pttl(lock_key) or -2)
            except Exception as exc:
                logger.warning("GracefulHandoff: lock poll failed: %s", exc)
                time.sleep(1.0)
                continue

            if not current_raw or current_ttl == -2:
                logger.info(
                    "GracefulHandoff: old instance released lock (key=%s)", lock_key
                )
                released = True
                waited_for_release = True
                break

            # Also check for explicit release signal written by old instance.
            try:
                signal_val = str(client.get(release_signal_key) or "")
                if signal_val:
                    logger.info(
                        "GracefulHandoff: explicit release signal detected "
                        "(key=%s signal=%s)",
                        release_signal_key,
                        signal_val[:32],
                    )
                    released = True
                    waited_for_release = True
                    break
            except Exception:
                pass

            remaining = deadline - time.monotonic()
            logger.debug(
                "GracefulHandoff: waiting for lock release (remaining=%.1fs ttl=%dms)",
                remaining,
                current_ttl,
            )
            time.sleep(min(1.0, max(0.1, remaining)))

        if not released:
            logger.warning(
                "GracefulHandoff: handoff wait timeout (%.0fs) — "
                "forcefully acquiring lock with new generation (key=%s)",
                _wait_timeout_s,
                lock_key,
            )
            forced = True

    # ── Acquire the lock ──────────────────────────────────────────────────────
    try:
        # Increment generation before acquiring so the new instance always
        # has a strictly higher generation than any stale in-flight trades.
        new_generation = _increment_generation(client)

        # Use SET NX PX for atomic acquire.
        acquired = bool(
            client.set(lock_key, lock_value, nx=True, px=_ttl_ms)
        )

        if not acquired and (forced or waited_for_release):
            # Force-acquire: delete the stale lock and retry once.  Even when an
            # explicit release signal was observed, SET NX can still race with a
            # stale key; after the handoff wait has completed we must not sit in
            # another old-instance delay.
            forced = True
            logger.warning(
                "GracefulHandoff: force-deleting stale lock (key=%s)", lock_key
            )
            client.delete(lock_key)
            acquired = bool(
                client.set(lock_key, lock_value, nx=True, px=_ttl_ms)
            )

        if not acquired:
            logger.error(
                "GracefulHandoff: lock acquisition failed (key=%s)", lock_key
            )
            return AcquireResult(
                acquired=False,
                generation=new_generation,
                token=token,
                instance_id=_instance_id,
                waited_for_release=waited_for_release,
                forced=forced,
                error="set_nx_failed",
            )

        # Write metadata alongside the lock for diagnostics.
        meta_payload = json.dumps(
            {
                "token": token,
                "instance_id": _instance_id,
                "generation": new_generation,
                "acquired_at": time.time(),
                "heartbeat_at": time.time(),
                "lock_ttl_s": _ttl_s,
            }
        )
        try:
            client.set(meta_key, meta_payload, px=_ttl_ms * 2)
        except Exception as meta_exc:
            logger.warning(
                "GracefulHandoff: metadata write failed (non-fatal): %s", meta_exc
            )

        # Persist generation and token to environment for downstream gates.
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = token
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = str(new_generation)
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
        os.environ["NIJA_LOCK_ACQUIRED"] = "true"
        os.environ["NIJA_WRITER_LOCK_TTL_S"] = str(_ttl_s)

        logger.info(
            "GracefulHandoff: lock acquired — instance=%s generation=%d "
            "token_prefix=%s ttl=%.0fs waited=%s forced=%s",
            _instance_id,
            new_generation,
            token[:8],
            _ttl_s,
            waited_for_release,
            forced,
        )
        return AcquireResult(
            acquired=True,
            generation=new_generation,
            token=token,
            instance_id=_instance_id,
            waited_for_release=waited_for_release,
            forced=forced,
        )

    except Exception as exc:
        logger.error("GracefulHandoff: lock acquisition error: %s", exc)
        return AcquireResult(
            acquired=False,
            generation=0,
            token=token,
            instance_id=_instance_id,
            waited_for_release=waited_for_release,
            forced=forced,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Lock heartbeat (renewal)
# ---------------------------------------------------------------------------


class LockHeartbeat:
    """Background thread that periodically renews the distributed writer lock.

    The heartbeat extends the lock TTL before it expires, preventing the lock
    from being claimed by a new instance while the current instance is still
    active.

    If the heartbeat fails to renew the lock (e.g. Redis unreachable or the
    lock was stolen), it sets the ``lost`` event so the caller can react.
    """

    def __init__(
        self,
        *,
        lock_key: str,
        lock_value: str,
        lock_ttl_s: float,
        meta_key: str,
        meta_payload_fn: Callable[[], str],
        interval_s: Optional[float] = None,
        on_lock_lost: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._lock_key = lock_key
        self._lock_value = lock_value
        self._lock_ttl_s = lock_ttl_s
        self._lock_ttl_ms = int(lock_ttl_s * 1000)
        self._meta_key = meta_key
        self._meta_payload_fn = meta_payload_fn
        self._interval_s = interval_s or _cfg_float(
            "NIJA_WRITER_HEARTBEAT_INTERVAL_S", _DEFAULT_HEARTBEAT_INTERVAL_S
        )
        self._on_lock_lost = on_lock_lost
        self._stop_event = threading.Event()
        self._lost_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_failures: int = 0
        self._last_success_ts: float = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the heartbeat thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="nija-lock-heartbeat",
                daemon=True,
            )
            self._thread.start()
        logger.info(
            "LockHeartbeat: started (interval=%.1fs ttl=%.0fs key=%s)",
            self._interval_s,
            self._lock_ttl_s,
            self._lock_key,
        )

    def stop(self) -> None:
        """Signal the heartbeat thread to stop."""
        self._stop_event.set()

    @property
    def is_lost(self) -> bool:
        """True when the lock has been lost (stolen or expired)."""
        return self._lost_event.is_set()

    @property
    def last_success_ts(self) -> float:
        return self._last_success_ts

    def _loop(self) -> None:
        """Main heartbeat loop."""
        while not self._stop_event.wait(timeout=self._interval_s):
            self._tick()

    def _tick(self) -> None:
        """Renew the lock TTL and update the heartbeat timestamp."""
        # Update the alive timestamp on every iteration (even on Redis failure)
        # so the two-tier freshness check in execution_authority_context can
        # distinguish a dead thread from a live thread with a Redis outage.
        now_ts = time.time()
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = str(now_ts)

        client = _get_redis_client(timeout_s=2)
        if client is None:
            self._consecutive_failures += 1
            logger.warning(
                "LockHeartbeat: Redis unavailable (failures=%d)",
                self._consecutive_failures,
            )
            return

        try:
            # Verify we still own the lock before renewing.
            current_value = str(client.get(self._lock_key) or "")
            if current_value != self._lock_value:
                self._consecutive_failures += 1
                reason = (
                    f"lock_stolen (current={current_value[:32]!r} "
                    f"expected={self._lock_value[:32]!r})"
                    if current_value
                    else "lock_expired"
                )
                logger.critical(
                    "LockHeartbeat: LOCK LOST — %s (key=%s failures=%d)",
                    reason,
                    self._lock_key,
                    self._consecutive_failures,
                )
                self._lost_event.set()
                if self._on_lock_lost is not None:
                    try:
                        self._on_lock_lost(reason)
                    except Exception as cb_exc:
                        logger.error(
                            "LockHeartbeat: on_lock_lost callback raised: %s", cb_exc
                        )
                return

            # Renew the TTL.
            client.pexpire(self._lock_key, self._lock_ttl_ms)

            # Update metadata heartbeat timestamp.
            try:
                meta_payload = self._meta_payload_fn()
                client.set(
                    self._meta_key, meta_payload, px=self._lock_ttl_ms * 2
                )
            except Exception as meta_exc:
                logger.debug(
                    "LockHeartbeat: metadata update failed (non-fatal): %s", meta_exc
                )

            self._consecutive_failures = 0
            self._last_success_ts = now_ts
            os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = str(now_ts)
            os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
            logger.debug(
                "LockHeartbeat: renewed (key=%s ttl=%.0fs)",
                self._lock_key,
                self._lock_ttl_s,
            )

        except Exception as exc:
            self._consecutive_failures += 1
            logger.warning(
                "LockHeartbeat: renewal failed (failures=%d): %s",
                self._consecutive_failures,
                exc,
            )


# ---------------------------------------------------------------------------
# Graceful shutdown handler
# ---------------------------------------------------------------------------


class GracefulShutdownHandler:
    """SIGTERM handler that implements the graceful handoff protocol.

    On SIGTERM (Railway restart signal):
      1. Sets the shutdown flag — new trade entries are blocked.
      2. Waits for in-flight trades to complete (up to shutdown_timeout_s).
      3. Logs final state and positions.
      4. Writes an explicit release signal to Redis.
      5. Deletes the distributed writer lock.
      6. Exits cleanly with code 0.

    Usage::

        handler = GracefulShutdownHandler(
            in_flight_tracker=tracker,
            lock_key=lock_key,
            lock_value=lock_value,
        )
        handler.install()
    """

    def __init__(
        self,
        *,
        in_flight_tracker: InFlightTracker,
        lock_key: str,
        lock_value: str,
        meta_key: str,
        heartbeat: Optional[LockHeartbeat] = None,
        shutdown_timeout_s: Optional[float] = None,
        state_dump_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        on_shutdown_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        self._tracker = in_flight_tracker
        self._lock_key = lock_key
        self._lock_value = lock_value
        self._meta_key = meta_key
        self._heartbeat = heartbeat
        self._shutdown_timeout_s = shutdown_timeout_s or _cfg_float(
            "NIJA_GRACEFUL_SHUTDOWN_TIMEOUT_S", _DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_S
        )
        self._state_dump_fn = state_dump_fn
        self._on_shutdown_complete = on_shutdown_complete
        self._shutdown_event = threading.Event()
        self._shutdown_started_at: Optional[float] = None
        self._installed = False

    def install(self) -> None:
        """Install SIGTERM and SIGINT signal handlers."""
        if self._installed:
            return
        try:
            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)
            self._installed = True
            logger.info(
                "GracefulShutdownHandler: installed SIGTERM/SIGINT handlers "
                "(timeout=%.0fs lock_key=%s)",
                self._shutdown_timeout_s,
                self._lock_key,
            )
        except (OSError, ValueError) as exc:
            # signal.signal() can fail when called from a non-main thread.
            logger.warning(
                "GracefulShutdownHandler: could not install signal handlers "
                "(must be called from main thread): %s",
                exc,
            )

    @property
    def is_shutting_down(self) -> bool:
        """True when a shutdown has been initiated."""
        return self._shutdown_event.is_set()

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle SIGTERM / SIGINT — initiate graceful shutdown."""
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        logger.critical(
            "GracefulShutdownHandler: %s received — initiating graceful shutdown "
            "(in_flight=%d timeout=%.0fs)",
            sig_name,
            self._tracker.count,
            self._shutdown_timeout_s,
        )
        self._shutdown_event.set()
        self._shutdown_started_at = time.time()

        # Run shutdown in a separate thread so the signal handler returns quickly.
        t = threading.Thread(
            target=self._run_shutdown,
            name="nija-graceful-shutdown",
            daemon=False,  # non-daemon so it completes before process exits
        )
        t.start()

    def _run_shutdown(self) -> None:
        """Execute the full graceful shutdown sequence."""
        start_ts = time.monotonic()

        # Step 1: Stop accepting new trades (shutdown flag already set).
        logger.critical(
            "GracefulShutdown [1/5]: new trade entries blocked "
            "(in_flight=%d)",
            self._tracker.count,
        )

        # Step 2: Wait for in-flight trades to complete.
        logger.critical(
            "GracefulShutdown [2/5]: waiting for %d in-flight trade(s) "
            "(timeout=%.0fs)",
            self._tracker.count,
            self._shutdown_timeout_s,
        )
        drained = self._tracker.wait_drained(timeout_s=self._shutdown_timeout_s)
        if drained:
            logger.critical(
                "GracefulShutdown [2/5]: all in-flight trades completed "
                "(elapsed=%.1fs)",
                time.monotonic() - start_ts,
            )
        else:
            logger.warning(
                "GracefulShutdown [2/5]: shutdown timeout — %d trade(s) still "
                "in-flight after %.0fs; proceeding with lock release",
                self._tracker.count,
                self._shutdown_timeout_s,
            )

        # Step 3: Log final state and positions.
        logger.critical("GracefulShutdown [3/5]: logging final state")
        if self._state_dump_fn is not None:
            try:
                state = self._state_dump_fn()
                logger.critical(
                    "GracefulShutdown [3/5]: final_state=%s",
                    json.dumps(state, default=str),
                )
            except Exception as dump_exc:
                logger.warning(
                    "GracefulShutdown [3/5]: state dump failed: %s", dump_exc
                )

        # Step 4: Stop heartbeat and write explicit release signal.
        logger.critical("GracefulShutdown [4/5]: releasing distributed lock")
        if self._heartbeat is not None:
            self._heartbeat.stop()

        client = _get_redis_client(timeout_s=3)
        if client is not None:
            try:
                # Write explicit release signal so the new instance can detect
                # the clean handoff without waiting for TTL expiry.
                release_signal_key = f"{_RELEASE_SIGNAL_KEY}:{self._lock_key}"
                release_payload = json.dumps(
                    {
                        "released_by": _current_instance_id(),
                        "released_at": time.time(),
                        "generation": int(
                            os.environ.get("NIJA_WRITER_LEASE_GENERATION", "0") or 0
                        ),
                        "reason": "graceful_shutdown",
                    }
                )
                # Signal expires after 2× the handoff wait timeout so the new
                # instance always has time to read it.
                _handoff_wait_s = _cfg_float(
                    "NIJA_HANDOFF_WAIT_TIMEOUT_S", _DEFAULT_HANDOFF_WAIT_TIMEOUT_S
                )
                client.set(
                    release_signal_key,
                    release_payload,
                    px=int(_handoff_wait_s * 2 * 1000),
                )
                logger.info(
                    "GracefulShutdown [4/5]: release signal written (key=%s)",
                    release_signal_key,
                )
            except Exception as sig_exc:
                logger.warning(
                    "GracefulShutdown [4/5]: release signal write failed: %s", sig_exc
                )

            try:
                # Delete the lock only if we still own it (compare-and-delete).
                current_value = str(client.get(self._lock_key) or "")
                if current_value == self._lock_value:
                    client.delete(self._lock_key)
                    logger.critical(
                        "GracefulShutdown [4/5]: lock released (key=%s)",
                        self._lock_key,
                    )
                else:
                    logger.warning(
                        "GracefulShutdown [4/5]: lock already transferred to new "
                        "instance — skipping delete (key=%s current=%s)",
                        self._lock_key,
                        current_value[:32] if current_value else "<empty>",
                    )
            except Exception as del_exc:
                logger.warning(
                    "GracefulShutdown [4/5]: lock delete failed: %s", del_exc
                )

            try:
                # Clear the metadata key.
                client.delete(self._meta_key)
            except Exception:
                pass
        else:
            logger.warning(
                "GracefulShutdown [4/5]: Redis unavailable — lock will expire via TTL"
            )

        # Clear environment flags so downstream gates immediately see the
        # authority as invalid (prevents stale env from allowing trades after
        # the lock is released).
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
        os.environ.pop("NIJA_WRITER_LEASE_ACQUIRED", None)
        os.environ.pop("NIJA_LOCK_ACQUIRED", None)
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"

        elapsed = time.monotonic() - start_ts
        logger.critical(
            "GracefulShutdown [5/5]: shutdown complete (elapsed=%.1fs) — exiting",
            elapsed,
        )

        if self._on_shutdown_complete is not None:
            try:
                self._on_shutdown_complete()
            except Exception as cb_exc:
                logger.error(
                    "GracefulShutdown [5/5]: on_shutdown_complete callback raised: %s",
                    cb_exc,
                )

        # Step 5: Exit cleanly.
        os._exit(0)


# ---------------------------------------------------------------------------
# Generation-tagged trade guard
# ---------------------------------------------------------------------------


def is_generation_current(trade_generation: int) -> bool:
    """Return True when *trade_generation* matches the current lease generation.

    A mismatch indicates a stale trade from a previous instance that should
    not be executed by the current instance.

    Parameters
    ----------
    trade_generation:
        The generation number embedded in the trade at creation time.

    Returns
    -------
    bool — True when the trade is from the current generation.
    """
    local_gen_raw = os.environ.get("NIJA_WRITER_LEASE_GENERATION", "0") or "0"
    try:
        local_gen = int(local_gen_raw)
    except (TypeError, ValueError):
        local_gen = 0

    if local_gen <= 0 or trade_generation <= 0:
        # Cannot verify — allow by default to avoid blocking on missing data.
        return True

    return trade_generation == local_gen


# ---------------------------------------------------------------------------
# High-level coordinator
# ---------------------------------------------------------------------------


class GracefulHandoffCoordinator:
    """Top-level coordinator that wires together lock acquisition, heartbeat,
    in-flight tracking, and graceful shutdown.

    Typical usage in bot startup::

        coordinator = GracefulHandoffCoordinator()
        result = coordinator.startup()
        if not result.acquired:
            logger.critical("Could not acquire writer lock — aborting")
            sys.exit(1)

        # Register the shutdown handler (must be called from main thread).
        coordinator.install_shutdown_handler()

        # Wrap trade execution:
        with coordinator.in_flight_scope():
            execute_trade(...)

    The coordinator is a singleton — use :func:`get_handoff_coordinator`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._acquire_result: Optional[AcquireResult] = None
        self._heartbeat: Optional[LockHeartbeat] = None
        self._shutdown_handler: Optional[GracefulShutdownHandler] = None
        self._in_flight = InFlightTracker()
        self._started = False

    def startup(
        self,
        *,
        instance_id: Optional[str] = None,
        lock_ttl_s: Optional[float] = None,
        handoff_wait_timeout_s: Optional[float] = None,
    ) -> AcquireResult:
        """Acquire the writer lock and start the heartbeat thread.

        Returns the AcquireResult.  Callers should check ``result.acquired``
        before proceeding.
        """
        with self._lock:
            if self._started:
                logger.warning(
                    "GracefulHandoffCoordinator: startup() called more than once — "
                    "returning cached result"
                )
                return self._acquire_result or AcquireResult(
                    acquired=False,
                    generation=0,
                    token="",
                    instance_id=instance_id or _current_instance_id(),
                    error="already_started",
                )

            result = acquire_writer_lock_with_handoff(
                instance_id=instance_id,
                lock_ttl_s=lock_ttl_s,
                handoff_wait_timeout_s=handoff_wait_timeout_s,
            )
            self._acquire_result = result

            if result.acquired:
                _ttl_s = lock_ttl_s or _cfg_float(
                    "NIJA_WRITER_LOCK_TTL_S", _DEFAULT_LOCK_TTL_S
                )
                lock_key = _resolve_lock_key()
                meta_key = _resolve_meta_key()
                lock_value = f"{result.token}:{result.instance_id}"

                def _meta_payload() -> str:
                    return json.dumps(
                        {
                            "token": result.token,
                            "instance_id": result.instance_id,
                            "generation": result.generation,
                            "acquired_at": time.time(),
                            "heartbeat_at": time.time(),
                            "lock_ttl_s": _ttl_s,
                        }
                    )

                self._heartbeat = LockHeartbeat(
                    lock_key=lock_key,
                    lock_value=lock_value,
                    lock_ttl_s=_ttl_s,
                    meta_key=meta_key,
                    meta_payload_fn=_meta_payload,
                    on_lock_lost=self._on_lock_lost,
                )
                self._heartbeat.start()

                self._shutdown_handler = GracefulShutdownHandler(
                    in_flight_tracker=self._in_flight,
                    lock_key=lock_key,
                    lock_value=lock_value,
                    meta_key=meta_key,
                    heartbeat=self._heartbeat,
                )

                self._started = True
                logger.info(
                    "GracefulHandoffCoordinator: startup complete — "
                    "generation=%d instance=%s",
                    result.generation,
                    result.instance_id,
                )
            else:
                logger.error(
                    "GracefulHandoffCoordinator: lock acquisition failed — %s",
                    result.error,
                )

            return result

    def install_shutdown_handler(self) -> None:
        """Install SIGTERM/SIGINT handlers (must be called from main thread)."""
        if self._shutdown_handler is not None:
            self._shutdown_handler.install()
        else:
            logger.warning(
                "GracefulHandoffCoordinator: install_shutdown_handler() called "
                "before startup() — no handler installed"
            )

    def in_flight_scope(self):
        """Context manager that tracks an in-flight trade operation."""
        return _InFlightScope(self._in_flight, self)

    @property
    def is_shutting_down(self) -> bool:
        """True when a graceful shutdown has been initiated."""
        if self._shutdown_handler is not None:
            return self._shutdown_handler.is_shutting_down
        return False

    @property
    def current_generation(self) -> int:
        """Return the generation number acquired at startup."""
        if self._acquire_result is not None:
            return self._acquire_result.generation
        return 0

    @property
    def in_flight_count(self) -> int:
        """Return the number of currently in-flight trade operations."""
        return self._in_flight.count

    def _on_lock_lost(self, reason: str) -> None:
        """Called by the heartbeat when the lock is lost."""
        logger.critical(
            "GracefulHandoffCoordinator: LOCK LOST — %s — halting trading", reason
        )
        # Halt the SEAK kernel to prevent any further order dispatch.
        try:
            try:
                from bot.single_execution_authority_kernel import get_seak
            except ImportError:
                from single_execution_authority_kernel import get_seak  # type: ignore[import]
            get_seak().emergency_halt(f"lock_lost:{reason}")
        except Exception as halt_exc:
            logger.error(
                "GracefulHandoffCoordinator: SEAK halt failed: %s", halt_exc
            )

        # Clear authority environment flags.
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
        os.environ.pop("NIJA_WRITER_LEASE_ACQUIRED", None)
        os.environ.pop("NIJA_LOCK_ACQUIRED", None)
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"


class _InFlightScope:
    """Context manager returned by GracefulHandoffCoordinator.in_flight_scope()."""

    def __init__(
        self, tracker: InFlightTracker, coordinator: GracefulHandoffCoordinator
    ) -> None:
        self._tracker = tracker
        self._coordinator = coordinator

    def __enter__(self) -> "_InFlightScope":
        if self._coordinator.is_shutting_down:
            raise RuntimeError(
                "GracefulHandoff: trade rejected — graceful shutdown in progress"
            )
        self._tracker.increment()
        return self

    def __exit__(self, *args: Any) -> None:
        self._tracker.decrement()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_coordinator_instance: Optional[GracefulHandoffCoordinator] = None
_coordinator_lock = threading.Lock()


def get_handoff_coordinator() -> GracefulHandoffCoordinator:
    """Return the singleton GracefulHandoffCoordinator instance."""
    global _coordinator_instance
    if _coordinator_instance is None:
        with _coordinator_lock:
            if _coordinator_instance is None:
                _coordinator_instance = GracefulHandoffCoordinator()
    return _coordinator_instance
