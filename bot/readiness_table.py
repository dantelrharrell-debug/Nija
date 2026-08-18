"""
NIJA Startup Readiness Truth Table
===================================

Single source of truth for startup readiness. Replaces the previous system
of eight ``threading.Event`` objects, a ``StartupReadinessGate`` with
``threading.Condition`` / callback / catch-up logic, a
``_compute_system_ready`` function that re-derived the same truth from the
object graph, and a set of global boolean locals re-computed at thread launch.

Design rules
------------
* **One write path per component**: each subsystem calls ``mark_ready(key)``.
* **No blocking reads**: ``is_ready()`` is a pure boolean read.
* **Lock only on write**: readiness writes are serialized and versioned.
* **Idempotent telemetry**: repeated writes of the same truth are DEBUG only.
* **Diagnosable**: ``snapshot()`` returns a copy of the full table in O(n).

Keys
----
``broker_connected``  — at least one platform broker is connected and eligible
``balance_hydrated``  — startup balance sync completed
``authority_ready``   — Redis writer authority prerequisites verified
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
from typing import Dict, Iterable

logger = logging.getLogger("nija.readiness_table")

KEYS: tuple[str, ...] = (
    "broker_connected",
    "balance_hydrated",
    "authority_ready",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "execution_ready",
    "nonce_ready",
    "bootstrap_ready",
)

_TABLE: Dict[str, bool] = {k: False for k in KEYS}
_LOCK = threading.Lock()
_VERSION = 0
READINESS_CHANGED_EVENT: threading.Event = threading.Event()


def set_ready(
    component: str,
    value: bool,
    *,
    allow_regression: bool = False,
) -> bool:
    """Set readiness and return whether the canonical truth actually changed.

    Ordinary true-to-false regressions are rejected. Runtime authority loss is
    intentionally different: callers use :func:`revoke_ready`, which explicitly
    permits a terminal regression.
    """
    global _VERSION
    snapshot: Dict[str, bool]
    changed = False
    with _LOCK:
        if component not in _TABLE:
            logger.debug("readiness_table: auto-registering unknown key '%s'", component)
            _TABLE[component] = False
        current = bool(_TABLE.get(component, False))
        desired = bool(value)
        if current and not desired and not allow_regression:
            logger.warning("Prevented readiness regression | %s", component)
            return False
        if current != desired:
            _TABLE[component] = desired
            _VERSION += 1
            changed = True
        version = int(_VERSION)
        snapshot = dict(_TABLE)

    if changed:
        READINESS_CHANGED_EVENT.set()
        READINESS_CHANGED_EVENT.clear()
        try:
            try:
                from bot.startup_coordinator import get_startup_coordinator
            except ImportError:
                from startup_coordinator import get_startup_coordinator  # type: ignore[import]
            get_startup_coordinator().record_readiness(
                key=component,
                value=bool(value),
                version=version,
                table=snapshot,
            )
        except Exception:
            logger.debug("readiness_table: coordinator update skipped", exc_info=True)
    return changed


def mark_ready(component: str) -> None:
    """Mark *component* ready without re-emitting unchanged success state."""
    changed = set_ready(component, True)
    if changed:
        logger.info("READINESS_TABLE_READY component=%s table=%s", component, snapshot())
    else:
        logger.debug("READINESS_TABLE_UNCHANGED component=%s ready=true", component)


def revoke_ready(component: str, *, reason: str) -> None:
    """Revoke a dynamic readiness proof after terminal runtime invalidation."""
    changed = set_ready(component, False, allow_regression=True)
    if changed:
        logger.warning(
            "READINESS_TABLE_REVOKED component=%s reason=%s table=%s",
            component,
            reason,
            snapshot(),
        )
    else:
        logger.debug(
            "READINESS_TABLE_UNCHANGED component=%s ready=false reason=%s",
            component,
            reason,
        )


def revoke_many(components: Iterable[str], *, reason: str) -> None:
    """Atomically revoke several runtime readiness proofs as one transition."""
    global _VERSION
    normalized = tuple(dict.fromkeys(str(name) for name in components if str(name)))
    if not normalized:
        return

    with _LOCK:
        changed = False
        for component in normalized:
            if component not in _TABLE:
                _TABLE[component] = False
            elif _TABLE[component]:
                _TABLE[component] = False
                changed = True
        if changed:
            _VERSION += 1
        version = int(_VERSION)
        table = dict(_TABLE)

    if changed:
        READINESS_CHANGED_EVENT.set()
        READINESS_CHANGED_EVENT.clear()
        try:
            try:
                from bot.startup_coordinator import get_startup_coordinator
            except ImportError:
                from startup_coordinator import get_startup_coordinator  # type: ignore[import]
            get_startup_coordinator().record_readiness(
                key="__bulk_revoke__",
                value=False,
                version=version,
                table=table,
            )
        except Exception:
            logger.debug("readiness_table: coordinator bulk revoke skipped", exc_info=True)
        logger.warning(
            "READINESS_TABLE_BULK_REVOKED components=%s reason=%s version=%d table=%s",
            ",".join(normalized),
            reason,
            version,
            table,
        )
    else:
        logger.debug(
            "READINESS_TABLE_BULK_UNCHANGED components=%s reason=%s version=%d",
            ",".join(normalized),
            reason,
            version,
        )


def mark_not_applicable(component: str, *, reason: str = "not configured") -> None:
    """Mark an optional subsystem as ready for gate evaluation."""
    changed = set_ready(component, True)
    if changed:
        logger.info(
            "READINESS_TABLE_NOT_APPLICABLE component=%s reason=%s",
            component,
            reason,
        )
    else:
        logger.debug(
            "READINESS_TABLE_NOT_APPLICABLE_UNCHANGED component=%s reason=%s",
            component,
            reason,
        )


def is_ready() -> bool:
    """Return True when every registered key is True."""
    with _LOCK:
        return all(_TABLE.values())


def snapshot() -> Dict[str, bool]:
    """Return a copy of the truth table for diagnostics."""
    with _LOCK:
        return dict(_TABLE)


def get_version() -> int:
    """Return the monotonic readiness-table version."""
    with _LOCK:
        return int(_VERSION)


def snapshot_with_version() -> tuple[int, Dict[str, bool]]:
    """Return ``(version, snapshot)`` for atomic diagnostics."""
    with _LOCK:
        return int(_VERSION), dict(_TABLE)


def pending() -> list[str]:
    """Return the sorted list of keys that are still False."""
    with _LOCK:
        return sorted(k for k, v in _TABLE.items() if not v)


def reset() -> None:
    """Reset all keys to False (use before a fresh startup attempt)."""
    global _VERSION
    with _LOCK:
        for key in list(_TABLE):
            _TABLE[key] = False
        _VERSION += 1
    READINESS_CHANGED_EVENT.set()
    READINESS_CHANGED_EVENT.clear()
    logger.info("READINESS_TABLE_RESET all_keys=false")
