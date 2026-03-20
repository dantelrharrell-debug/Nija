"""
NIJA Startup Readiness Gate — Race-Condition-Free Boot Sequencer
================================================================

Fixes the startup race condition where trading threads begin executing
orders before critical subsystems (broker connection, market data feed,
strategy initialisation) have fully completed their own initialisation.

Problem
-------
When the bot starts, several things happen concurrently:
    - Health-check HTTP server spins up immediately (good).
    - Broker connection (Kraken) can take 10–30 s (slow I/O).
    - Strategy object is constructed (CPU + I/O).
    - Per-broker trading threads are started.

Without a readiness gate the trading threads can call the broker before
the connection has been confirmed, causing transient "not connected" errors
that are mis-classified as hard failures and halt the thread.

Solution
--------
``StartupReadinessGate`` is a centralised "all clear" signal:

    gate = get_startup_readiness_gate()

    # In the initialisation sequence — signal each component:
    gate.signal_ready("broker:kraken")
    gate.signal_ready("strategy")

    # In every trading thread — block until ready:
    if not gate.wait_until_ready(timeout_s=120):
        logger.error("Readiness gate timed out — aborting thread")
        return

Components are registered with ``register_component(name)`` before
initialisation starts. Once *all* registered components have called
``signal_ready(name)``, the gate opens and all waiting threads unblock
simultaneously.

Thread-safety
-------------
All public methods are protected by a ``threading.Lock``.  The gate uses
``threading.Event`` for efficient waiting with no busy-polling.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Set

logger = logging.getLogger("nija.startup_readiness_gate")


class StartupReadinessGate:
    """
    Thread-safe readiness gate that serialises the bot startup sequence.

    Usage pattern
    -------------
    ::

        gate = get_startup_readiness_gate()

        # During bot.__init__ — register components that MUST be ready
        # before trading is allowed to start.
        gate.register_component("broker:kraken")
        gate.register_component("strategy")

        # ... initialise broker ...
        gate.signal_ready("broker:kraken")

        # ... initialise strategy ...
        gate.signal_ready("strategy")

        # In each trading thread (blocks until gate is open):
        if not gate.wait_until_ready(timeout_s=120):
            logger.error("Startup timed out; aborting thread")
            return

    The gate can be reset (e.g. for restarts) via ``reset()``.
    """

    def __init__(self, default_timeout_s: float = 120.0) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._default_timeout_s = default_timeout_s

        self._required: Set[str] = set()
        self._ready: Set[str] = set()
        self._failed: Dict[str, str] = {}   # component → failure reason
        self._gate_forced_open: bool = False
        self._gate_forced_closed: bool = False
        self._opened_at: Optional[datetime] = None
        self._registered_at: Dict[str, datetime] = {}
        self._signalled_at: Dict[str, datetime] = {}

        # Separate event used only to unblock waiters when force_close() is called.
        # Keeping it separate from _event preserves the invariant that
        # _event.is_set() ↔ "gate is genuinely open (ready)".
        self._close_unblock_event = threading.Event()

        logger.info("✅ StartupReadinessGate initialised (timeout=%.0fs)", default_timeout_s)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_component(self, name: str) -> None:
        """
        Register a component that must signal ready before the gate opens.

        Call this *before* spawning trading threads so the gate is fully
        configured when threads call ``wait_until_ready``.
        """
        with self._lock:
            self._required.add(name)
            self._registered_at[name] = datetime.now(timezone.utc)
            logger.debug("📋 Registered component: %s (%d total required)", name, len(self._required))

    # ------------------------------------------------------------------
    # Signalling
    # ------------------------------------------------------------------

    def signal_ready(self, name: str) -> None:
        """
        Mark *name* as ready.  Opens the gate when all required components
        have called this method.

        If *name* was not previously registered, it is accepted anyway so
        that callers do not need to be strictly ordered.
        """
        with self._lock:
            if name not in self._required:
                logger.debug(
                    "signal_ready('%s') — component not pre-registered; accepting anyway", name
                )
                self._required.add(name)

            self._ready.add(name)
            self._signalled_at[name] = datetime.now(timezone.utc)
            logger.info("✅ Component ready: %s (%d/%d)", name, len(self._ready), len(self._required))

            self._check_and_open()

    def signal_failed(self, name: str, reason: str = "") -> None:
        """
        Mark *name* as permanently failed.

        A failed component is removed from *required* so that the remaining
        healthy components can still open the gate.  The failure is logged
        at WARNING level and is included in the status report.
        """
        with self._lock:
            self._failed[name] = reason or "unknown failure"
            self._required.discard(name)
            logger.warning(
                "⚠️  Component FAILED: %s — %s (removed from gate requirements)",
                name,
                reason or "no reason given",
            )
            self._check_and_open()

    # ------------------------------------------------------------------
    # Waiting
    # ------------------------------------------------------------------

    def wait_until_ready(self, timeout_s: Optional[float] = None) -> bool:
        """
        Block the calling thread until the gate opens or *timeout_s* elapses.

        Returns
        -------
        True  — gate opened (all required components are ready).
        False — timed out before gate opened, or gate was force-closed.
        """
        if self._gate_forced_closed:
            logger.error("Startup readiness gate is FORCE CLOSED — trading blocked")
            return False

        effective_timeout = timeout_s if timeout_s is not None else self._default_timeout_s

        # Fast path: already open
        if self._event.is_set():
            return True

        t0 = time.monotonic()
        logger.info(
            "⏳ Waiting for startup readiness gate (timeout=%.0fs) …", effective_timeout
        )

        # Wait for either the readiness event OR the force-close unblock event.
        # We poll in short increments so we notice force_close quickly without
        # busy-spinning.
        deadline = t0 + effective_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            # Wait in slices of up to 0.5 s so force-close is noticed quickly.
            slice_s = min(0.5, remaining)
            if self._event.wait(timeout=slice_s):
                break                       # gate opened normally
            if self._gate_forced_closed:
                break                       # gate was force-closed
            if self._close_unblock_event.is_set():
                break                       # unblocked by force_close

        elapsed = time.monotonic() - t0

        if self._gate_forced_closed:
            logger.error(
                "❌ Startup readiness gate is FORCE CLOSED after %.1fs — trading blocked", elapsed
            )
            return False

        opened = self._event.is_set()
        if opened:
            logger.info("🚀 Startup readiness gate OPENED after %.1fs", elapsed)
        else:
            pending = self._required - self._ready
            logger.error(
                "❌ Startup readiness gate TIMED OUT after %.1fs — pending components: %s",
                elapsed,
                ", ".join(sorted(pending)) if pending else "<none>",
            )
        return opened

    def is_ready(self) -> bool:
        """Return True if the gate is currently open (non-blocking)."""
        return self._event.is_set()

    # ------------------------------------------------------------------
    # Manual overrides
    # ------------------------------------------------------------------

    def force_open(self, reason: str = "manual override") -> None:
        """
        Immediately open the gate regardless of component state.

        Use with caution — this bypasses the readiness guarantee.  Only
        appropriate for emergency situations or unit tests.
        """
        with self._lock:
            self._gate_forced_open = True
            self._opened_at = datetime.now(timezone.utc)
            self._event.set()
            logger.warning("⚠️  StartupReadinessGate FORCE OPENED: %s", reason)

    def force_close(self, reason: str = "manual override") -> None:
        """
        Close the gate and prevent it from re-opening.

        New calls to ``wait_until_ready`` will return False immediately.
        Existing blocked calls will unblock and return False.

        Note: ``_close_unblock_event`` is set to wake blocked waiters.
        ``_event`` (the normal ready signal) is deliberately NOT set here so
        that ``is_ready()`` continues to return False.
        """
        with self._lock:
            self._gate_forced_closed = True
            self._close_unblock_event.set()   # unblock waiters without setting the ready event
            logger.error("🔒 StartupReadinessGate FORCE CLOSED: %s", reason)

    def reset(self) -> None:
        """
        Reset the gate to its initial (closed) state.

        Useful when the bot performs a warm restart without a full process
        restart.  Clears all component registrations and signals.
        """
        with self._lock:
            self._required.clear()
            self._ready.clear()
            self._failed.clear()
            self._gate_forced_open = False
            self._gate_forced_closed = False
            self._opened_at = None
            self._registered_at.clear()
            self._signalled_at.clear()
            self._event.clear()
            self._close_unblock_event.clear()
            logger.info("🔄 StartupReadinessGate RESET")

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Return a serialisable snapshot of the gate's current state."""
        with self._lock:
            pending = sorted(self._required - self._ready)
            return {
                "gate_open": self._event.is_set() and not self._gate_forced_closed,
                "forced_open": self._gate_forced_open,
                "forced_closed": self._gate_forced_closed,
                "required_count": len(self._required),
                "ready_count": len(self._ready),
                "failed_count": len(self._failed),
                "pending_components": pending,
                "ready_components": sorted(self._ready),
                "failed_components": dict(self._failed),
                "opened_at": self._opened_at.isoformat() if self._opened_at else None,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_and_open(self) -> None:
        """Open the gate if all required components are ready (call under lock)."""
        if self._event.is_set():
            return  # already open
        if self._gate_forced_closed:
            return

        # Gate opens when all required components have signalled ready
        # (failed components are removed from _required, so they don't block)
        if self._required and self._required.issubset(self._ready):
            self._opened_at = datetime.now(timezone.utc)
            self._event.set()
            logger.info(
                "🚀 All %d component(s) ready — startup gate OPENED at %s",
                len(self._ready),
                self._opened_at.isoformat(),
            )
        elif not self._required:
            # Nothing was registered — open immediately to avoid eternal block
            self._opened_at = datetime.now(timezone.utc)
            self._event.set()
            logger.info(
                "🚀 No components registered — startup gate opened immediately at %s",
                self._opened_at.isoformat(),
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[StartupReadinessGate] = None
_instance_lock = threading.Lock()


def get_startup_readiness_gate(**kwargs) -> StartupReadinessGate:
    """
    Return the process-wide ``StartupReadinessGate`` singleton.

    Keyword arguments are forwarded to the constructor on first call only.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = StartupReadinessGate(**kwargs)
    return _instance
