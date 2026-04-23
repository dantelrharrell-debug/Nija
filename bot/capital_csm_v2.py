"""Capital State Machine v2 (CSM-v2)
=====================================

Single deterministic gate for all capital-related trading decisions.

Eliminates permanently:

* **Race conditions** — single-writer contract: only ``ingest_snapshot()``
  may advance state; all mutations are atomic under ``threading.Lock``.
* **Bootstrap non-determinism** — explicit ``INITIALIZING → {READY, DEGRADED,
  BLOCKED}`` path with a blocking ``wait_for_hydration()`` barrier that raises
  ``CapitalIntegrityError`` instead of silently returning ``False``.
* **$0 ambiguity** — ``INITIALIZING`` ≠ ``BLOCKED(zero capital)``.
  ``is_hydrated=False`` means "pipeline never ran";
  ``is_hydrated=True + capital=0`` means "confirmed empty account".
* **Readiness opacity** — single ``is_live_capital_valid()`` predicate plus
  ``TradingReadiness`` enum (``READY / DEGRADED / BLOCKED``) so every caller
  speaks the same language.

State machine
-------------
::

    INITIALIZING  – no snapshot ingested; hydrated=False
                    "$0 here" means "pipeline hasn't run", not "account empty"

    READY         – all gates open:
                      LIVE_CAPITAL_VERIFIED=true
                      AND real_capital > 0
                      AND confidence_score ≥ MEDIUM (0.55)
                      AND snapshot not stale

    DEGRADED      – live_verified AND capital > 0 but quality reduced:
                      confidence LOW  OR  snapshot stale
                    Existing positions ok; new entries throttled by caller.

    BLOCKED       – trading hard-blocked.  At least one constraint fails:
                      LIVE_CAPITAL_VERIFIED != 'true'
                      OR real_capital == 0.0 (hydrated, confirmed empty)
                    Check ``blocked_reason`` for the specific cause.

Transitions (all via ``ingest_snapshot()``)::

    INITIALIZING → READY / DEGRADED / BLOCKED   (first snapshot received)
    READY        → DEGRADED / BLOCKED            (quality drops / capital lost)
    DEGRADED     → READY / BLOCKED               (quality recovers / capital lost)
    BLOCKED      → READY / DEGRADED              (env gate on + capital confirmed)

``TradingReadiness`` (external view)::

    READY    ← state == READY
    DEGRADED ← state == DEGRADED
    BLOCKED  ← state in {INITIALIZING, BLOCKED}

Barriers::

    wait_for_hydration(timeout)  – blocks until state != INITIALIZING
    wait_for_ready(timeout)      – blocks until state == READY

    Both raise ``CapitalIntegrityError`` on timeout.

Bootstrap order (MUST be enforced before tier/strategy/execution starts)::

    broker_connect()
    → balance_fetch()               # drives CapitalRefreshCoordinator
    → get_csm_v2().wait_for_hydration()   ← HARD BARRIER (this module)
    → tier_calculation()
    → strategy_init()
    → execution_loop_start()

Single predicate::

    is_live_capital_valid() → bool
        True  ↔  state == READY
        False ↔  everything else

Author: NIJA Trading Systems
Version: 2.0
"""

from __future__ import annotations

import logging
import os
import threading
from enum import Enum
from typing import Any, Dict, List, Optional

# Import CapitalIntegrityError from the canonical exceptions module so that
# ``from bot.exceptions import CapitalIntegrityError`` and
# ``from bot.capital_csm_v2 import CapitalIntegrityError`` resolve to the same
# class and can be caught interchangeably.
try:
    from bot.exceptions import CapitalIntegrityError  # noqa: F401  (re-export)
except ImportError:
    try:
        from exceptions import CapitalIntegrityError  # type: ignore[no-redef]  # noqa: F401
    except ImportError:
        class CapitalIntegrityError(RuntimeError):  # type: ignore[no-redef]
            """Raised when a capital safety invariant is violated."""

logger = logging.getLogger("nija.capital_csm_v2")

# ---------------------------------------------------------------------------
# Confidence threshold — mirrors capital_flow_state_machine.CONFIDENCE_MEDIUM_THRESHOLD
# Inlined here to avoid a circular import; keep in sync if the source changes.
# ---------------------------------------------------------------------------
_MEDIUM_CONFIDENCE_THRESHOLD: float = 0.55


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class CapitalCSMState(str, Enum):
    """Internal states of the Capital State Machine v2.

    Callers that only need a three-way signal should use
    :attr:`CapitalCSMv2.trading_readiness` (:class:`TradingReadiness`) instead.
    """

    INITIALIZING = "INITIALIZING"
    """No snapshot has been ingested yet.  ``is_hydrated`` is ``False``.

    A value of $0 here means *"the pipeline has not run"*, not *"the account
    is empty"*.  Never fall back to STARTER tier or allow trading from this
    state.
    """

    READY = "READY"
    """All hard gates are open.

    * ``LIVE_CAPITAL_VERIFIED=true`` (operator env gate)
    * ``real_capital > 0`` (confirmed non-zero balance)
    * ``confidence_score ≥ 0.55`` (MEDIUM or HIGH quality)
    * snapshot is **not** stale

    Full live trading is permitted.
    """

    DEGRADED = "DEGRADED"
    """Capital is confirmed positive and the env gate is open, but quality
    is reduced (confidence LOW or snapshot stale).

    Existing positions may continue.  New entries should be throttled or
    blocked at the caller's discretion.
    """

    BLOCKED = "BLOCKED"
    """Trading is hard-blocked.  At least one mandatory constraint is unmet.

    * ``LIVE_CAPITAL_VERIFIED != 'true'`` — operator kill-switch, or
    * ``real_capital == 0.0`` — hydrated but confirmed empty account.

    Inspect :attr:`CapitalCSMv2.blocked_reason` for the specific cause.
    """


class TradingReadiness(str, Enum):
    """Caller-facing trading readiness.  Maps directly from :class:`CapitalCSMState`."""

    READY    = "READY"
    """All systems go."""

    DEGRADED = "DEGRADED"
    """Capital confirmed; quality reduced.  Throttled trading."""

    BLOCKED  = "BLOCKED"
    """No trading.  Inspect the CSM for details."""


# ---------------------------------------------------------------------------
# Capital State Machine v2
# ---------------------------------------------------------------------------

class CapitalCSMv2:
    """
    Single deterministic gate for all capital-related trading decisions.

    **Thread-safe**: all state mutations are atomic under ``_lock``.

    **Single-writer**: only :meth:`ingest_snapshot` may advance state.  No
    other method, thread, or module is permitted to modify ``_state``.
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._state: CapitalCSMState = CapitalCSMState.INITIALIZING
        self._blocked_reason: str = "system not yet initialized (INITIALIZING)"
        self._last_snapshot: Optional[Any] = None
        self._ingest_count: int = 0
        self._history: List[Dict[str, Any]] = []

        # Threading events for blocking callers.
        #
        # _hydrated_event — set once the first snapshot is ingested
        #   (state leaves INITIALIZING).  Never cleared.
        self._hydrated_event: threading.Event = threading.Event()

        # _ready_event — set the first time state transitions to READY.
        #   Never cleared after being set (acts as a startup gate).
        #   Callers that need "currently ready" should call is_live_capital_valid()
        #   rather than testing this event directly.
        self._ready_event: threading.Event = threading.Event()

    # ------------------------------------------------------------------
    # Single write path (only entry point that changes state)
    # ------------------------------------------------------------------

    def ingest_snapshot(self, snapshot: Any) -> CapitalCSMState:
        """Ingest a capital snapshot and advance the state machine.

        This is the **only** method that may change the internal state.  All
        other callers are read-only.

        Parameters
        ----------
        snapshot:
            A :class:`~bot.capital_flow_state_machine.CapitalSnapshot` (or any
            compatible object) exposing:

            * ``real_capital: float``
            * ``confidence.confidence_score: float``   (0.0 – 1.0)
            * ``is_stale: bool``

        Returns
        -------
        CapitalCSMState
            The new state after ingestion.
        """
        # Read env gate OUTSIDE lock so we don't hold _lock during os.getenv.
        live_verified = (
            os.getenv("LIVE_CAPITAL_VERIFIED", "").lower().strip()
            in ("true", "1", "yes", "enabled")
        )

        # Extract snapshot fields defensively.
        try:
            real_capital: float = float(getattr(snapshot, "real_capital", 0.0))
        except (TypeError, ValueError):
            real_capital = 0.0

        try:
            _conf = getattr(snapshot, "confidence", None)
            confidence_score: float = (
                float(getattr(_conf, "confidence_score", 0.0))
                if _conf is not None
                else 0.0
            )
        except (TypeError, ValueError):
            confidence_score = 0.0

        try:
            is_stale: bool = bool(getattr(snapshot, "is_stale", False))
        except (TypeError, ValueError):
            is_stale = True

        # ── Determine the target state ────────────────────────────────────────
        if not live_verified:
            new_state = CapitalCSMState.BLOCKED
            new_reason = (
                "LIVE_CAPITAL_VERIFIED != 'true' — operator env gate is closed; "
                "set LIVE_CAPITAL_VERIFIED=true to enable live trading"
            )
        elif real_capital <= 0.0:
            new_state = CapitalCSMState.BLOCKED
            new_reason = (
                "real_capital == 0.0 — hydrated but account is empty or "
                "all broker fetches returned zero"
            )
        elif confidence_score >= _MEDIUM_CONFIDENCE_THRESHOLD and not is_stale:
            new_state = CapitalCSMState.READY
            new_reason = (
                f"capital=${real_capital:.2f} "
                f"confidence={confidence_score:.3f} "
                f"stale={is_stale}"
            )
        else:
            new_state = CapitalCSMState.DEGRADED
            new_reason = (
                f"capital=${real_capital:.2f} "
                f"confidence={confidence_score:.3f} "
                f"(below MEDIUM={_MEDIUM_CONFIDENCE_THRESHOLD}) "
                f"stale={is_stale}"
            )

        # ── Atomic state update ───────────────────────────────────────────────
        with self._lock:
            old_state = self._state
            self._state = new_state
            self._blocked_reason = new_reason if new_state == CapitalCSMState.BLOCKED else ""
            self._last_snapshot = snapshot
            self._ingest_count += 1
            record: Dict[str, Any] = {
                "seq": self._ingest_count,
                "from": old_state.value,
                "to": new_state.value,
                "reason": new_reason,
            }
            self._history.append(record)
            # Keep history bounded to the last 50 transitions.
            if len(self._history) > 50:
                self._history = self._history[-50:]

        # ── Fire events AFTER releasing lock to avoid deadlocks ───────────────

        # Hydrated: set on any first ingest (state leaving INITIALIZING).
        if old_state == CapitalCSMState.INITIALIZING:
            self._hydrated_event.set()
            logger.info(
                "🔑 [CSM-v2] First snapshot ingested — INITIALIZING → %s  "
                "reason=%s",
                new_state.value,
                new_reason,
            )
        elif old_state != new_state:
            logger.info(
                "🔄 [CSM-v2] %s → %s  reason=%s",
                old_state.value,
                new_state.value,
                new_reason,
            )

        # Ready: set the first time state == READY (startup gate; never cleared).
        if new_state == CapitalCSMState.READY:
            self._ready_event.set()

        return new_state

    # ------------------------------------------------------------------
    # Blocking barriers (MUST run before tier/strategy/execution init)
    # ------------------------------------------------------------------

    def wait_for_hydration(self, timeout: float = 30.0) -> None:
        """Block until the first snapshot has been ingested.

        "Hydrated" means the capital pipeline has run at least once and
        ``state != INITIALIZING``.  The confirmed balance may still be zero
        (``BLOCKED(zero)``); this barrier only guarantees the pipeline ran.

        This barrier **MUST** execute:

        * **BEFORE** tier calculation
        * **BEFORE** strategy init
        * **BEFORE** the execution engine starts

        Parameters
        ----------
        timeout:
            Maximum seconds to wait.  Default 30 s.

        Raises
        ------
        CapitalIntegrityError
            If ``timeout`` elapses without any snapshot being ingested.

        Example
        -------
        ::

            from bot.capital_csm_v2 import get_csm_v2, CapitalIntegrityError

            try:
                get_csm_v2().wait_for_hydration()
            except CapitalIntegrityError:
                logger.critical("FATAL: capital pipeline did not run — aborting")
                raise
        """
        if self._hydrated_event.wait(timeout=timeout):
            logger.info(
                "✅ [CSM-v2] Capital hydration confirmed (state=%s)",
                self.state.value,
            )
            return
        raise CapitalIntegrityError(
            f"Capital hydration timeout: no valid balance snapshot received within "
            f"{timeout:.0f}s.  Ensure brokers are connected and the capital pipeline "
            f"has been started before calling this barrier.  "
            f"(CSM-v2 state={self.state.value})"
        )

    def wait_for_ready(self, timeout: float = 30.0) -> bool:
        """Block until the CSM reaches :attr:`CapitalCSMState.READY`.

        ``READY`` requires all of:

        * ``LIVE_CAPITAL_VERIFIED=true``
        * ``real_capital > 0``
        * ``confidence_score ≥ 0.55``
        * snapshot is not stale

        Parameters
        ----------
        timeout:
            Maximum seconds to wait.  Default 30 s.

        Returns
        -------
        bool
            ``True`` if the CSM reached ``READY`` within *timeout* seconds,
            ``False`` otherwise.  The caller is responsible for aborting if
            ``False`` is returned.
        """
        if self._ready_event.wait(timeout=timeout):
            # Verify we are still READY (not just "was once ready").
            with self._lock:
                current = self._state
            if current == CapitalCSMState.READY:
                logger.info("✅ [CSM-v2] Capital READY confirmed")
                return True
        with self._lock:
            current = self._state
            reason = self._blocked_reason
        logger.critical(
            "❌ [CSM-v2] Capital NOT ready after %.0fs: state=%s blocked_reason=%r",
            timeout,
            current.value,
            reason,
        )
        return False

    # ------------------------------------------------------------------
    # Read-only accessors (all non-blocking)
    # ------------------------------------------------------------------

    @property
    def state(self) -> CapitalCSMState:
        """Current internal state (thread-safe, non-blocking)."""
        with self._lock:
            return self._state

    @property
    def is_hydrated(self) -> bool:
        """``True`` after the first snapshot has been ingested.

        Equivalent to ``state != INITIALIZING``.  Uses the underlying
        ``threading.Event`` so it is atomic without acquiring ``_lock``.
        """
        return self._hydrated_event.is_set()

    @property
    def trading_readiness(self) -> TradingReadiness:
        """Caller-facing readiness enum.

        * ``READY``    — all gates open; live trading allowed.
        * ``DEGRADED`` — capital positive; quality reduced; throttled.
        * ``BLOCKED``  — no trading; see :attr:`blocked_reason`.
        """
        with self._lock:
            s = self._state
        if s == CapitalCSMState.READY:
            return TradingReadiness.READY
        if s == CapitalCSMState.DEGRADED:
            return TradingReadiness.DEGRADED
        return TradingReadiness.BLOCKED

    @property
    def blocked_reason(self) -> str:
        """Human-readable reason when state is ``BLOCKED`` (empty otherwise)."""
        with self._lock:
            return self._blocked_reason

    @property
    def last_snapshot(self) -> Optional[Any]:
        """Most-recently ingested snapshot, or ``None`` before first ingest."""
        with self._lock:
            return self._last_snapshot

    @property
    def ingest_count(self) -> int:
        """Total number of snapshots ingested since construction."""
        with self._lock:
            return self._ingest_count

    # ------------------------------------------------------------------
    # Primary trading gate
    # ------------------------------------------------------------------

    def is_live_capital_valid(self) -> bool:
        """Return ``True`` only when the system is fully ready to trade live.

        Equivalent to ``trading_readiness == TradingReadiness.READY``, which
        in turn requires all of:

        * ``LIVE_CAPITAL_VERIFIED=true`` (operator env gate)
        * at least one snapshot ingested (hydrated)
        * ``real_capital > 0`` (confirmed non-zero balance)
        * ``confidence_score ≥ 0.55`` (snapshot quality MEDIUM+)
        * snapshot is not stale

        This is the **single predicate** that :class:`~bot.execution_engine.ExecutionEngine`,
        the strategy loop, and :class:`~bot.bootstrap_state_machine.BootstrapStateMachine`
        should use to gate live trading::

            from bot.capital_csm_v2 import is_live_capital_valid, CapitalIntegrityError

            if not is_live_capital_valid():
                raise CapitalIntegrityError(
                    "Live trading blocked: capital not fully validated"
                )
        """
        with self._lock:
            return self._state == CapitalCSMState.READY

    # ------------------------------------------------------------------
    # Observability helpers
    # ------------------------------------------------------------------

    def status_dict(self) -> Dict[str, Any]:
        """Serializable status snapshot for health/monitoring endpoints."""
        with self._lock:
            snap = self._last_snapshot
            state = self._state
            reason = self._blocked_reason
            count = self._ingest_count
            history = list(self._history[-5:])

        real_cap: Optional[float] = None
        confidence: Optional[float] = None
        if snap is not None:
            try:
                real_cap = float(getattr(snap, "real_capital", 0.0))
            except (TypeError, ValueError):
                pass
            try:
                _conf = getattr(snap, "confidence", None)
                if _conf is not None:
                    confidence = float(getattr(_conf, "confidence_score", 0.0))
            except (TypeError, ValueError):
                pass

        return {
            "state": state.value,
            "trading_readiness": self.trading_readiness.value,
            "is_hydrated": self._hydrated_event.is_set(),
            "is_live_capital_valid": state == CapitalCSMState.READY,
            "blocked_reason": reason,
            "ingest_count": count,
            "real_capital": real_cap,
            "confidence_score": confidence,
            "env_LIVE_CAPITAL_VERIFIED": os.getenv("LIVE_CAPITAL_VERIFIED", "not_set"),
            "recent_history": history,
        }

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most recent *limit* state-transition records."""
        with self._lock:
            return list(self._history[-limit:])


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_csm_v2_instance: Optional[CapitalCSMv2] = None
_csm_v2_lock: threading.Lock = threading.Lock()


def get_csm_v2() -> CapitalCSMv2:
    """Return the process-wide :class:`CapitalCSMv2` singleton (lazy-init, thread-safe)."""
    global _csm_v2_instance
    if _csm_v2_instance is None:
        with _csm_v2_lock:
            if _csm_v2_instance is None:
                _csm_v2_instance = CapitalCSMv2()
                logger.debug("[CSM-v2] singleton created")
    return _csm_v2_instance


def reset_csm_v2_singleton() -> None:
    """Reset the singleton for unit-test teardown.  **Not for production use.**"""
    global _csm_v2_instance
    with _csm_v2_lock:
        _csm_v2_instance = None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def is_live_capital_valid() -> bool:
    """Return ``True`` iff live trading is fully permitted.

    Delegates to :meth:`CapitalCSMv2.is_live_capital_valid` on the singleton.

    Import this function anywhere a simple boolean gate is needed::

        from bot.capital_csm_v2 import is_live_capital_valid, CapitalIntegrityError

        if not is_live_capital_valid():
            raise CapitalIntegrityError("Live trading blocked: capital not fully validated")
    """
    return get_csm_v2().is_live_capital_valid()
