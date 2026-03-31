# bot/broker_failure_manager.py
"""
NIJA Broker Failure Manager
=============================

Tracks per-broker error counts and automatically marks a broker as **dead**
once it exceeds a configurable failure threshold.  When a broker dies its
capital allocation is instantly redistributed to the remaining active brokers.
Dead brokers are retried with intelligent exponential backoff so that a
recovered exchange is brought back into the active pool without manual
intervention.

Features
--------
* **Auto-remove failed brokers** — broker is marked dead after
  ``FAILURE_THRESHOLD`` consecutive errors (default 5, override via
  ``NIJA_BROKER_FAILURE_THRESHOLD`` env var).
* **Instant capital rebalancing** — :meth:`get_active_allocation_weights`
  returns normalised weights that exclude dead brokers so callers can
  immediately redirect capital to healthy exchanges.
* **Intelligent retry** — :meth:`get_retry_delay` returns an increasing
  backoff delay (15 s → 30 s → 60 s) so reconnect attempts don't hammer a
  temporarily unavailable exchange.

Typical usage
-------------
Tracks per-broker failure counts, applies retry backoff, auto-disables
brokers that repeatedly fail, and redistributes capital allocation from
dead brokers to healthy ones.

Features
--------
1. Auto-disable failed brokers from allocation
   - After ``FAILURE_THRESHOLD`` consecutive cycle errors, a broker is
     marked as **dead** and excluded from new trade allocation.

2. Retry backoff: 15 s → 30 s → 60 s
   - 1st consecutive error  → wait 15 s
   - 2nd consecutive error  → wait 30 s
   - 3rd+ consecutive error → wait 60 s
   (Normal 150-second cycle wait is unchanged for healthy brokers.)

3. ACTIVE vs DEAD broker status — surfaced in the status banner.

4. Fail-safe allocation shift
   - When a broker becomes dead its allocation weight is split evenly
     among remaining active brokers via ``get_active_allocation_weights()``.

Usage
-----
::

    from bot.broker_failure_manager import get_broker_failure_manager

    bfm = get_broker_failure_manager()

    # Register all brokers at startup (equal weights by default):
    bfm.register_broker("coinbase",  initial_allocation=0.50)
    bfm.register_broker("kraken",    initial_allocation=0.30)
    bfm.register_broker("binance",   initial_allocation=0.20)

    # In the trading loop:
    try:
        run_trading_cycle(broker)
        bfm.record_success("coinbase")
    except Exception as e:
        bfm.record_error("coinbase", reason=str(e))

    # Before placing a trade, check liveness:
    if bfm.is_dead("coinbase"):
        delay = bfm.get_retry_delay("coinbase")
        time.sleep(delay)   # wait, then attempt reconnect

    # Get redistributed weights when allocating capital:
    weights = bfm.get_active_allocation_weights()
    # {"kraken": 0.60, "binance": 0.40}  ← coinbase excluded (dead)

    # After a successful reconnect:
    bfm.revive_broker("coinbase")
    mgr = get_broker_failure_manager()

    # Call on each cycle error:
    mgr.record_error("kraken", "API timeout")
    delay = mgr.get_retry_delay("kraken")      # 15, 30, or 60 seconds
    is_dead = mgr.is_dead("kraken")

    # Call on each cycle success:
    mgr.record_success("kraken")

    # Allocation weights for live capital sizing:
    weights = mgr.get_active_allocation_weights(["kraken", "coinbase"])

    # For the status banner:
    active, dead = mgr.get_active_dead_lists()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.broker_failure_manager")

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

#: Default consecutive-failure threshold before a broker is marked dead.
#: Override with the ``NIJA_BROKER_FAILURE_THRESHOLD`` environment variable.
FAILURE_THRESHOLD: int = int(os.environ.get("NIJA_BROKER_FAILURE_THRESHOLD", "5"))

# Retry backoff delays in seconds (index = min(consecutive_errors - 1, len - 1))
BACKOFF_DELAYS: Tuple[int, ...] = (15, 30, 60)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BrokerFailureState:
    """Live failure-tracking record for one broker."""
    broker_name: str
    consecutive_errors: int = 0
    total_errors: int = 0
    total_successes: int = 0
    is_dead: bool = False
    disabled_at: Optional[str] = None      # ISO timestamp when broker was disabled
    last_error_msg: Optional[str] = None
    last_error_at: Optional[str] = None
    last_success_at: Optional[str] = None
    # Accumulated allocation weight when broker was disabled; redistributed to others.
    redistributed_weight: float = 0.0

    # ----- helpers -----

    def record_error(self, error_msg: Optional[str] = None) -> None:
        self.consecutive_errors += 1
        self.total_errors += 1
        self.last_error_msg = (error_msg or "")[:200]
        self.last_error_at = datetime.now(timezone.utc).isoformat()

    def record_success(self) -> None:
        self.consecutive_errors = 0
        self.total_successes += 1
        self.last_success_at = datetime.now(timezone.utc).isoformat()

    def mark_dead(self, allocation_weight: float = 0.0) -> None:
        self.is_dead = True
        self.disabled_at = datetime.now(timezone.utc).isoformat()
        self.redistributed_weight = allocation_weight
        logger.error(
            "🔴 BROKER DEAD: %s — %d consecutive errors. "
            "Allocation (%.1f%%) shifted to active brokers.",
            self.broker_name, self.consecutive_errors, allocation_weight * 100,
        )

    def revive(self) -> None:
        """Re-enable a dead broker (e.g., after manual intervention)."""
        self.is_dead = False
        self.disabled_at = None
        self.consecutive_errors = 0
        self.redistributed_weight = 0.0
        logger.info("✅ BROKER REVIVED: %s re-enabled for allocation.", self.broker_name)

    @property
    def retry_delay(self) -> int:
        """Backoff delay in seconds based on consecutive error count."""
        idx = min(max(self.consecutive_errors - 1, 0), len(BACKOFF_DELAYS) - 1)
        return BACKOFF_DELAYS[idx]


# ---------------------------------------------------------------------------
# Manager class
# ---------------------------------------------------------------------------

class BrokerFailureManager:
    """
    Thread-safe singleton that tracks per-broker failure state and exposes
    backoff delays, dead-broker detection, and allocation-shift logic.
    """

    def __init__(self, failure_threshold: int = FAILURE_THRESHOLD) -> None:
        self._lock = threading.Lock()
        self._states: Dict[str, BrokerFailureState] = {}
        self.failure_threshold = failure_threshold
        logger.info(
            "✅ BrokerFailureManager initialized "
            "(threshold=%d, backoffs=%s s)",
            failure_threshold, "/".join(str(d) for d in BACKOFF_DELAYS),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure(self, broker_name: str) -> BrokerFailureState:
        """Return (or create) the failure-state record for *broker_name*."""
        if broker_name not in self._states:
            self._states[broker_name] = BrokerFailureState(broker_name=broker_name)
        return self._states[broker_name]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_error(
        self,
        broker_name: str,
        error_msg: Optional[str] = None,
        current_allocation_weight: float = 0.0,
    ) -> None:
        """
        Record a cycle failure for *broker_name*.

        When the consecutive-error count reaches ``failure_threshold`` the
        broker is automatically marked dead and its allocation weight is
        stored for redistribution.

        Args:
            broker_name: Broker identifier (e.g. ``"kraken"``).
            error_msg: Short description of the error (for diagnostics).
            current_allocation_weight: The broker's current allocation fraction
                (0–1).  Stored so callers can redistribute it.
        """
        with self._lock:
            state = self._ensure(broker_name)
            if state.is_dead:
                return  # already dead — no further tracking needed
            state.record_error(error_msg)
            logger.warning(
                "⚠️  %s — consecutive errors: %d/%d",
                broker_name, state.consecutive_errors, self.failure_threshold,
            )
            if state.consecutive_errors >= self.failure_threshold:
                state.mark_dead(current_allocation_weight)

    def record_success(self, broker_name: str) -> None:
        """
        Record a successful cycle for *broker_name*.

        Resets the consecutive-error counter.  A previously *dead* broker
        is **not** automatically revived — call :meth:`revive_broker` for
        that so the operator has explicit control.
        """
        with self._lock:
            state = self._ensure(broker_name)
            if state.is_dead:
                return
            if state.consecutive_errors > 0:
                logger.info(
                    "✅ %s recovered — consecutive errors reset (was %d)",
                    broker_name, state.consecutive_errors,
                )
            state.record_success()

    def is_dead(self, broker_name: str) -> bool:
        """Return ``True`` if *broker_name* has been auto-disabled."""
        with self._lock:
            return self._states.get(broker_name, BrokerFailureState(broker_name)).is_dead

    def get_retry_delay(self, broker_name: str) -> int:
        """
        Return the backoff delay (seconds) that the caller should sleep
        before the next retry of *broker_name*.

        Sequence: 15 s → 30 s → 60 s (capped at last value).
        """
        with self._lock:
            state = self._ensure(broker_name)
            return state.retry_delay

    def revive_broker(self, broker_name: str) -> None:
        """Re-enable a dead broker (manual operator override)."""
        with self._lock:
            state = self._ensure(broker_name)
            state.revive()

    def get_active_dead_lists(self) -> Tuple[List[str], List[str]]:
        """
        Return ``(active_brokers, dead_brokers)`` name lists.

        A broker is *active* if it has at least one recorded cycle (success
        or error) and is **not** dead.  Brokers that have never been seen
        are omitted from both lists.
        """
        with self._lock:
            active: List[str] = []
            dead: List[str] = []
            for name, state in self._states.items():
                if state.is_dead:
                    dead.append(name)
                else:
                    active.append(name)
            return sorted(active), sorted(dead)

    def get_active_allocation_weights(
        self,
        all_brokers: List[str],
        base_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Return normalized allocation weights for *active* brokers only.

        Dead brokers receive a weight of ``0``.  Their weight is
        redistributed evenly among the remaining active brokers.

        Args:
            all_brokers: Complete list of registered broker names.
            base_weights: Optional mapping of broker → preferred weight
                (0–1).  If ``None``, equal weights are assumed.

        Returns:
            Dict mapping every broker in *all_brokers* to its adjusted
            weight (dead brokers → 0, actives normalized to sum = 1).
        """
        with self._lock:
            if not all_brokers:
                return {}

            # Start from base weights or assume equal
            if base_weights:
                weights = {b: base_weights.get(b, 1.0 / len(all_brokers)) for b in all_brokers}
            else:
                share = 1.0 / len(all_brokers)
                weights = {b: share for b in all_brokers}

            dead_set = {name for name, st in self._states.items() if st.is_dead}

            # Zero-out dead brokers
            dead_weight_total = sum(weights[b] for b in all_brokers if b in dead_set)
            active_brokers = [b for b in all_brokers if b not in dead_set]

            if not active_brokers:
                # All brokers dead — return equal weights as emergency fallback
                logger.critical(
                    "🚨 ALL BROKERS DEAD — returning equal weights as emergency fallback"
                )
                equal = 1.0 / len(all_brokers)
                return {b: equal for b in all_brokers}

            for b in all_brokers:
                if b in dead_set:
                    weights[b] = 0.0

            # Redistribute dead weight to active brokers proportionally
            if dead_weight_total > 0 and active_brokers:
                active_total = sum(weights[b] for b in active_brokers)
                if active_total > 0:
                    for b in active_brokers:
                        weights[b] += dead_weight_total * (weights[b] / active_total)
                else:
                    share = dead_weight_total / len(active_brokers)
                    for b in active_brokers:
                        weights[b] += share

            # Final normalization
            total = sum(weights.values())
            if total > 0:
                for b in all_brokers:
                    weights[b] /= total

            return weights

    def get_full_report(self) -> Dict:
        """Return a JSON-serializable status dict for all tracked brokers."""
        with self._lock:
            return {
                name: {
                    "consecutive_errors": st.consecutive_errors,
                    "total_errors": st.total_errors,
                    "total_successes": st.total_successes,
                    "is_dead": st.is_dead,
                    "disabled_at": st.disabled_at,
                    "last_error_msg": st.last_error_msg,
                    "last_error_at": st.last_error_at,
                    "last_success_at": st.last_success_at,
                    "retry_delay_s": st.retry_delay,
                }
                for name, st in self._states.items()
            }

    def get_consecutive_errors(self, broker_name: str) -> int:
        """Return the current consecutive-error count for *broker_name*."""
        with self._lock:
            return self._states.get(
                broker_name, BrokerFailureState(broker_name=broker_name)
            ).consecutive_errors

    def log_active_dead_banner(self) -> None:
        """
        Log an "ACTIVE BROKERS vs DEAD BROKERS" status banner.
        Intended to be called from the periodic status-summary logger.
        """
        active, dead = self.get_active_dead_lists()
        logger.info("=" * 70)
        logger.info("🔍 BROKER HEALTH — ACTIVE vs DEAD")
        logger.info("=" * 70)
        if active:
            logger.info("✅ ACTIVE BROKERS (%d):", len(active))
            for name in active:
                with self._lock:
                    st = self._states.get(name)
                if st:
                    logger.info(
                        "   • %-20s  errors=%d  successes=%d",
                        name.upper(), st.total_errors, st.total_successes,
                    )
        else:
            logger.warning("   (none)")

        if dead:
            logger.warning("🔴 DEAD BROKERS (%d) — excluded from allocation:", len(dead))
            for name in dead:
                with self._lock:
                    st = self._states.get(name)
                if st:
                    logger.warning(
                        "   • %-20s  disabled_at=%s  last_error=%s",
                        name.upper(),
                        st.disabled_at or "N/A",
                        (st.last_error_msg or "N/A")[:60],
                    )
        else:
            logger.info("   No dead brokers 🎉")

        logger.info("=" * 70)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[BrokerFailureManager] = None
_instance_lock = threading.Lock()


def get_broker_failure_manager(
    failure_threshold: Optional[int] = None,
) -> BrokerFailureManager:
    """
    Return (or create) the process-wide :class:`BrokerFailureManager` singleton.

    Args:
        failure_threshold: Override the failure threshold only on the **first**
            call that creates the instance.  Subsequent calls ignore this
            parameter so the threshold remains stable at runtime.

    Returns:
        :class:`BrokerFailureManager` instance.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            threshold = failure_threshold if failure_threshold is not None else FAILURE_THRESHOLD
            _instance = BrokerFailureManager(failure_threshold=threshold)
            logger.info(
                f"🛡️  BrokerFailureManager singleton created "
                f"(failure_threshold={threshold})"
            )
        return _instance


def reset_broker_failure_manager() -> None:
    """
    Destroy the singleton (primarily for testing).

    After calling this function the next :func:`get_broker_failure_manager`
    call will create a fresh instance.
    """
    global _instance
    with _instance_lock:
        _instance = None
