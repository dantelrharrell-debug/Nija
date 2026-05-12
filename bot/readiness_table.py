"""
NIJA Startup Readiness Truth Table
===================================

Single source of truth for startup readiness.  Replaces the previous system
of eight ``threading.Event`` objects, a ``StartupReadinessGate`` with
``threading.Condition`` / callback / catch-up logic, a
``_compute_system_ready`` function that re-derived the same truth from the
object graph, and a set of global boolean locals re-computed at thread launch.

Design rules
------------
* **One write path per component**: each subsystem calls ``mark_ready(key)``
  exactly once.  There are no events to set, no gates to signal, and no
  catch-up replays.
* **No blocking reads**: ``is_ready()`` is a pure boolean read.  The startup
  path polls with a bounded deadline; there is no ``Condition.wait()`` and
  therefore no possibility of deadlock.
* **Lock only on write**: ``_LOCK`` is only held during writes.  Reads of
  Python ``bool`` values are atomic in CPython, so ``is_ready()`` and
  ``snapshot()`` do not need the lock.
* **Diagnosable**: ``snapshot()`` returns a copy of the full table in O(n).

Keys
----
``broker_connected``  — at least one platform broker is connected and eligible
``balance_hydrated``  — startup balance sync completed
``capital_ready``     — capital authority gate is open (BootstrapFSM ≥ CAPITAL_READY)
``risk_ready``        — risk / strategy subsystem initialized
``strategy_ready``    — TradingStrategy singleton published
``execution_ready``   — execution engine wired to strategy
``nonce_ready``       — Kraken nonce FSM authorized (auto-True for Coinbase-only)
``bootstrap_ready``   — bootstrap kernel reached INIT_COMPLETE and is ready for the pre-thread handoff barrier
"""

from __future__ import annotations

import logging
import threading
from typing import Dict

logger = logging.getLogger("nija.readiness_table")

# ---------------------------------------------------------------------------
# Canonical keys
# ---------------------------------------------------------------------------

KEYS: tuple[str, ...] = (
    "broker_connected",
    "balance_hydrated",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "execution_ready",
    "nonce_ready",
    "bootstrap_ready",
)

# ---------------------------------------------------------------------------
# Module-level truth table
# ---------------------------------------------------------------------------

_TABLE: Dict[str, bool] = {k: False for k in KEYS}
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Write API
# ---------------------------------------------------------------------------

def mark_ready(component: str) -> None:
    """Mark *component* as ready.

    If *component* is not one of the canonical keys it is accepted anyway so
    that callers do not need to track the exact key list.
    """
    with _LOCK:
        if component not in _TABLE:
            logger.debug("readiness_table: auto-registering unknown key '%s'", component)
            _TABLE[component] = False
        _TABLE[component] = True
    logger.critical(
        "✅ READINESS_TABLE mark_ready=%s table=%s",
        component,
        _TABLE,
    )


def mark_not_applicable(component: str, *, reason: str = "not configured") -> None:
    """Mark *component* as not applicable (treated as ready for gate evaluation).

    Use this for optional subsystems that are skipped in the current
    deployment (e.g. ``nonce_ready`` on a Coinbase-only bot).
    """
    with _LOCK:
        if component not in _TABLE:
            _TABLE[component] = False
        _TABLE[component] = True
    logger.info(
        "⏩ READINESS_TABLE mark_not_applicable=%s reason=%s",
        component,
        reason,
    )


# ---------------------------------------------------------------------------
# Read API
# ---------------------------------------------------------------------------

def is_ready() -> bool:
    """Return True when every key in the table is True.

    Acquires the lock to produce a consistent view across all keys.
    """
    with _LOCK:
        return all(_TABLE.values())


def snapshot() -> Dict[str, bool]:
    """Return a copy of the truth table for diagnostics."""
    with _LOCK:
        return dict(_TABLE)


def pending() -> list[str]:
    """Return the sorted list of keys that are still False."""
    with _LOCK:
        return sorted(k for k, v in _TABLE.items() if not v)


# ---------------------------------------------------------------------------
# Reset (for warm restarts / tests)
# ---------------------------------------------------------------------------

def reset() -> None:
    """Reset all keys to False (use before a fresh startup attempt)."""
    with _LOCK:
        for k in list(_TABLE):
            _TABLE[k] = False
    logger.info("🔄 READINESS_TABLE reset — all keys False")
