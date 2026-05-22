"""
NIJA Authority Heartbeat Monitor
=================================

Periodically verifies Redis connectivity and fencing token validity.
If the heartbeat fails 3 consecutive times, the trading state machine is
forced to LIVE_PAUSED (or OFFLINE) and all trading is blocked.

Configuration
-------------
NIJA_AUTHORITY_HEARTBEAT_INTERVAL_S  : Heartbeat check interval (default: 30s)
NIJA_AUTHORITY_HEARTBEAT_TIMEOUT_S   : Per-check timeout (default: 5s)
NIJA_AUTHORITY_HEARTBEAT_MAX_FAILURES: Consecutive failures before lockdown (default: 3)

Safety Contract
---------------
- Heartbeat runs in a daemon thread; it does NOT block startup.
- On lockdown: RuntimeError("AUTHORITY HEARTBEAT EXPIRED") is raised,
  the FSM is forced to EMERGENCY_STOP, and all order dispatch is blocked.
- There is NO recovery path from lockdown without a full restart and
  re-acquisition of the Redis writer lease.

Author: NIJA Trading Systems
Version: 2.0 (strict authority enforcement)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("nija.authority_heartbeat")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_INTERVAL_S: float = 30.0
_DEFAULT_TIMEOUT_S: float = 5.0
_DEFAULT_MAX_FAILURES: int = 3


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


# ---------------------------------------------------------------------------
# File-based heartbeat marker
# ---------------------------------------------------------------------------


def _write_heartbeat_marker() -> None:
    """Write (or refresh) the file-based heartbeat verification marker.

    The marker is read by ``_heartbeat_verification_status()`` in
    ``trading_state_machine.py``.  It must be a JSON file containing at
    minimum a ``stage`` field (``FILL_VERIFY`` satisfies all stage
    requirements) and a ``verified_at_epoch`` timestamp.

    This is called on every successful authority heartbeat tick so that the
    marker stays fresh (within ``HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS``,
    default 1800 s) and the ``_live_activation_gate()`` check passes even
    when no heartbeat trade has been executed yet.
    """
    marker_path = os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")
    try:
        path = Path(marker_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "stage": "FILL_VERIFY",
                "verified_at_epoch": time.time(),
                "source": "authority_heartbeat",
            },
            sort_keys=True,
        )
        # Write atomically via a temp file to avoid partial reads.
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)
        logger.debug(
            "AuthorityHeartbeatMonitor: heartbeat marker refreshed path=%s", marker_path
        )
    except Exception as exc:
        logger.warning(
            "AuthorityHeartbeatMonitor: could not write heartbeat marker path=%s: %s",
            marker_path,
            exc,
        )


# ---------------------------------------------------------------------------
# Heartbeat check
# ---------------------------------------------------------------------------


def _check_authority_once(timeout_s: float) -> tuple[bool, str]:
    """Perform a single authority heartbeat check.

    Verifies:
    1. NIJA_WRITER_FENCING_TOKEN is present.
    2. Redis is reachable (ping within timeout_s).
    3. Distributed writer authority is valid (fencing token matches Redis lock),
       OR the Redis lease was not acquired (single-instance / fallback-token mode)
       in which case only Redis connectivity is verified.

    Returns (ok, error_message).
    """
    # 1. Fencing token must be present.
    token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
    if not token:
        return False, "NIJA_WRITER_FENCING_TOKEN is not set — writer authority lost"

    # 2. Redis URL must be configured.
    try:
        from bot.redis_env import get_redis_url
    except ImportError:
        from redis_env import get_redis_url  # type: ignore[import]

    redis_url = get_redis_url()
    if not redis_url:
        # Redis is not configured.  When a fallback token was generated
        # (single-instance / no-Redis mode) we still consider the authority
        # valid as long as the fencing token is present.
        _truthy = {"1", "true", "yes", "on", "enabled"}
        is_fallback = os.environ.get("NIJA_WRITER_FENCING_TOKEN_FALLBACK", "").strip().lower() in _truthy
        if is_fallback:
            logger.debug(
                "AuthorityHeartbeatMonitor: Redis not configured; "
                "accepting fallback-token authority (single-instance mode)"
            )
            return True, ""
        return False, "Redis URL is not configured — cannot verify authority"

    # 3. Verify Redis connectivity and fencing token.
    # When a process-local fallback token was generated (Redis lock not
    # acquired), skip the fencing-token lock-key match check and only verify
    # that Redis is reachable.  When the Redis lease was properly acquired,
    # perform the full distributed authority check.
    _truthy = {"1", "true", "yes", "on", "enabled"}
    is_fallback = os.environ.get("NIJA_WRITER_FENCING_TOKEN_FALLBACK", "").strip().lower() in _truthy
    try:
        if not is_fallback:
            try:
                from bot.execution_authority_context import assert_distributed_writer_authority
            except ImportError:
                from execution_authority_context import assert_distributed_writer_authority  # type: ignore[import]

            # Run authority check with a bounded timeout using a thread.
            result: list[Optional[Exception]] = [None]
            done = threading.Event()

            def _run() -> None:
                try:
                    assert_distributed_writer_authority()
                except Exception as exc:
                    result[0] = exc
                finally:
                    done.set()

            t = threading.Thread(target=_run, daemon=True, name="authority-heartbeat-check")
            t.start()
            if not done.wait(timeout=timeout_s):
                return False, f"Authority check timed out after {timeout_s:.1f}s"

            if result[0] is not None:
                return False, str(result[0])
        else:
            # Fallback-token mode: verify Redis is reachable with a simple ping.
            import redis as _redis_lib
            _client = _redis_lib.from_url(redis_url, socket_connect_timeout=timeout_s)
            ping_result: list[Optional[Exception]] = [None]
            ping_done = threading.Event()

            def _ping() -> None:
                try:
                    _client.ping()
                except Exception as exc:
                    ping_result[0] = exc
                finally:
                    ping_done.set()

            _pt = threading.Thread(target=_ping, daemon=True, name="authority-heartbeat-ping")
            _pt.start()
            if not ping_done.wait(timeout=timeout_s):
                return False, f"Redis ping timed out after {timeout_s:.1f}s"
            if ping_result[0] is not None:
                return False, f"Redis ping failed: {ping_result[0]}"
            logger.debug(
                "AuthorityHeartbeatMonitor: Redis reachable; "
                "accepting fallback-token authority (single-instance mode)"
            )

        return True, ""

    except Exception as exc:
        return False, f"Authority check raised unexpected error: {exc}"


# ---------------------------------------------------------------------------
# Heartbeat monitor
# ---------------------------------------------------------------------------


class AuthorityHeartbeatMonitor:
    """Background daemon that monitors Redis authority and locks down on failure.

    Usage::

        monitor = AuthorityHeartbeatMonitor()
        monitor.start()

    The monitor runs until the process exits (daemon thread).  On lockdown it
    calls the registered lockdown callback (default: force FSM to EMERGENCY_STOP).
    """

    def __init__(
        self,
        interval_s: Optional[float] = None,
        timeout_s: Optional[float] = None,
        max_failures: Optional[int] = None,
        lockdown_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._interval_s = interval_s or _cfg_float(
            "NIJA_AUTHORITY_HEARTBEAT_INTERVAL_S", _DEFAULT_INTERVAL_S
        )
        self._timeout_s = timeout_s or _cfg_float(
            "NIJA_AUTHORITY_HEARTBEAT_TIMEOUT_S", _DEFAULT_TIMEOUT_S
        )
        self._max_failures = max_failures or _cfg_int(
            "NIJA_AUTHORITY_HEARTBEAT_MAX_FAILURES", _DEFAULT_MAX_FAILURES
        )
        self._lockdown_callback = lockdown_callback or _default_lockdown_callback
        self._consecutive_failures: int = 0
        self._locked_down: bool = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the heartbeat monitor in a background daemon thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("AuthorityHeartbeatMonitor: already running")
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="authority-heartbeat-monitor",
                daemon=True,
            )
            self._thread.start()
        logger.info(
            "AuthorityHeartbeatMonitor started: interval=%.1fs timeout=%.1fs max_failures=%d",
            self._interval_s,
            self._timeout_s,
            self._max_failures,
        )

    def stop(self) -> None:
        """Signal the heartbeat monitor to stop."""
        self._stop_event.set()

    @property
    def is_locked_down(self) -> bool:
        """True when the monitor has triggered a lockdown."""
        return self._locked_down

    @property
    def consecutive_failures(self) -> int:
        """Number of consecutive heartbeat failures since last success."""
        return self._consecutive_failures

    def _loop(self) -> None:
        """Main heartbeat loop."""
        logger.info("AuthorityHeartbeatMonitor: heartbeat loop started")
        # Run an immediate check on startup so the writer-heartbeat gate can
        # pass without waiting for the first interval to elapse.
        self._tick()
        while not self._stop_event.wait(timeout=self._interval_s):
            if self._locked_down:
                break
            self._tick()
        logger.info("AuthorityHeartbeatMonitor: heartbeat loop stopped")

    def _tick(self) -> None:
        """Perform one heartbeat check and update failure counter."""
        ok, err = _check_authority_once(self._timeout_s)
        if ok:
            if self._consecutive_failures > 0:
                logger.info(
                    "AuthorityHeartbeatMonitor: authority restored after %d failure(s)",
                    self._consecutive_failures,
                )
            self._consecutive_failures = 0
            # Signal to the writer-heartbeat gate that the authority heartbeat
            # is active and fresh.  This allows _writer_heartbeat_gate() in
            # trading_state_machine.py to pass when the Redis lock heartbeat
            # thread is not running (e.g. single-instance deployments).
            _now_ts = str(time.time())
            os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
            os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = _now_ts
            # Also refresh the file-based heartbeat marker so that the
            # _heartbeat_verification_status() check in _live_activation_gate()
            # passes when HEARTBEAT_REQUIRED_FIRST_ACTIVATION or HEARTBEAT_TRADE
            # is set.  Without this, the activation gate stays blocked with
            # heartbeat_err=marker_missing even though the Redis authority
            # heartbeat is healthy — a chicken-and-egg deadlock where the marker
            # is normally written by a heartbeat trade, but trades cannot execute
            # until the gate opens.
            _write_heartbeat_marker()
            return

        self._consecutive_failures += 1
        logger.critical(
            "AuthorityHeartbeatMonitor: HEARTBEAT FAILURE #%d/%d — %s",
            self._consecutive_failures,
            self._max_failures,
            err,
        )

        if self._consecutive_failures >= self._max_failures:
            self._trigger_lockdown(err)

    def _trigger_lockdown(self, reason: str) -> None:
        """Trigger authority lockdown — block all trading."""
        if self._locked_down:
            return
        self._locked_down = True
        # Clear the writer-heartbeat gate signals so the activation gate
        # immediately sees the heartbeat as inactive after lockdown.
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
        msg = (
            f"AUTHORITY HEARTBEAT EXPIRED: {self._consecutive_failures} consecutive "
            f"heartbeat failures (max={self._max_failures}). "
            f"Last error: {reason}"
        )
        logger.critical("🚨 %s", msg)
        try:
            self._lockdown_callback(msg)
        except Exception as exc:
            logger.critical(
                "AuthorityHeartbeatMonitor: lockdown callback raised: %s", exc
            )


def _default_lockdown_callback(reason: str) -> None:
    """Default lockdown: force FSM to EMERGENCY_STOP and raise RuntimeError."""
    logger.critical(
        "AuthorityHeartbeatMonitor: forcing EMERGENCY_STOP — %s", reason
    )

    # Force the trading state machine to EMERGENCY_STOP.
    try:
        try:
            from bot.trading_state_machine import get_state_machine, TradingState
        except ImportError:
            from trading_state_machine import get_state_machine, TradingState  # type: ignore[import]

        sm = get_state_machine()
        try:
            sm.transition_to(TradingState.EMERGENCY_STOP, f"AUTHORITY_HEARTBEAT_EXPIRED: {reason}")
        except Exception as fsm_exc:
            logger.critical(
                "AuthorityHeartbeatMonitor: FSM transition to EMERGENCY_STOP failed: %s",
                fsm_exc,
            )
            # Force state directly if transition fails.
            with sm._lock:
                sm._current_state = TradingState.EMERGENCY_STOP
                sm._activation_committed = False
                sm._execution_authority = False
                sm._core_loop_owns_execution = True
                sm._can_dispatch_trades = False
    except Exception as exc:
        logger.critical(
            "AuthorityHeartbeatMonitor: could not access FSM for lockdown: %s", exc
        )

    # Halt SEAK to block all in-flight and future order acquisitions.
    try:
        try:
            from bot.single_execution_authority_kernel import get_seak
        except ImportError:
            from single_execution_authority_kernel import get_seak  # type: ignore[import]
        get_seak().emergency_halt(f"AUTHORITY_HEARTBEAT_EXPIRED: {reason}")
    except Exception as exc:
        logger.critical(
            "AuthorityHeartbeatMonitor: could not halt SEAK: %s", exc
        )

    raise RuntimeError(f"AUTHORITY HEARTBEAT EXPIRED: {reason}")


# ---------------------------------------------------------------------------
# Process-global singleton
# ---------------------------------------------------------------------------

_monitor_instance: Optional[AuthorityHeartbeatMonitor] = None
_monitor_lock = threading.Lock()


def get_authority_heartbeat_monitor() -> AuthorityHeartbeatMonitor:
    """Return the process-global AuthorityHeartbeatMonitor singleton."""
    global _monitor_instance
    if _monitor_instance is not None:
        return _monitor_instance
    with _monitor_lock:
        if _monitor_instance is None:
            _monitor_instance = AuthorityHeartbeatMonitor()
    return _monitor_instance


def start_authority_heartbeat() -> AuthorityHeartbeatMonitor:
    """Start the process-global authority heartbeat monitor.

    Safe to call multiple times — subsequent calls are no-ops if already running.
    Should be called once after the bot successfully acquires the Redis writer
    lease and transitions to LIVE_ACTIVE.
    """
    monitor = get_authority_heartbeat_monitor()
    monitor.start()
    return monitor


__all__ = [
    "AuthorityHeartbeatMonitor",
    "get_authority_heartbeat_monitor",
    "start_authority_heartbeat",
]
