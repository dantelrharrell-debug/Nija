"""NIJA Capital Flow State Machine
===================================

Deterministic, single-writer capital-pipeline infrastructure.

Architecture
------------
The pipeline has five explicit, sequential stages that run inside
``CapitalRefreshCoordinator.execute_refresh()``::

    STAGE 1 – KRAKEN_FETCH
        Call ``broker.get_account_balance()`` for every connected broker.
        Record per-broker fetch timestamps and Kraken-specific diagnostics.

    STAGE 2 – NORMALIZE
        Each broker's own ``get_account_balance()`` already normalises asset
        codes (e.g. XXBT→BTC, ZUSD→USD) and converts crypto holdings to USD.
        This stage aggregates the per-broker scalars and falls back to the
        last-known balance when a fetch returns zero or raises an exception.

    STAGE 3 – VALUATE
        Derive real / usable / risk capital from the aggregated balances,
        the authority's reserve fraction, and the current open-exposure figure.

    STAGE 4 – CONFIDENCE
        Compute an immutable ``CapitalConfidence`` from three orthogonal inputs:
          * freshness  — seconds since the last successful Kraken balance fetch
          * pricing    — fraction of non-USD Kraken assets priced successfully
          * errors     — consecutive Kraken API error count (0 = healthy)

    STAGE 5 – PUBLISH
        Build an immutable ``CapitalSnapshot`` and call
        ``CapitalAuthority.publish_snapshot(snapshot, writer_id=WRITER_ID)``.
        This is the **only** write path that the authority accepts.

Single-writer contract
----------------------
``WRITER_ID = "mabm_capital_refresh_coordinator"``

``CapitalAuthority.publish_snapshot()`` rejects any call whose *writer_id*
does not match this constant.  All other code is read-only.

State machines
--------------
``CapitalBootstrapStateMachine`` — one-time startup sequencing::

    BOOT_IDLE → WAIT_PLATFORM → REFRESH_REQUESTED → REFRESH_IN_FLIGHT
             → SNAPSHOT_EVALUATING → READY
                                  → DEGRADED → REFRESH_REQUESTED (retry)
                                  → FAILED   → REFRESH_REQUESTED (recovery)

``CapitalRuntimeStateMachine`` — per-cycle health tracking::

    RUN_READY     → RUN_STALE      (snapshot age > TTL)
    RUN_STALE     → RUN_REFRESHING (REFRESH_REQUESTED)
    RUN_REFRESHING→ RUN_READY      (confidence ≥ MEDIUM)
    RUN_REFRESHING→ RUN_DEGRADED   (confidence < MEDIUM)
    RUN_DEGRADED  → RUN_READY      (confidence recovers ≥ MEDIUM)
    RUN_DEGRADED  → RUN_HALTED     (N consecutive LOW cycles or capital = 0)
    RUN_HALTED    → RUN_REFRESHING (recovery requested)

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nija.capital_flow_sm")

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Confidence threshold above which a snapshot is classified as HIGH quality.
CONFIDENCE_HIGH_THRESHOLD: float = 0.80

#: Confidence threshold above which a snapshot is classified as MEDIUM quality.
CONFIDENCE_MEDIUM_THRESHOLD: float = 0.55

#: Default snapshot freshness TTL (seconds).  Matches
#: ``_DEFAULT_FRESHNESS_TTL_S`` in ``capital_authority.py`` and the per-cycle
#: refresh cadence so a missed refresh is caught before the next trade.
FRESHNESS_TTL_S: float = 90.0

#: The only writer_id accepted by ``CapitalAuthority.publish_snapshot()``.
#: Any call that passes a different id is silently rejected.
WRITER_ID: str = "mabm_capital_refresh_coordinator"

# ---------------------------------------------------------------------------
# Stage 4 — Confidence model
# ---------------------------------------------------------------------------


class CapitalConfidenceBand(str, Enum):
    """Qualitative quality band derived from ``CapitalConfidence.confidence_score``."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class CapitalConfidence:
    """
    Immutable, data-quality score for a capital snapshot.

    All three component scores live in ``[0, 1]``.  The composite
    ``confidence_score`` is a weighted average::

        score = 0.50 * freshness_score
              + 0.35 * pricing_score
              + 0.15 * error_score

    Weights reflect operational priority: data freshness matters most, then
    pricing coverage, then API health.
    """

    freshness_score: float   # 0..1  — decays linearly over FRESHNESS_TTL_S
    pricing_score: float     # 0..1  — fraction of non-USD assets successfully priced
    error_score: float       # 0..1  — 1/(1+consecutive_errors)
    confidence_score: float  # 0..1  — weighted composite
    band: CapitalConfidenceBand

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def compute(
        kraken_response_age_s: float,
        assets_priced_success_pct: float,
        api_error_count: int,
        freshness_ttl_s: float = FRESHNESS_TTL_S,
    ) -> "CapitalConfidence":
        """
        Derive a ``CapitalConfidence`` from raw pipeline metrics.

        Parameters
        ----------
        kraken_response_age_s:
            Seconds since the last successful Kraken balance fetch.  A value
            of ``float('inf')`` means "never fetched" → freshness_score = 0.
        assets_priced_success_pct:
            Fraction of non-USD Kraken assets successfully converted to USD
            during the valuation stage (0..1).
        api_error_count:
            Consecutive Kraken API error count.  0 means fully healthy.
        freshness_ttl_s:
            Denominator for the linear freshness decay.  Defaults to 90 s.
        """
        denom = max(freshness_ttl_s, 1.0)
        freshness = max(0.0, min(1.0, 1.0 - kraken_response_age_s / denom))
        pricing = max(0.0, min(1.0, float(assets_priced_success_pct)))
        errors = 1.0 / (1.0 + max(0, int(api_error_count)))
        score = round(0.50 * freshness + 0.35 * pricing + 0.15 * errors, 6)
        if score >= CONFIDENCE_HIGH_THRESHOLD:
            band = CapitalConfidenceBand.HIGH
        elif score >= CONFIDENCE_MEDIUM_THRESHOLD:
            band = CapitalConfidenceBand.MEDIUM
        else:
            band = CapitalConfidenceBand.LOW
        return CapitalConfidence(
            freshness_score=freshness,
            pricing_score=pricing,
            error_score=errors,
            confidence_score=score,
            band=band,
        )


# ---------------------------------------------------------------------------
# Stage 5 — Immutable snapshot model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapitalSnapshot:
    """
    Immutable capital state produced atomically by
    :class:`CapitalRefreshCoordinator` and published to
    ``CapitalAuthority`` via ``publish_snapshot()``.

    Downstream readers obtain the most-recently accepted instance via
    ``CapitalAuthority.get_typed_snapshot()``.  They must **never** mutate it.
    """

    # ── Core balances ─────────────────────────────────────────────────────
    real_capital: float         # gross USD+stablecoin equity across all brokers
    usable_capital: float       # real * (1 - reserve_pct)
    risk_capital: float         # usable - open_exposure_usd
    open_exposure_usd: float    # sum of all live open-position notional values
    reserve_pct: float          # authority's reserve fraction at publish time

    # ── Broker breakdown ──────────────────────────────────────────────────
    broker_balances: Dict[str, float]  # {broker_id: raw_usd_balance}
    broker_count: int                  # number of non-zero brokers in this snapshot
    expected_brokers: int              # authority's expected_brokers at publish time

    # ── Timing ────────────────────────────────────────────────────────────
    computed_at: datetime       # UTC wall-clock when the snapshot was built
    snapshot_age_s: float       # age of the *previous* CA snapshot at compute time

    # ── Confidence inputs (pipeline observability) ─────────────────────────
    kraken_response_age_s: float        # seconds since last successful Kraken fetch
    assets_priced_success_pct: float    # fraction of non-USD assets priced (0..1)
    api_error_count: int                # consecutive Kraken API errors at publish time

    # ── Derived confidence ─────────────────────────────────────────────────
    confidence: CapitalConfidence

    # ── Validity flags ─────────────────────────────────────────────────────
    is_fresh: bool   # True  ↔ broker threshold met AND age ≤ TTL AND real > 0
                     #   normal mode:       broker_count ≥ expected_brokers
                     #   opportunistic mode: broker_count ≥ 1
    is_stale: bool   # True  ↔ not is_fresh

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain-dict representation for dashboards and logging."""
        return {
            "real_capital": self.real_capital,
            "usable_capital": self.usable_capital,
            "risk_capital": self.risk_capital,
            "open_exposure_usd": self.open_exposure_usd,
            "reserve_pct": self.reserve_pct,
            "broker_balances": dict(self.broker_balances),
            "broker_count": self.broker_count,
            "expected_brokers": self.expected_brokers,
            "computed_at": self.computed_at.isoformat(),
            "snapshot_age_s": self.snapshot_age_s,
            "kraken_response_age_s": self.kraken_response_age_s,
            "assets_priced_success_pct": self.assets_priced_success_pct,
            "api_error_count": self.api_error_count,
            "confidence_score": self.confidence.confidence_score,
            "confidence_band": self.confidence.band.value,
            "freshness_score": self.confidence.freshness_score,
            "pricing_score": self.confidence.pricing_score,
            "error_score": self.confidence.error_score,
            "is_fresh": self.is_fresh,
            "is_stale": self.is_stale,
        }


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class CapitalEventType(str, Enum):
    """Life-cycle events emitted by the capital pipeline."""

    REFRESH_REQUESTED = "REFRESH_REQUESTED"
    REFRESH_STARTED = "REFRESH_STARTED"
    BROKER_BALANCE_COLLECTED = "BROKER_BALANCE_COLLECTED"
    SNAPSHOT_COMPUTED = "SNAPSHOT_COMPUTED"
    SNAPSHOT_PUBLISHED = "SNAPSHOT_PUBLISHED"
    SNAPSHOT_REJECTED = "SNAPSHOT_REJECTED"
    CAPITAL_READY = "CAPITAL_READY"
    CAPITAL_DEGRADED = "CAPITAL_DEGRADED"
    CAPITAL_STALE = "CAPITAL_STALE"


@dataclass
class CapitalEvent:
    """A single event emitted onto :class:`CapitalEventBus`."""

    event_type: CapitalEventType
    trigger: str = ""
    snapshot: Optional[CapitalSnapshot] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    emitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CapitalEventBus:
    """
    In-process, non-blocking event queue for capital-pipeline life-cycle events.

    Producers call :meth:`emit` or the convenience :meth:`request_refresh`.
    Consumers register callbacks via :meth:`subscribe` and receive events
    when :meth:`dispatch_pending` is called (typically at the start of each
    trading cycle).
    """

    def __init__(self) -> None:
        self._queue: "queue.Queue[CapitalEvent]" = queue.Queue()
        self._subscribers: List[Callable[[CapitalEvent], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, callback: Callable[[CapitalEvent], None]) -> None:
        """Register a callback to be invoked during :meth:`dispatch_pending`."""
        with self._lock:
            self._subscribers.append(callback)

    def emit(self, event: CapitalEvent) -> None:
        """Enqueue an event.  Non-blocking; never raises."""
        self._queue.put_nowait(event)

    def request_refresh(self, trigger: str) -> None:
        """
        The only way non-writer modules may trigger a capital refresh.

        Emits a ``REFRESH_REQUESTED`` event; the coordinator handles it
        synchronously via :meth:`CapitalRefreshCoordinator.execute_refresh`.
        """
        self.emit(CapitalEvent(
            event_type=CapitalEventType.REFRESH_REQUESTED,
            trigger=trigger,
        ))

    def dispatch_pending(self) -> int:
        """
        Drain the internal queue and call all registered subscribers.

        Returns the number of events dispatched.  Safe to call from any thread.
        """
        count = 0
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                subs = list(self._subscribers)
            for cb in subs:
                try:
                    cb(event)
                except Exception as exc:
                    logger.debug("[CapitalEventBus] subscriber error: %s", exc)
            count += 1
        return count


# Module-level singleton ─────────────────────────────────────────────────────
_event_bus: Optional[CapitalEventBus] = None
_event_bus_lock = threading.Lock()


def get_capital_event_bus() -> CapitalEventBus:
    """Return the process-wide :class:`CapitalEventBus` singleton."""
    global _event_bus
    if _event_bus is None:
        with _event_bus_lock:
            if _event_bus is None:
                _event_bus = CapitalEventBus()
    return _event_bus


# ---------------------------------------------------------------------------
# Bootstrap state machine
# ---------------------------------------------------------------------------


class CapitalBootstrapState(str, Enum):
    """States for the one-time startup capital readiness sequence."""

    BOOT_IDLE = "BOOT_IDLE"
    WAIT_PLATFORM = "WAIT_PLATFORM"
    REFRESH_REQUESTED = "REFRESH_REQUESTED"
    REFRESH_IN_FLIGHT = "REFRESH_IN_FLIGHT"
    SNAPSHOT_EVALUATING = "SNAPSHOT_EVALUATING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class CapitalBootstrapStateMachine:
    """
    Deterministic startup sequencing for capital readiness.

    Forward path::

        BOOT_IDLE → WAIT_PLATFORM → REFRESH_REQUESTED → REFRESH_IN_FLIGHT
                 → SNAPSHOT_EVALUATING → READY

    Retry paths::

        SNAPSHOT_EVALUATING → DEGRADED → REFRESH_REQUESTED  (retry)
        SNAPSHOT_EVALUATING → FAILED   → REFRESH_REQUESTED  (recovery)

    ``READY`` is the terminal success state.
    """

    _VALID_TRANSITIONS: Dict[CapitalBootstrapState, List[CapitalBootstrapState]] = {
        CapitalBootstrapState.BOOT_IDLE: [CapitalBootstrapState.WAIT_PLATFORM],
        CapitalBootstrapState.WAIT_PLATFORM: [CapitalBootstrapState.REFRESH_REQUESTED],
        CapitalBootstrapState.REFRESH_REQUESTED: [CapitalBootstrapState.REFRESH_IN_FLIGHT],
        CapitalBootstrapState.REFRESH_IN_FLIGHT: [CapitalBootstrapState.SNAPSHOT_EVALUATING],
        CapitalBootstrapState.SNAPSHOT_EVALUATING: [
            CapitalBootstrapState.READY,
            CapitalBootstrapState.DEGRADED,
            CapitalBootstrapState.FAILED,
        ],
        CapitalBootstrapState.DEGRADED: [CapitalBootstrapState.REFRESH_REQUESTED],
        CapitalBootstrapState.FAILED: [CapitalBootstrapState.REFRESH_REQUESTED],
        CapitalBootstrapState.READY: [],  # terminal — no further transitions
    }

    def __init__(self) -> None:
        self._state = CapitalBootstrapState.BOOT_IDLE
        self._lock = threading.Lock()
        self._ready_event = threading.Event()
        # Callbacks fired once when the FSM enters READY for the first time.
        self._on_ready_callbacks: List[Callable[[], None]] = []

    @property
    def state(self) -> CapitalBootstrapState:
        with self._lock:
            return self._state

    def transition(self, new_state: CapitalBootstrapState, reason: str = "") -> bool:
        """
        Attempt a state transition.

        Returns ``True`` on success.  Invalid transitions are logged at DEBUG
        level and return ``False`` without mutating state.
        """
        with self._lock:
            allowed = self._VALID_TRANSITIONS.get(self._state, [])
            if new_state not in allowed:
                logger.debug(
                    "[BootstrapFSM] invalid transition %s → %s (%s) — ignored",
                    self._state.value, new_state.value, reason or "no_reason",
                )
                return False
            old = self._state
            self._state = new_state
            just_ready = new_state == CapitalBootstrapState.READY
            callbacks = list(self._on_ready_callbacks) if just_ready else []
            if just_ready:
                self._on_ready_callbacks.clear()
        logger.info(
            "[BootstrapFSM] %s → %s  reason=%s",
            old.value, new_state.value, reason or "—",
        )
        if just_ready:
            self._ready_event.set()
            for cb in callbacks:
                try:
                    cb()
                except Exception:
                    logger.exception("on_ready callback raised an exception: %s", cb)
        return True

    def register_on_ready(self, callback: Callable[[], None]) -> None:
        """
        Register *callback* to be called exactly once when the FSM enters READY.

        If the FSM is already in READY state, *callback* is invoked immediately
        (synchronously, in the calling thread) before this method returns.

        Callbacks are fired **outside** the internal lock so they may safely
        call :attr:`is_ready`, :meth:`wait_ready`, or any other FSM method
        without deadlocking.  Exceptions raised by a callback are logged at
        ERROR level but do not prevent other callbacks from running.
        """
        with self._lock:
            if self._state == CapitalBootstrapState.READY:
                fire_now = True
            else:
                self._on_ready_callbacks.append(callback)
                fire_now = False
        if fire_now:
            try:
                callback()
            except Exception:
                logger.exception("on_ready callback raised an exception: %s", callback)

    def wait_ready(self, timeout: Optional[float] = None) -> bool:
        """Block until the FSM reaches READY or *timeout* expires."""
        return self._ready_event.wait(timeout=timeout)

    @property
    def is_ready(self) -> bool:
        return self._state == CapitalBootstrapState.READY

    @property
    def is_failed(self) -> bool:
        return self._state == CapitalBootstrapState.FAILED

    @property
    def is_degraded(self) -> bool:
        return self._state == CapitalBootstrapState.DEGRADED


# Module-level singleton ─────────────────────────────────────────────────────
_bootstrap_fsm: Optional[CapitalBootstrapStateMachine] = None
_bootstrap_fsm_lock = threading.Lock()


def get_capital_bootstrap_fsm() -> CapitalBootstrapStateMachine:
    """Return the process-wide :class:`CapitalBootstrapStateMachine` singleton."""
    global _bootstrap_fsm
    if _bootstrap_fsm is None:
        with _bootstrap_fsm_lock:
            if _bootstrap_fsm is None:
                _bootstrap_fsm = CapitalBootstrapStateMachine()
    return _bootstrap_fsm


# ---------------------------------------------------------------------------
# Runtime state machine
# ---------------------------------------------------------------------------


class CapitalRuntimeState(str, Enum):
    """States for ongoing per-cycle capital health tracking."""

    RUN_READY = "RUN_READY"
    RUN_STALE = "RUN_STALE"
    RUN_REFRESHING = "RUN_REFRESHING"
    RUN_DEGRADED = "RUN_DEGRADED"
    RUN_HALTED = "RUN_HALTED"


class CapitalRuntimeStateMachine:
    """
    Per-cycle capital health tracker.

    Driven by ``on_snapshot_received()`` after every successful coordinator
    publish.  The state directly informs whether new entries are allowed::

        RUN_READY, RUN_DEGRADED  → trading allowed (degraded = reduced confidence)
        RUN_STALE                → refresh imminent; trading allowed
        RUN_REFRESHING           → in-flight; use last accepted snapshot
        RUN_HALTED               → trading blocked until recovery
    """

    _VALID_TRANSITIONS: Dict[CapitalRuntimeState, List[CapitalRuntimeState]] = {
        CapitalRuntimeState.RUN_READY: [
            CapitalRuntimeState.RUN_STALE,
            CapitalRuntimeState.RUN_REFRESHING,
        ],
        CapitalRuntimeState.RUN_STALE: [CapitalRuntimeState.RUN_REFRESHING],
        CapitalRuntimeState.RUN_REFRESHING: [
            CapitalRuntimeState.RUN_READY,
            CapitalRuntimeState.RUN_DEGRADED,
        ],
        CapitalRuntimeState.RUN_DEGRADED: [
            CapitalRuntimeState.RUN_READY,
            CapitalRuntimeState.RUN_HALTED,
            CapitalRuntimeState.RUN_REFRESHING,
        ],
        CapitalRuntimeState.RUN_HALTED: [CapitalRuntimeState.RUN_REFRESHING],
    }

    def __init__(self, max_degraded_cycles: int = 5) -> None:
        self._state = CapitalRuntimeState.RUN_READY
        self._lock = threading.Lock()
        self._degraded_cycle_count: int = 0
        self._max_degraded_cycles = max_degraded_cycles

    @property
    def state(self) -> CapitalRuntimeState:
        with self._lock:
            return self._state

    def transition(self, new_state: CapitalRuntimeState, reason: str = "") -> bool:
        """Attempt a state transition.  Returns ``True`` on success."""
        with self._lock:
            allowed = self._VALID_TRANSITIONS.get(self._state, [])
            if new_state not in allowed:
                logger.debug(
                    "[RuntimeFSM] invalid transition %s → %s (%s) — ignored",
                    self._state.value, new_state.value, reason or "no_reason",
                )
                return False
            old = self._state
            self._state = new_state
            if new_state == CapitalRuntimeState.RUN_DEGRADED:
                self._degraded_cycle_count += 1
            elif new_state in (
                CapitalRuntimeState.RUN_READY,
                CapitalRuntimeState.RUN_HALTED,
            ):
                self._degraded_cycle_count = 0
        logger.info(
            "[RuntimeFSM] %s → %s  reason=%s",
            old.value, new_state.value, reason or "—",
        )
        return True

    def on_snapshot_received(
        self,
        snapshot: CapitalSnapshot,
        bus: Optional[CapitalEventBus] = None,
    ) -> CapitalRuntimeState:
        """
        Drive state transitions based on a freshly published snapshot.

        May emit ``CAPITAL_READY``, ``CAPITAL_DEGRADED``, or
        ``CAPITAL_STALE`` events onto *bus*.
        """
        confidence = snapshot.confidence
        capital_zero = snapshot.real_capital <= 0.0

        with self._lock:
            current = self._state
            degraded_count = self._degraded_cycle_count

        # ── RUN_REFRESHING → outcome ──────────────────────────────────────────
        if current == CapitalRuntimeState.RUN_REFRESHING:
            if capital_zero:
                self.transition(CapitalRuntimeState.RUN_DEGRADED, "capital_zero")
                if bus:
                    bus.emit(CapitalEvent(
                        event_type=CapitalEventType.CAPITAL_DEGRADED,
                        trigger="capital_zero",
                        snapshot=snapshot,
                    ))
            elif confidence.band in (
                CapitalConfidenceBand.HIGH, CapitalConfidenceBand.MEDIUM
            ):
                self.transition(CapitalRuntimeState.RUN_READY, confidence.band.value)
                if bus:
                    bus.emit(CapitalEvent(
                        event_type=CapitalEventType.CAPITAL_READY,
                        trigger=confidence.band.value,
                        snapshot=snapshot,
                    ))
            else:
                self.transition(CapitalRuntimeState.RUN_DEGRADED, "confidence_low")
                if bus:
                    bus.emit(CapitalEvent(
                        event_type=CapitalEventType.CAPITAL_DEGRADED,
                        trigger="confidence_low",
                        snapshot=snapshot,
                    ))
            return self.state

        # ── RUN_DEGRADED → recovery or halt ──────────────────────────────────
        if current == CapitalRuntimeState.RUN_DEGRADED:
            if not capital_zero and confidence.band in (
                CapitalConfidenceBand.HIGH, CapitalConfidenceBand.MEDIUM
            ):
                self.transition(CapitalRuntimeState.RUN_READY, "confidence_recovered")
                if bus:
                    bus.emit(CapitalEvent(
                        event_type=CapitalEventType.CAPITAL_READY,
                        trigger="confidence_recovered",
                        snapshot=snapshot,
                    ))
            elif capital_zero or degraded_count >= self._max_degraded_cycles:
                reason = "capital_zero" if capital_zero else "degraded_too_long"
                self.transition(CapitalRuntimeState.RUN_HALTED, reason)
            return self.state

        # ── RUN_READY → stale check ───────────────────────────────────────────
        if current == CapitalRuntimeState.RUN_READY and snapshot.is_stale:
            self.transition(CapitalRuntimeState.RUN_STALE, "snapshot_stale")
            if bus:
                bus.emit(CapitalEvent(
                    event_type=CapitalEventType.CAPITAL_STALE,
                    trigger="snapshot_stale",
                    snapshot=snapshot,
                ))
        return self.state

    def request_recovery(self) -> bool:
        """Attempt to transition ``RUN_HALTED → RUN_REFRESHING`` for recovery."""
        return self.transition(CapitalRuntimeState.RUN_REFRESHING, "recovery_requested")


# ---------------------------------------------------------------------------
# Refresh coordinator — the single writer
# ---------------------------------------------------------------------------


class CapitalRefreshCoordinator:
    """
    The **single writer** for :class:`~capital_authority.CapitalAuthority`.

    All balance fetches, snapshot computations, and authority publishes run
    through this class via :meth:`execute_refresh`.  No other module may call
    ``CapitalAuthority.publish_snapshot()``.

    The five pipeline stages are explicit and sequential::

        STAGE 1 – KRAKEN_FETCH      fetch per-broker balances + timestamps
        STAGE 2 – NORMALIZE         aggregate broker scalars / apply fallbacks
        STAGE 3 – VALUATE           derive real / usable / risk capital
        STAGE 4 – CONFIDENCE        compute CapitalConfidence
        STAGE 5 – PUBLISH           atomic authority.publish_snapshot()

    A per-instance ``_in_flight`` guard prevents concurrent executions.
    """

    WRITER_ID: str = WRITER_ID

    def __init__(
        self,
        event_bus: CapitalEventBus,
        bootstrap_fsm: CapitalBootstrapStateMachine,
        runtime_fsm: CapitalRuntimeStateMachine,
    ) -> None:
        self._bus = event_bus
        self._boot = bootstrap_fsm
        self._runtime = runtime_fsm
        self._lock = threading.Lock()
        self._in_flight = False

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def execute_refresh(
        self,
        broker_map: Dict[str, Any],
        trigger: str = "coordinator",
        open_exposure_usd: float = 0.0,
    ) -> Optional[CapitalSnapshot]:
        """
        Run the five-stage pipeline and return the accepted snapshot.

        Parameters
        ----------
        broker_map:
            ``{broker_id: broker_instance}`` for every connected broker.
        trigger:
            Human-readable label emitted on every pipeline event.
        open_exposure_usd:
            Sum of all current open-position notional values in USD.

        Returns
        -------
        CapitalSnapshot or None
            The atomically published snapshot, or ``None`` if the publish was
            rejected or an unrecoverable exception occurred.
        """
        with self._lock:
            if self._in_flight:
                logger.debug(
                    "[Coordinator] refresh already in-flight — duplicate %s skipped",
                    trigger,
                )
                return None
            self._in_flight = True
        try:
            return self._pipeline(
                broker_map=broker_map,
                trigger=trigger,
                open_exposure_usd=open_exposure_usd,
            )
        except Exception as exc:
            logger.error("[Coordinator] pipeline exception (%s): %s", trigger, exc)
            self._bus.emit(CapitalEvent(
                event_type=CapitalEventType.SNAPSHOT_REJECTED,
                trigger=trigger,
                metadata={"error": str(exc)},
            ))
            return None
        finally:
            with self._lock:
                self._in_flight = False

    # ------------------------------------------------------------------
    # Five-stage deterministic pipeline (private)
    # ------------------------------------------------------------------

    def _pipeline(
        self,
        broker_map: Dict[str, Any],
        trigger: str,
        open_exposure_usd: float,
    ) -> Optional[CapitalSnapshot]:

        self._bus.emit(CapitalEvent(
            event_type=CapitalEventType.REFRESH_STARTED,
            trigger=trigger,
        ))
        self._boot.transition(CapitalBootstrapState.REFRESH_IN_FLIGHT, trigger)

        # Late import avoids circular dependencies at module load time.
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            try:
                from capital_authority import get_capital_authority  # type: ignore[no-redef]
            except ImportError:
                logger.error("[Coordinator] cannot import capital_authority — aborting")
                return None

        authority = get_capital_authority()

        # =================================================================
        # STAGE 1: KRAKEN_FETCH
        # Fetch balances from every connected broker.  Record Kraken-specific
        # diagnostics (fetch timestamp, pricing coverage, error count) for use
        # in Stage 4 confidence scoring.
        # =================================================================
        raw_balances: Dict[str, float] = {}   # broker_id → fetched scalar
        kraken_fetch_ts: Optional[float] = None
        kraken_response_age_s: float = FRESHNESS_TTL_S   # default = maximally stale
        assets_priced_success_pct: float = 1.0
        api_error_count: int = 0

        for broker_id, broker in broker_map.items():
            if broker is None:
                continue
            broker_key = str(broker_id)
            is_kraken = broker_key.lower() == "kraken"

            # Read Kraken diagnostics BEFORE the fetch so they reflect the
            # state that was current when this refresh was triggered.
            if is_kraken:
                if hasattr(broker, "get_error_count"):
                    try:
                        api_error_count = int(broker.get_error_count())
                    except Exception:
                        pass
                if hasattr(broker, "get_last_pricing_coverage"):
                    try:
                        assets_priced_success_pct = float(
                            broker.get_last_pricing_coverage()
                        )
                    except Exception:
                        pass
                if hasattr(broker, "get_balance_fetch_timestamp"):
                    try:
                        _bft = broker.get_balance_fetch_timestamp()
                        if _bft is not None:
                            kraken_response_age_s = max(
                                0.0, time.time() - float(_bft)
                            )
                    except Exception:
                        pass

            previous = float(authority.get_raw_per_broker(broker_key))
            try:
                if is_kraken:
                    kraken_fetch_ts = time.time()
                raw = broker.get_account_balance()
                if is_kraken and hasattr(broker, "get_balance_fetch_timestamp"):
                    # Use the broker's own timestamp for accuracy (it may have
                    # served a TTL-cached result rather than hitting the API).
                    _blt = broker.get_balance_fetch_timestamp()
                    if _blt is not None:
                        kraken_response_age_s = max(0.0, time.time() - float(_blt))
                    # Re-read pricing coverage from the broker post-fetch, in
                    # case the fetch updated it.
                    if hasattr(broker, "get_last_pricing_coverage"):
                        try:
                            assets_priced_success_pct = float(
                                broker.get_last_pricing_coverage()
                            )
                        except Exception:
                            pass

                if isinstance(raw, dict):
                    scalar = float(
                        raw.get("trading_balance")
                        or raw.get("total_funds")
                        or (raw.get("usd", 0.0) + raw.get("usdc", 0.0))
                        or 0.0
                    )
                elif raw is not None:
                    scalar = float(raw)
                else:
                    scalar = 0.0

                raw_balances[broker_key] = scalar if scalar > 0.0 else previous
                self._bus.emit(CapitalEvent(
                    event_type=CapitalEventType.BROKER_BALANCE_COLLECTED,
                    trigger=trigger,
                    metadata={
                        "broker": broker_key,
                        "balance": raw_balances.get(broker_key, 0.0),
                    },
                ))
            except Exception as exc:
                logger.warning(
                    "[Coordinator] stage1_fetch broker=%s error=%s — fallback to previous=%.2f",
                    broker_key, exc, previous,
                )
                if previous > 0.0:
                    raw_balances[broker_key] = previous
                self._bus.emit(CapitalEvent(
                    event_type=CapitalEventType.BROKER_BALANCE_COLLECTED,
                    trigger=trigger,
                    metadata={
                        "broker": broker_key,
                        "balance": previous,
                        "error": str(exc),
                    },
                ))

        # =================================================================
        # STAGE 2: NORMALIZE
        # Drop zero-balance entries; keep only brokers with a confirmed value.
        # The authority's last_updated age is used for snapshot_age_s (reflects
        # how stale the PREVIOUS snapshot was when this refresh was triggered).
        # =================================================================
        new_balances: Dict[str, float] = {
            k: v for k, v in raw_balances.items() if v > 0.0
        }
        now = datetime.now(timezone.utc)
        prior_age_s = (
            (now - authority.last_updated).total_seconds()
            if authority.last_updated is not None
            else float("inf")
        )

        # =================================================================
        # STAGE 3: VALUATE
        # Derive real / usable / risk capital from normalised broker totals.
        # =================================================================
        reserve_pct = authority.reserve_pct
        expected = authority.expected_brokers
        # In opportunistic mode only 1 broker is required for freshness; in
        # normal mode all expected_brokers must be present.
        broker_threshold = 1 if authority.opportunistic else max(1, expected)
        real = sum(new_balances.values())
        usable = real * (1.0 - reserve_pct)
        risk = max(0.0, usable - max(0.0, float(open_exposure_usd)))

        # =================================================================
        # STAGE 4: CONFIDENCE
        # Weight three orthogonal signals into a single quality score.
        # =================================================================
        confidence = CapitalConfidence.compute(
            kraken_response_age_s=kraken_response_age_s,
            assets_priced_success_pct=assets_priced_success_pct,
            api_error_count=api_error_count,
        )

        is_fresh = (
            len(new_balances) >= broker_threshold
            and prior_age_s <= FRESHNESS_TTL_S
            and real > 0.0
        )

        snapshot = CapitalSnapshot(
            real_capital=real,
            usable_capital=usable,
            risk_capital=risk,
            open_exposure_usd=max(0.0, float(open_exposure_usd)),
            reserve_pct=reserve_pct,
            broker_balances=dict(new_balances),
            broker_count=len(new_balances),
            expected_brokers=expected,
            computed_at=now,
            snapshot_age_s=prior_age_s,
            kraken_response_age_s=kraken_response_age_s,
            assets_priced_success_pct=float(assets_priced_success_pct),
            api_error_count=int(api_error_count),
            confidence=confidence,
            is_fresh=is_fresh,
            is_stale=not is_fresh,
        )

        self._bus.emit(CapitalEvent(
            event_type=CapitalEventType.SNAPSHOT_COMPUTED,
            trigger=trigger,
            snapshot=snapshot,
        ))
        self._boot.transition(CapitalBootstrapState.SNAPSHOT_EVALUATING, trigger)

        # =================================================================
        # STAGE 5: PUBLISH
        # Single atomic write to CapitalAuthority.  Rejected if writer_id
        # does not match the authorised constant.
        # =================================================================
        accepted = authority.publish_snapshot(snapshot, writer_id=self.WRITER_ID)

        if not accepted:
            self._bus.emit(CapitalEvent(
                event_type=CapitalEventType.SNAPSHOT_REJECTED,
                trigger=trigger,
                snapshot=snapshot,
            ))
            return None

        self._bus.emit(CapitalEvent(
            event_type=CapitalEventType.SNAPSHOT_PUBLISHED,
            trigger=trigger,
            snapshot=snapshot,
        ))

        # ── Drive bootstrap FSM to terminal state ─────────────────────────────
        if snapshot.real_capital > 0.0 and confidence.band in (
            CapitalConfidenceBand.HIGH, CapitalConfidenceBand.MEDIUM
        ):
            self._boot.transition(CapitalBootstrapState.READY, "capital_ready")
            self._bus.emit(CapitalEvent(
                event_type=CapitalEventType.CAPITAL_READY,
                trigger=trigger,
                snapshot=snapshot,
            ))
        elif snapshot.real_capital > 0.0:
            self._boot.transition(CapitalBootstrapState.DEGRADED, "confidence_low")
            self._bus.emit(CapitalEvent(
                event_type=CapitalEventType.CAPITAL_DEGRADED,
                trigger=trigger,
                snapshot=snapshot,
            ))
        else:
            self._boot.transition(CapitalBootstrapState.FAILED, "capital_zero")

        # ── Drive runtime FSM based on the published snapshot ─────────────────
        # Force the FSM into RUN_REFRESHING so on_snapshot_received can
        # complete the cycle.  RUN_READY and RUN_STALE allow this transition
        # directly.  RUN_REFRESHING is a no-op (already in target state).
        #
        # Capital/state mismatch guard: if the FSM is in RUN_HALTED *and* the
        # freshly-published snapshot shows positive capital at acceptable
        # confidence, auto-call request_recovery() so the coordinator pipeline
        # can advance the state.  Without this, the pipeline would silently
        # discard every subsequent healthy snapshot and trading would remain
        # blocked indefinitely even after capital is confirmed healthy.
        if self._runtime.state == CapitalRuntimeState.RUN_HALTED:
            if (
                snapshot.real_capital > 0.0
                and confidence.band in (
                    CapitalConfidenceBand.HIGH,
                    CapitalConfidenceBand.MEDIUM,
                )
            ):
                logger.info(
                    "[Coordinator] RUN_HALTED + healthy snapshot → auto-recovering "
                    "via request_recovery() (real=$%.2f  confidence=%s)",
                    snapshot.real_capital,
                    confidence.band.value,
                )
                self._runtime.request_recovery()
            else:
                logger.warning(
                    "[Coordinator] RUN_HALTED but snapshot not healthy enough to "
                    "auto-recover (real=$%.2f  confidence=%s) — remaining halted",
                    snapshot.real_capital,
                    confidence.band.value,
                )
        self._runtime.transition(CapitalRuntimeState.RUN_REFRESHING, "coordinator_publish")
        self._runtime.on_snapshot_received(snapshot, self._bus)

        logger.info(
            "[Coordinator] published  real=$%.2f  confidence=%.3f(%s)  "
            "freshness=%.3f  pricing=%.3f  errors=%d  trigger=%s",
            snapshot.real_capital,
            confidence.confidence_score,
            confidence.band.value,
            confidence.freshness_score,
            confidence.pricing_score,
            snapshot.api_error_count,
            trigger,
        )
        return snapshot


# ---------------------------------------------------------------------------
# Per-broker balance-payload bootstrap FSM
# ---------------------------------------------------------------------------


class BrokerPayloadState(str, Enum):
    """
    Per-broker balance-payload bootstrap lifecycle.

    Every broker that is registered with the MABM starts in ``REGISTERED``
    and is driven forward by :meth:`BrokerPayloadFSM.probe_and_advance`.

    Terminal states
    ---------------
    ``PAYLOAD_READY``
        The broker has a confirmed ``_last_known_balance`` value (even 0.0 is
        a valid payload — it means the account exists but is unfunded).
        Only brokers in this state are eligible to contribute capital to the
        ``CapitalAuthority`` during the bootstrap phase.

    ``EXHAUSTED``
        :meth:`probe_and_advance` was called ``max_probe_attempts`` times
        without success.  The broker is permanently excluded from capital
        calculations until :meth:`reset` is called (e.g. on reconnect).

    This design makes the ``bootstrap_missing_balance_payload`` deadlock
    impossible: instead of silently skipping a broker and hoping a payload
    appears later, every registered broker is *actively probed* up to a
    bounded number of times, after which it is explicitly exhausted.
    """

    REGISTERED    = "REGISTERED"     # in _platform_brokers; payload not yet confirmed
    PROBING       = "PROBING"        # get_account_balance() call in progress
    PAYLOAD_READY = "PAYLOAD_READY"  # _last_known_balance is set; eligible for capital
    EXHAUSTED     = "EXHAUSTED"      # max probe attempts exceeded; excluded from capital


class BrokerPayloadFSM:
    """
    Strict per-broker state machine that **guarantees convergence** to
    ``PAYLOAD_READY`` or ``EXHAUSTED``.

    Convergence guarantee
    ---------------------
    :meth:`probe_and_advance` is the **only** path that advances a broker
    past ``REGISTERED`` during bootstrap.  Every call either:

    * **succeeds** → ``PAYLOAD_READY``  (broker contributes capital)
    * **fails**    → ``REGISTERED`` (retry allowed) or ``EXHAUSTED`` (terminal)

    ``EXHAUSTED`` is reached after exactly *max_probe_attempts* consecutive
    failures, so the machine **never loops forever**.  A broker can recover
    from ``EXHAUSTED`` only via an explicit :meth:`reset` call (e.g. issued
    by the reconnect path), which restores ``REGISTERED`` and clears the
    attempt counter.

    Fast-path shortcut
    ------------------
    If ``connect()`` successfully seeds ``_last_known_balance`` before the
    bootstrap polling loop starts, call :meth:`mark_payload_ready` to skip
    probing entirely.

    Thread-safety
    -------------
    All public methods are protected by ``self._lock``.
    :meth:`probe_and_advance` releases the lock *during* the blocking
    ``get_account_balance()`` call so the rest of the system stays responsive.
    Only one probe can be in flight at a time (a concurrent call returns
    ``False`` immediately without incrementing the attempt counter).

    Valid transitions
    -----------------
    ::

        REGISTERED → PROBING          (probe_and_advance, attempt < max)
        REGISTERED → PAYLOAD_READY    (mark_payload_ready shortcut)
        PROBING    → PAYLOAD_READY    (probe succeeded)
        PROBING    → REGISTERED       (probe failed, retries remain)
        PROBING    → EXHAUSTED        (probe failed, no retries remain)
        PAYLOAD_READY → REGISTERED    (reset — reconnect cycle)
        EXHAUSTED     → REGISTERED    (reset — explicit retry)
    """

    #: Default maximum consecutive probe failures before ``EXHAUSTED``.
    #: Override via ``NIJA_BALANCE_PROBE_MAX_ATTEMPTS`` environment variable.
    DEFAULT_MAX_PROBE_ATTEMPTS: int = 5

    _VALID_TRANSITIONS: Dict[BrokerPayloadState, List[BrokerPayloadState]] = {
        BrokerPayloadState.REGISTERED: [
            BrokerPayloadState.PROBING,
            BrokerPayloadState.PAYLOAD_READY,
        ],
        BrokerPayloadState.PROBING: [
            BrokerPayloadState.PAYLOAD_READY,
            BrokerPayloadState.REGISTERED,
            BrokerPayloadState.EXHAUSTED,
        ],
        BrokerPayloadState.PAYLOAD_READY: [BrokerPayloadState.REGISTERED],
        BrokerPayloadState.EXHAUSTED:     [BrokerPayloadState.REGISTERED],
    }

    def __init__(
        self,
        broker_id: str,
        max_probe_attempts: Optional[int] = None,
    ) -> None:
        self.broker_id = broker_id
        self._max_probe_attempts: int = (
            max_probe_attempts
            if max_probe_attempts is not None
            else int(
                os.getenv(
                    "NIJA_BALANCE_PROBE_MAX_ATTEMPTS",
                    str(self.DEFAULT_MAX_PROBE_ATTEMPTS),
                )
            )
        )
        self._state: BrokerPayloadState = BrokerPayloadState.REGISTERED
        self._probe_attempts: int = 0
        self._lock = threading.Lock()
        self._log = logging.getLogger(f"nija.capital_bootstrap.{broker_id}")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> BrokerPayloadState:
        with self._lock:
            return self._state

    @property
    def probe_attempts(self) -> int:
        with self._lock:
            return self._probe_attempts

    @property
    def max_probe_attempts(self) -> int:
        return self._max_probe_attempts

    @property
    def is_payload_ready(self) -> bool:
        """``True`` only when ``PAYLOAD_READY`` — the sole eligibility gate."""
        return self.state == BrokerPayloadState.PAYLOAD_READY

    @property
    def is_exhausted(self) -> bool:
        """``True`` only when ``EXHAUSTED`` — broker excluded from capital."""
        return self.state == BrokerPayloadState.EXHAUSTED

    @property
    def can_probe(self) -> bool:
        """``True`` if a probe attempt is allowed right now."""
        with self._lock:
            return (
                self._state == BrokerPayloadState.REGISTERED
                and self._probe_attempts < self._max_probe_attempts
            )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _transition(self, new_state: BrokerPayloadState) -> bool:
        """Internal guarded transition. Must be called **with** ``self._lock``."""
        allowed = self._VALID_TRANSITIONS.get(self._state, [])
        if new_state not in allowed:
            self._log.warning(
                "[BrokerPayloadFSM] broker=%s invalid transition %s → %s (ignored)",
                self.broker_id,
                self._state.value,
                new_state.value,
            )
            return False
        self._log.debug(
            "[BrokerPayloadFSM] broker=%s %s → %s",
            self.broker_id,
            self._state.value,
            new_state.value,
        )
        self._state = new_state
        return True

    def mark_payload_ready(self) -> None:
        """
        Externally advance to ``PAYLOAD_READY`` without probing.

        Call this when ``connect()`` already seeded ``_last_known_balance``
        so the FSM immediately reflects the current reality and the bootstrap
        polling loop can skip the probing round-trip.

        No-op when already ``PAYLOAD_READY`` or ``EXHAUSTED``.
        """
        with self._lock:
            if self._state == BrokerPayloadState.EXHAUSTED:
                return
            if self._state == BrokerPayloadState.PAYLOAD_READY:
                return
            self._transition(BrokerPayloadState.PAYLOAD_READY)

    def reset(self) -> None:
        """
        Reset to ``REGISTERED`` for a fresh reconnect cycle.

        Clears the probe counter so the broker gets a full
        *max_probe_attempts* budget on the next connect attempt.
        Allowed from any state (idempotent from ``REGISTERED``).
        """
        with self._lock:
            self._probe_attempts = 0
            self._state = BrokerPayloadState.REGISTERED
        self._log.info(
            "[BrokerPayloadFSM] broker=%s reset to REGISTERED (probe counter cleared)",
            self.broker_id,
        )

    def probe_and_advance(self, broker: Any) -> bool:
        """
        Call ``broker.get_account_balance()`` and advance the FSM.

        This is the **only** way to advance a broker past ``REGISTERED``
        during bootstrap.  It is safe to call multiple times:

        * Once ``PAYLOAD_READY`` it is an immediate no-op returning ``True``.
        * Once ``EXHAUSTED`` it is an immediate no-op returning ``False``.
        * If a probe is already in-flight (``PROBING``) the call returns
          ``False`` without incrementing the attempt counter.

        Parameters
        ----------
        broker:
            Live broker instance.  Must expose ``get_account_balance()``.

        Returns
        -------
        bool
            ``True`` if the broker is now in ``PAYLOAD_READY``.
        """
        with self._lock:
            if self._state == BrokerPayloadState.PAYLOAD_READY:
                return True
            if self._state == BrokerPayloadState.EXHAUSTED:
                return False
            if self._state == BrokerPayloadState.PROBING:
                # Another caller is already probing — skip without counting.
                return False
            if self._probe_attempts >= self._max_probe_attempts:
                self._transition(BrokerPayloadState.EXHAUSTED)
                self._log.error(
                    "[BrokerPayloadFSM] broker=%s EXHAUSTED after %d probe "
                    "attempts — excluded from capital until reconnect",
                    self.broker_id,
                    self._probe_attempts,
                )
                return False
            self._transition(BrokerPayloadState.PROBING)
            self._probe_attempts += 1
            attempt = self._probe_attempts

        # ── Balance fetch (outside the lock so the system stays responsive) ──
        self._log.info(
            "[BrokerPayloadFSM] broker=%s probing balance (attempt %d/%d)",
            self.broker_id,
            attempt,
            self._max_probe_attempts,
        )
        try:
            broker.get_account_balance()
        except Exception as exc:
            self._log.warning(
                "[BrokerPayloadFSM] broker=%s probe attempt %d/%d raised: %s",
                self.broker_id,
                attempt,
                self._max_probe_attempts,
                exc,
            )

        # ── Evaluate result (re-acquire lock) ─────────────────────────────────
        lkb = getattr(broker, "_last_known_balance", None)
        with self._lock:
            if lkb is not None:
                self._transition(BrokerPayloadState.PAYLOAD_READY)
                self._log.info(
                    "[BrokerPayloadFSM] broker=%s PAYLOAD_READY "
                    "(balance=%.2f) after %d probe attempt(s)",
                    self.broker_id,
                    float(lkb),
                    attempt,
                )
                return True
            # Payload not yet present.
            if self._probe_attempts >= self._max_probe_attempts:
                self._transition(BrokerPayloadState.EXHAUSTED)
                self._log.error(
                    "[BrokerPayloadFSM] broker=%s EXHAUSTED — "
                    "no payload after %d probes",
                    self.broker_id,
                    self._probe_attempts,
                )
                return False
            # Retries remain — return to REGISTERED so the next call can probe.
            self._transition(BrokerPayloadState.REGISTERED)
            self._log.info(
                "[BrokerPayloadFSM] broker=%s probe %d/%d failed — "
                "will retry on next bootstrap iteration",
                self.broker_id,
                self._probe_attempts,
                self._max_probe_attempts,
            )
            return False
