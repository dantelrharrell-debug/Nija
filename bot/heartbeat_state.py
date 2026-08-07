"""Canonical shared HeartbeatState for the NIJA writer-authority lifecycle.

All modules that need to publish or read the current heartbeat health MUST
use this singleton. No module may maintain an independent heartbeat cache.

Freshness contract
------------------
``timestamp`` remains a Unix epoch timestamp for telemetry and persisted
markers. Freshness is measured only from the process-local monotonic clock so
wall-clock adjustments cannot make a live heartbeat appear stale (or make a
stale heartbeat appear fresh).
"""
from __future__ import annotations

import threading
import time
from enum import Enum
from typing import NamedTuple, Optional


class WriterLifecyclePhase(str, Enum):
    BOOT = "BOOT"
    LEASE_ACQUIRED = "LEASE_ACQUIRED"
    SCAN_RUNNING = "SCAN_RUNNING"
    SCAN_COMPLETE = "SCAN_COMPLETE"
    LIVE = "LIVE"


class HeartbeatSnapshot(NamedTuple):
    """Immutable point-in-time view of the canonical heartbeat state."""

    timestamp: float
    """Unix timestamp of the most recent successful heartbeat."""

    generation: int
    """Authority lineage generation number at time of heartbeat."""

    healthy: bool
    """True when a successful heartbeat has established current authority."""

    marker_timestamp: float
    """Unix timestamp of the most recent file-marker write (0.0 if never written)."""

    phase: WriterLifecyclePhase
    """Current writer-authority lifecycle phase."""


class HeartbeatState:
    """Thread-safe, canonical heartbeat state shared across all authority modules."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._timestamp: float = 0.0
        self._monotonic_timestamp: float = 0.0
        self._generation: int = 0
        self._healthy: bool = False
        self._marker_timestamp: float = 0.0
        self._phase: WriterLifecyclePhase = WriterLifecyclePhase.BOOT

    # ------------------------------------------------------------------ #
    # Write API                                                            #
    # ------------------------------------------------------------------ #

    def record_heartbeat(
        self,
        *,
        generation: int,
        marker_timestamp: float = 0.0,
        timestamp: float = 0.0,
        monotonic_timestamp: float = 0.0,
    ) -> HeartbeatSnapshot:
        """Atomically record a successful heartbeat.

        ``timestamp`` is the epoch value exported to logs/env/marker state.
        ``monotonic_timestamp`` is the freshness origin. Callers normally omit
        both and let this method sample the two clocks together.
        """
        epoch_now = float(timestamp or time.time())
        mono_now = float(monotonic_timestamp or time.monotonic())
        with self._lock:
            self._timestamp = epoch_now
            self._monotonic_timestamp = mono_now
            self._generation = generation
            self._healthy = True
            if marker_timestamp > 0.0:
                self._marker_timestamp = marker_timestamp
            snap = self._snapshot()
        return snap

    def record_heartbeat_failure(self) -> HeartbeatSnapshot:
        """Record a failed probe without invalidating a still-fresh success.

        A transient Redis/probe error is not the same event as authority loss.
        Freshness expires naturally from the monotonic timestamp, while genuine
        lease loss calls :meth:`reset` immediately. This prevents the invalid
        state ``heartbeat_active=True`` + recent success + ``healthy=False``.
        """
        with self._lock:
            snap = self._snapshot()
        return snap

    def advance_phase(self, phase: WriterLifecyclePhase) -> None:
        """Advance the lifecycle phase; regressions are ignored."""
        order = list(WriterLifecyclePhase)
        with self._lock:
            if order.index(phase) > order.index(self._phase):
                self._phase = phase

    def recover_health(self, *, max_age_s: float = 180.0) -> bool:
        """Restore healthy=True only when the last success is still fresh."""
        mono_now = time.monotonic()
        epoch_now = time.time()
        with self._lock:
            if self._healthy:
                return False
            if self._timestamp <= 0.0 or self._monotonic_timestamp <= 0.0:
                return False
            if (mono_now - self._monotonic_timestamp) > max_age_s:
                return False
            self._timestamp = epoch_now
            self._monotonic_timestamp = mono_now
            self._healthy = True
        return True

    def reset(self) -> None:
        """Reset all state to BOOT (used when writer lease is released)."""
        with self._lock:
            self._timestamp = 0.0
            self._monotonic_timestamp = 0.0
            self._generation = 0
            self._healthy = False
            self._marker_timestamp = 0.0
            self._phase = WriterLifecyclePhase.BOOT

    # ------------------------------------------------------------------ #
    # Read API                                                             #
    # ------------------------------------------------------------------ #

    def snapshot(self) -> HeartbeatSnapshot:
        """Return a consistent point-in-time view of all public fields."""
        with self._lock:
            return self._snapshot()

    def health_for_generation(
        self,
        *,
        expected_generation: int,
        max_age_s: float,
    ) -> tuple[bool, float, bool, float]:
        """Return the one canonical heartbeat freshness decision.

        Returns ``(healthy, age_s, authoritative, heartbeat_ts)``. The result is
        authoritative only after a successful heartbeat for the expected
        generation has been recorded. Age is always calculated with monotonic
        time; ``heartbeat_ts`` is the corresponding epoch timestamp for logs.
        """
        mono_now = time.monotonic()
        with self._lock:
            authoritative = bool(
                expected_generation > 0
                and self._generation == expected_generation
                and self._timestamp > 0.0
                and self._monotonic_timestamp > 0.0
            )
            if not authoritative:
                return False, float("inf"), False, self._timestamp
            age_s = max(0.0, mono_now - self._monotonic_timestamp)
            healthy = bool(self._healthy and age_s <= max_age_s)
            return healthy, age_s, True, self._timestamp

    def is_fresh(self, max_age_s: float = 90.0) -> bool:
        """Return True when the last successful heartbeat is fresh and healthy."""
        mono_now = time.monotonic()
        with self._lock:
            if (
                not self._healthy
                or self._timestamp <= 0.0
                or self._monotonic_timestamp <= 0.0
            ):
                return False
            return (mono_now - self._monotonic_timestamp) <= max_age_s

    def age_s(self) -> float:
        """Seconds since the last successful heartbeat (inf when never beaten)."""
        mono_now = time.monotonic()
        with self._lock:
            if self._monotonic_timestamp <= 0.0:
                return float("inf")
            return max(0.0, mono_now - self._monotonic_timestamp)

    @property
    def phase(self) -> WriterLifecyclePhase:
        with self._lock:
            return self._phase

    @property
    def is_live(self) -> bool:
        with self._lock:
            return self._phase == WriterLifecyclePhase.LIVE

    def _snapshot(self) -> HeartbeatSnapshot:
        """Must be called with ``_lock`` held."""
        return HeartbeatSnapshot(
            timestamp=self._timestamp,
            generation=self._generation,
            healthy=self._healthy,
            marker_timestamp=self._marker_timestamp,
            phase=self._phase,
        )


_SINGLETON_LOCK = threading.Lock()
_SINGLETON: Optional[HeartbeatState] = None


def get_heartbeat_state() -> HeartbeatState:
    """Return the process-wide :class:`HeartbeatState` singleton."""
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = HeartbeatState()
    return _SINGLETON


def reset_heartbeat_state_for_testing() -> HeartbeatState:
    """Replace the singleton with a fresh instance (test use only)."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = HeartbeatState()
    return _SINGLETON
