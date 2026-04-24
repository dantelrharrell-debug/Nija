"""
NIJA Connection Stability Manager
===================================

Provides proactive connection health monitoring and automatic reconnection
for broker API connections.

Features
--------
* Per-broker connection watchdog that runs in a background daemon thread.
* Automatic reconnection with exponential backoff when a connection drops.
* HTTP connection-pool configuration helpers (pool_connections, pool_maxsize,
  keep-alive, retry) that callers can apply to a ``requests.Session``.
* Thread-safe state management using standard ``threading`` primitives.
* Singleton per broker via ``get_connection_stability_manager(broker_name)``.

Typical usage
-------------
::

    from bot.connection_stability_manager import get_connection_stability_manager

    csm = get_connection_stability_manager("coinbase")
    csm.register_broker(
        broker=coinbase_broker_instance,
        reconnect_fn=coinbase_broker_instance.connect,
    )
    csm.start_watchdog()         # launch background health-check thread

    # Apply connection-pool settings to a requests.Session:
    import requests
    session = requests.Session()
    csm.apply_connection_pool(session)

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("nija.connection_stability")


# ---------------------------------------------------------------------------
# Connection state
# ---------------------------------------------------------------------------

class ConnectionState(str, Enum):
    CONNECTED    = "connected"      # Healthy, last probe succeeded
    DEGRADED     = "degraded"       # Probe failed at least once; still running
    DISCONNECTED = "disconnected"   # Consecutive probe failures hit threshold
    RECONNECTING = "reconnecting"   # Reconnect attempt in progress


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ConnectionPoolConfig:
    """
    Parameters for the HTTP connection pool attached to a ``requests.Session``.

    These values are sized for the Coinbase Advanced Trade API (up to ~10 req/s
    burst) while also being conservative enough for Kraken / Binance.
    """
    pool_connections: int = 4       # Number of urllib3 connection pools
    pool_maxsize: int = 10          # Connections kept alive per pool
    max_retries: int = 3            # urllib3-level retries (transport only)
    connect_timeout: float = 10.0   # Seconds to wait for TCP connection
    read_timeout: float = 60.0      # Seconds to wait for server response (increased 30s→60s for Kraken latency)
    backoff_factor: float = 0.5     # urllib3 retry backoff factor


@dataclass
class WatchdogConfig:
    """Configuration for the connection watchdog thread."""
    check_interval_s: float = 30.0       # Seconds between health probes
    failure_threshold: int = 3           # Consecutive failures → DISCONNECTED
    reconnect_base_delay_s: float = 5.0  # Base delay before first reconnect
    reconnect_max_delay_s: float = 120.0 # Cap for exponential backoff
    reconnect_backoff_factor: float = 2.0
    max_reconnect_attempts: int = 10     # 0 → unlimited


# ---------------------------------------------------------------------------
# Per-broker manager
# ---------------------------------------------------------------------------

class ConnectionStabilityManager:
    """
    Manages connection stability for a single named broker.

    This class:
    1. Maintains connection state (CONNECTED / DEGRADED / DISCONNECTED).
    2. Runs an optional background watchdog thread that probes connection
       health and triggers automatic reconnection on repeated failure.
    3. Exposes helpers to configure HTTP connection pooling.
    """

    def __init__(
        self,
        broker_name: str,
        watchdog_cfg: Optional[WatchdogConfig] = None,
        pool_cfg: Optional[ConnectionPoolConfig] = None,
    ) -> None:
        self.broker_name = broker_name
        self._watchdog_cfg = watchdog_cfg or WatchdogConfig()
        self._pool_cfg = pool_cfg or ConnectionPoolConfig()

        # Connection state
        self._state = ConnectionState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._consecutive_failures = 0
        self._total_reconnects = 0
        self._last_probe_time: Optional[float] = None
        self._last_success_time: Optional[float] = None
        self._last_failure_reason: Optional[str] = None

        # Registered broker objects
        self._broker: Optional[Any] = None
        self._reconnect_fn: Optional[Callable[[], bool]] = None
        self._health_probe_fn: Optional[Callable[[], bool]] = None

        # Watchdog thread management
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_broker(
        self,
        broker: Any,
        reconnect_fn: Callable[[], bool],
        health_probe_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Register a broker instance and its connection callbacks.

        If a broker is already registered this call is a no-op so that
        repeated connect() calls during polling / watchdog re-entry do not
        re-register the same broker multiple times.

        Args:
            broker: Broker object (used for logging context only).
            reconnect_fn: Callable that (re-)establishes the connection and
                returns ``True`` on success.  Typically ``broker.connect``.
            health_probe_fn: Optional lightweight callable that returns
                ``True`` when the connection is alive.  If omitted the
                watchdog calls ``reconnect_fn`` to test liveness.
        """
        if self._broker is not None:
            logger.debug(
                f"[{self.broker_name}] Broker already registered — skipping duplicate registration"
            )
            return
        self._broker = broker
        self._reconnect_fn = reconnect_fn
        self._health_probe_fn = health_probe_fn
        logger.info(f"🔌 [{self.broker_name}] Broker registered with ConnectionStabilityManager")

    def mark_connected(self) -> None:
        """Signal that the broker is now connected (call after successful connect())."""
        with self._state_lock:
            self._state = ConnectionState.CONNECTED
            self._consecutive_failures = 0
            self._last_success_time = time.monotonic()
        logger.debug(f"[{self.broker_name}] Connection state → CONNECTED")

    def mark_disconnected(self, reason: str = "") -> None:
        """Signal that the broker has lost its connection."""
        with self._state_lock:
            self._state = ConnectionState.DISCONNECTED
            self._last_failure_reason = reason
        logger.warning(f"⚠️ [{self.broker_name}] Connection state → DISCONNECTED: {reason}")

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        with self._state_lock:
            return self._state

    @property
    def is_connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    def get_status(self) -> Dict[str, Any]:
        """Return a status dictionary suitable for dashboards / health endpoints."""
        with self._state_lock:
            return {
                "broker": self.broker_name,
                "state": self._state.value,
                "consecutive_failures": self._consecutive_failures,
                "total_reconnects": self._total_reconnects,
                "last_probe_time": self._last_probe_time,
                "last_success_time": self._last_success_time,
                "last_failure_reason": self._last_failure_reason,
                "watchdog_running": (
                    self._watchdog_thread is not None
                    and self._watchdog_thread.is_alive()
                ),
            }

    # ------------------------------------------------------------------
    # Connection pool helpers
    # ------------------------------------------------------------------

    def apply_connection_pool(self, session: Any) -> None:
        """
        Configure a ``requests.Session`` with optimised connection-pool
        settings (pool size, keep-alive, timeouts, transport-level retries).

        Args:
            session: A ``requests.Session`` instance to configure.
        """
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            retry_strategy = Retry(
                total=self._pool_cfg.max_retries,
                backoff_factor=self._pool_cfg.backoff_factor,
                # Only retry on transient transport-level errors; HTTP errors
                # are handled at the application layer by RetryHandler.
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST", "DELETE"],
                raise_on_status=False,
            )

            adapter = HTTPAdapter(
                pool_connections=self._pool_cfg.pool_connections,
                pool_maxsize=self._pool_cfg.pool_maxsize,
                max_retries=retry_strategy,
            )

            session.mount("https://", adapter)
            session.mount("http://", adapter)

            logger.info(
                f"🌐 [{self.broker_name}] Connection pool applied: "
                f"pool_connections={self._pool_cfg.pool_connections}, "
                f"pool_maxsize={self._pool_cfg.pool_maxsize}, "
                f"max_retries={self._pool_cfg.max_retries}"
            )
        except ImportError:
            logger.warning(
                f"[{self.broker_name}] requests/urllib3 not available; "
                "connection pool settings not applied"
            )

    def get_default_timeouts(self) -> tuple:
        """
        Return a ``(connect_timeout, read_timeout)`` tuple for use with
        ``requests`` calls, e.g. ``requests.get(url, timeout=csm.get_default_timeouts())``.
        """
        return (self._pool_cfg.connect_timeout, self._pool_cfg.read_timeout)

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def start_watchdog(self) -> None:
        """
        Start the background watchdog thread.

        The watchdog periodically probes the broker connection and
        triggers automatic reconnection when consecutive failures exceed
        the configured threshold.  Safe to call multiple times — only one
        thread will be running at a time.
        """
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            logger.debug(f"[{self.broker_name}] Watchdog already running")
            return

        self._stop_event.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name=f"csm-watchdog-{self.broker_name}",
            daemon=True,
        )
        self._watchdog_thread.start()
        logger.info(
            f"🐾 [{self.broker_name}] Connection watchdog started "
            f"(interval={self._watchdog_cfg.check_interval_s}s, "
            f"failure_threshold={self._watchdog_cfg.failure_threshold})"
        )

    def stop_watchdog(self) -> None:
        """Stop the background watchdog thread gracefully."""
        self._stop_event.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=self._watchdog_cfg.check_interval_s + 5)
            self._watchdog_thread = None
        logger.info(f"[{self.broker_name}] Connection watchdog stopped")

    def _probe_connection(self) -> bool:
        """
        Execute a single connection health probe.

        Returns True when the connection appears healthy.
        """
        probe_fn = self._health_probe_fn or self._reconnect_fn
        if probe_fn is None:
            # No probe registered — log at debug level so operators know
            logger.debug(
                f"[{self.broker_name}] No probe function registered; "
                "skipping health check (register a broker to enable probing)"
            )
            return True
        try:
            result = probe_fn()
            return bool(result)
        except Exception as exc:
            logger.debug(f"[{self.broker_name}] Probe raised: {exc}")
            return False

    def _attempt_reconnect(self) -> bool:
        """
        Try to re-establish the broker connection using exponential backoff.

        Returns True if reconnection succeeded.
        """
        if self._reconnect_fn is None:
            return False

        cfg = self._watchdog_cfg
        delay = cfg.reconnect_base_delay_s
        # 0 means unlimited; cap at a large finite value to prevent infinite loops
        max_attempts = cfg.max_reconnect_attempts if cfg.max_reconnect_attempts > 0 else 10_000
        attempt = 0

        with self._state_lock:
            self._state = ConnectionState.RECONNECTING

        while attempt < max_attempts:
            attempt += 1
            logger.info(
                f"🔄 [{self.broker_name}] Reconnect attempt {attempt}"
                + (f"/{cfg.max_reconnect_attempts}" if cfg.max_reconnect_attempts else "")
                + f" (delay was {delay:.1f}s)…"
            )

            try:
                success = self._reconnect_fn()
            except Exception as exc:
                success = False
                logger.warning(f"⚠️ [{self.broker_name}] Reconnect raised: {exc}")

            if success:
                with self._state_lock:
                    self._state = ConnectionState.CONNECTED
                    self._consecutive_failures = 0
                    self._last_success_time = time.monotonic()
                    self._total_reconnects += 1
                logger.info(f"✅ [{self.broker_name}] Reconnected after {attempt} attempt(s)")
                return True

            # Back off before next attempt; honour a stop request during the wait
            if self._stop_event.wait(timeout=delay):
                logger.info(f"[{self.broker_name}] Watchdog stopping; aborting reconnect")
                with self._state_lock:
                    self._state = ConnectionState.DISCONNECTED
                return False
            delay = min(delay * cfg.reconnect_backoff_factor, cfg.reconnect_max_delay_s)

        logger.error(
            f"❌ [{self.broker_name}] Could not reconnect after {attempt} attempt(s)"
        )
        with self._state_lock:
            self._state = ConnectionState.DISCONNECTED
        return False

    def _watchdog_loop(self) -> None:
        """Main loop executed in the watchdog daemon thread."""
        cfg = self._watchdog_cfg
        logger.debug(f"[{self.broker_name}] Watchdog thread started")

        while not self._stop_event.is_set():
            # Wait for next probe interval (or stop signal)
            if self._stop_event.wait(timeout=cfg.check_interval_s):
                break

            now = time.monotonic()
            self._last_probe_time = now

            healthy = self._probe_connection()

            if healthy:
                with self._state_lock:
                    self._consecutive_failures = 0
                    if self._state in (ConnectionState.DEGRADED, ConnectionState.DISCONNECTED):
                        self._state = ConnectionState.CONNECTED
                        logger.info(f"✅ [{self.broker_name}] Connection recovered (watchdog probe)")
                    self._last_success_time = now
            else:
                with self._state_lock:
                    self._consecutive_failures += 1
                    failures = self._consecutive_failures

                if failures < cfg.failure_threshold:
                    with self._state_lock:
                        self._state = ConnectionState.DEGRADED
                    logger.warning(
                        f"⚠️ [{self.broker_name}] Probe failed "
                        f"({failures}/{cfg.failure_threshold}) → DEGRADED"
                    )
                else:
                    logger.error(
                        f"🔴 [{self.broker_name}] {failures} consecutive probe failures → "
                        "attempting reconnect…"
                    )
                    self._attempt_reconnect()

        logger.debug(f"[{self.broker_name}] Watchdog thread exiting")


# ---------------------------------------------------------------------------
# Global registry / singleton factory
# ---------------------------------------------------------------------------

_managers: Dict[str, ConnectionStabilityManager] = {}
_managers_lock = threading.Lock()


def get_connection_stability_manager(
    broker_name: str,
    watchdog_cfg: Optional[WatchdogConfig] = None,
    pool_cfg: Optional[ConnectionPoolConfig] = None,
) -> ConnectionStabilityManager:
    """
    Return (or create) the singleton :class:`ConnectionStabilityManager` for
    the given *broker_name*.

    Args:
        broker_name: Unique identifier for the broker (e.g. ``"coinbase"``).
        watchdog_cfg: Optional watchdog configuration; used only on first call.
        pool_cfg: Optional pool configuration; used only on first call.

    Returns:
        :class:`ConnectionStabilityManager` instance.
    """
    with _managers_lock:
        if broker_name not in _managers:
            _managers[broker_name] = ConnectionStabilityManager(
                broker_name=broker_name,
                watchdog_cfg=watchdog_cfg,
                pool_cfg=pool_cfg,
            )
        return _managers[broker_name]


def reset_all_managers() -> None:
    """Remove all registered managers (primarily for test teardown)."""
    with _managers_lock:
        for mgr in _managers.values():
            mgr.stop_watchdog()
        _managers.clear()
