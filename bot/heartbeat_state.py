"""Canonical shared HeartbeatState for the NIJA writer-authority lifecycle.

All modules that need to publish or read the current heartbeat health MUST
use this singleton.  No module may maintain an independent heartbeat cache.

Lifecycle phases
----------------
BOOT             – process started, no lease held
LEASE_ACQUIRED   – Redis writer lease successfully acquired
SCAN_RUNNING     – first trading scan has been initiated
SCAN_COMPLETE    – initial scan completed (startup-only deadline retired)
LIVE             – steady-state; no startup timeouts apply

Thread safety
-------------
All public methods acquire ``_lock`` internally so callers never need to
synchronise externally.
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
    """True when the most recent heartbeat completed without error."""

    marker_timestamp: float
    """Unix timestamp of the most recent file-marker write (0.0 if never written)."""

    phase: WriterLifecyclePhase
    """Current writer-authority lifecycle phase."""


class HeartbeatState:
    """Thread-safe, canonical heartbeat state shared across all authority modules.

    Singleton access: use :func:`get_heartbeat_state`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._timestamp: float = 0.0
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
    ) -> HeartbeatSnapshot:
        """Atomically record a *successful* heartbeat.

        Parameters
        ----------
        generation:
            The authority-lineage generation number as of this beat.
        marker_timestamp:
            Unix timestamp of the associated file-marker write, or 0.0 if no
            marker was written during this beat.

        Returns
        -------
        HeartbeatSnapshot
            The new canonical state immediately after the update.
        """
        now = time.time()
        with self._lock:
            self._timestamp = now
            self._generation = generation
            self._healthy = True
            if marker_timestamp > 0.0:
                self._marker_timestamp = marker_timestamp
            snap = self._snapshot()
        return snap

    def record_heartbeat_failure(self) -> HeartbeatSnapshot:
        """Mark the heartbeat as unhealthy without changing the timestamp."""
        with self._lock:
            self._healthy = False
            snap = self._snapshot()
        return snap

    def advance_phase(self, phase: WriterLifecyclePhase) -> None:
        """Advance the lifecycle phase.

        Phases must progress forward; attempts to regress are silently ignored.
        """
        _order = list(WriterLifecyclePhase)
        with self._lock:
            if _order.index(phase) > _order.index(self._phase):
                self._phase = phase

    def recover_health(self, *, max_age_s: float = 180.0) -> bool:
        """Restore ``healthy=True`` when the last heartbeat timestamp is recent.

        Called when external authority evidence (e.g. a live Redis lease and a
        running heartbeat loop) confirms liveness even though a previous
        :meth:`record_heartbeat_failure` set ``healthy=False``.  Only repairs
        when the stored timestamp is within *max_age_s* seconds, so a genuinely
        stale or never-initialised state is never falsely healed.

        Returns ``True`` when the repair was applied, ``False`` when skipped
        (either ``_healthy`` was already ``True``, or the timestamp is too old /
        not set).
        """
        now = time.time()
        with self._lock:
            if self._healthy:
                return False
            if self._timestamp <= 0.0:
                return False
            if (now - self._timestamp) > max_age_s:
                return False
            self._timestamp = now
            self._healthy = True
        return True

    def reset(self) -> None:
        """Reset all state to BOOT (used when writer lease is released)."""
        with self._lock:
            self._timestamp = 0.0
            self._generation = 0
            self._healthy = False
            self._marker_timestamp = 0.0
            self._phase = WriterLifecyclePhase.BOOT

    # ------------------------------------------------------------------ #
    # Read API                                                             #
    # ------------------------------------------------------------------ #

    def snapshot(self) -> HeartbeatSnapshot:
        """Return a consistent point-in-time view of all heartbeat fields."""
        with self._lock:
            return self._snapshot()

    def is_fresh(self, max_age_s: float = 90.0) -> bool:
        """Return True when the last successful heartbeat is within *max_age_s*."""
        with self._lock:
            if not self._healthy or self._timestamp <= 0.0:
                return False
            return (time.time() - self._timestamp) <= max_age_s

    def age_s(self) -> float:
        """Seconds since the last successful heartbeat (inf when never beaten)."""
        with self._lock:
            if self._timestamp <= 0.0:
                return float("inf")
            return max(0.0, time.time() - self._timestamp)

    @property
    def phase(self) -> WriterLifecyclePhase:
        with self._lock:
            return self._phase

    @property
    def is_live(self) -> bool:
        """True when lifecycle has reached the LIVE steady-state phase."""
        with self._lock:
            return self._phase == WriterLifecyclePhase.LIVE

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _snapshot(self) -> HeartbeatSnapshot:
        """Must be called with ``_lock`` held."""
        return HeartbeatSnapshot(
            timestamp=self._timestamp,
            generation=self._generation,
            healthy=self._healthy,
            marker_timestamp=self._marker_timestamp,
            phase=self._phase,
        )


# ------------------------------------------------------------------ #
# Module-level singleton                                               #
# ------------------------------------------------------------------ #

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
