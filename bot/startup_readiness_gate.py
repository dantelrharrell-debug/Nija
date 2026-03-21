"""
NIJA Startup Readiness Gate — Deadlock-Free Boot Sequencer
==========================================================

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

Deadlock prevention
-------------------
The rewrite eliminates all known deadlock and eternal-block scenarios:

1. Uses a single ``threading.Condition`` instead of a ``Lock`` plus two
   separate ``Event`` objects.  ``Condition.notify_all()`` wakes every
   blocked waiter atomically; no second "unblock" event is needed.

2. Every read of shared state (``_gate_open``, ``_gate_forced_closed``,
   ``_required``, ``_ready``) happens *inside* the Condition lock so no
   thread can observe a torn or stale view.

3. ``wait_until_ready`` triggers ``_check_and_open`` on entry.  This
   handles the case where zero components were ever registered: the gate
   opens immediately instead of blocking until the caller times out.

4. ``wait_until_ready`` uses a single ``Condition.wait(timeout)`` call
   rather than polling in 0.5 s slices, so ``force_close`` unblocks
   waiters instantly rather than after up to 0.5 s.

Author: NIJA Trading Systems
Version: 2.0
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
    Thread-safe, deadlock-free readiness gate for the bot startup sequence.

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
        # Single Condition replaces Lock + two Events.
        # All state is read/written while holding _cond; notify_all() wakes
        # every blocked waiter so no separate "unblock event" is needed.
        self._cond = threading.Condition(threading.Lock())
        self._default_timeout_s = default_timeout_s

        self._required: Set[str] = set()
        self._ready: Set[str] = set()
        self._failed: Dict[str, str] = {}      # component → failure reason
        self._gate_open: bool = False           # True once the gate has opened
        self._gate_forced_open: bool = False    # True if opened via force_open()
        self._gate_forced_closed: bool = False  # True if permanently closed
        self._opened_at: Optional[datetime] = None
        self._registered_at: Dict[str, datetime] = {}
        self._signalled_at: Dict[str, datetime] = {}

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
        with self._cond:
            self._required.add(name)
            self._registered_at[name] = datetime.now(timezone.utc)
            logger.debug(
                "📋 Registered component: %s (%d total required)", name, len(self._required)
            )

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
        with self._cond:
            if name not in self._required:
                logger.debug(
                    "signal_ready('%s') — component not pre-registered; accepting anyway", name
                )
                self._required.add(name)

            self._ready.add(name)
            self._signalled_at[name] = datetime.now(timezone.utc)
            logger.info(
                "✅ Component ready: %s (%d/%d)", name, len(self._ready), len(self._required)
            )

            self._check_and_open()
            self._cond.notify_all()

    def signal_failed(self, name: str, reason: str = "") -> None:
        """
        Mark *name* as permanently failed.

        A failed component is removed from *required* so that the remaining
        healthy components can still open the gate.  The failure is logged
        at WARNING level and is included in the status report.
        """
        with self._cond:
            self._failed[name] = reason or "unknown failure"
            self._required.discard(name)
            logger.warning(
                "⚠️  Component FAILED: %s — %s (removed from gate requirements)",
                name,
                reason or "no reason given",
            )
            self._check_and_open()
            self._cond.notify_all()

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
        effective_timeout = timeout_s if timeout_s is not None else self._default_timeout_s
        deadline = time.monotonic() + effective_timeout

        with self._cond:
            # Trigger the open check on entry: handles the case where zero
            # components were registered and signal_ready was never called.
            if not self._gate_open and not self._gate_forced_closed:
                self._check_and_open()

            # Wait until the gate opens, is force-closed, or the deadline passes.
            # Condition.wait() atomically releases the lock and sleeps; it
            # re-acquires the lock before returning, so all state reads below
            # are safe without an additional lock acquisition.
            while not self._gate_open and not self._gate_forced_closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(timeout=remaining)

            if self._gate_forced_closed:
                elapsed = effective_timeout - (deadline - time.monotonic())
                logger.error(
                    "❌ Startup readiness gate is FORCE CLOSED after %.1fs — trading blocked",
                    max(0.0, elapsed),
                )
                return False

            if self._gate_open:
                return True

            # Timed out
            pending = self._required - self._ready
            logger.error(
                "❌ Startup readiness gate TIMED OUT after %.0fs — pending components: %s",
                effective_timeout,
                ", ".join(sorted(pending)) if pending else "<none>",
            )
            return False

    def is_ready(self) -> bool:
        """Return True if the gate is currently open (non-blocking)."""
        with self._cond:
            return self._gate_open and not self._gate_forced_closed

    # ------------------------------------------------------------------
    # Manual overrides
    # ------------------------------------------------------------------

    def force_open(self, reason: str = "manual override") -> None:
        """
        Immediately open the gate regardless of component state.

        Use with caution — this bypasses the readiness guarantee.  Only
        appropriate for emergency situations or unit tests.
        """
        with self._cond:
            self._gate_forced_open = True
            self._gate_open = True
            self._opened_at = datetime.now(timezone.utc)
            self._cond.notify_all()
            logger.warning("⚠️  StartupReadinessGate FORCE OPENED: %s", reason)

    def force_close(self, reason: str = "manual override") -> None:
        """
        Close the gate and prevent it from re-opening.

        New calls to ``wait_until_ready`` will return False immediately.
        Existing blocked calls will unblock and return False.
        """
        with self._cond:
            self._gate_forced_closed = True
            self._cond.notify_all()  # wake all waiters so they observe the closed state
            logger.error("🔒 StartupReadinessGate FORCE CLOSED: %s", reason)

    def reset(self) -> None:
        """
        Reset the gate to its initial (closed) state.

        Useful when the bot performs a warm restart without a full process
        restart.  Clears all component registrations and signals.
        """
        with self._cond:
            self._required.clear()
            self._ready.clear()
            self._failed.clear()
            self._gate_open = False
            self._gate_forced_open = False
            self._gate_forced_closed = False
            self._opened_at = None
            self._registered_at.clear()
            self._signalled_at.clear()
            self._cond.notify_all()
            logger.info("🔄 StartupReadinessGate RESET")

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Return a serialisable snapshot of the gate's current state."""
        with self._cond:
            pending = sorted(self._required - self._ready)
            return {
                "gate_open": self._gate_open and not self._gate_forced_closed,
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
        """
        Open the gate if all conditions are met.

        Must be called while holding ``self._cond``.  Callers are
        responsible for calling ``self._cond.notify_all()`` after this
        returns so that waiting threads are woken.
        """
        if self._gate_open or self._gate_forced_closed:
            return  # already open or permanently closed

        if not self._required:
            # Nothing registered — open immediately to avoid an eternal block.
            self._gate_open = True
            self._opened_at = datetime.now(timezone.utc)
            logger.info(
                "🚀 No components registered — startup gate opened immediately at %s",
                self._opened_at.isoformat(),
            )
        elif self._required.issubset(self._ready):
            # Every required component has signalled ready
            # (failed components are removed from _required so they don't block).
            self._gate_open = True
            self._opened_at = datetime.now(timezone.utc)
            logger.info(
                "🚀 All %d component(s) ready — startup gate OPENED at %s",
                len(self._ready),
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
