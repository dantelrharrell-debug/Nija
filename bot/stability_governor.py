"""
Stability Governor
==================

Lyapunov-style policy layer + deterministic finite-state governor for
execution stability in the NIJA trading bot.

Architecture
------------
Layer 1 – Lyapunov potential (V_t)
    A scalar risk score ∈ [0, 1] computed from weighted system signals.
    V_t = 0 → fully stable; V_t → 1 → maximally unstable.
    Component weights are tuned to match the severity ordering defined in
    the NIJA authority/safety model.

Layer 2 – Finite-state governor (FSM)
    Deterministic mode transitions with hysteresis and cooldowns:

        BOOT → OBSERVE → STABLE
        STABLE → GUARDED  (V_t rising persistently)
        GUARDED → HALT    (hard invariants violated or V_t rises further)
        GUARDED/HALT → RECOVERING  (V_t improving, authority healthy)
        RECOVERING → STABLE        (quorum window of improvement)

    All transitions require the state to have been held for a minimum
    cooldown to prevent rapid oscillation ("chattering").

Layer 3 – Control outputs
    - ``mode``  — governor FSM state (BOOT/OBSERVE/STABLE/GUARDED/HALT/RECOVERING)
    - ``exploration_damping`` — float ∈ [0, 1] multiplier for live near-miss admission
    - ``is_halted()`` — True when mode is HALT

Integration (thin hooks — all feature-flagged)
----------------------------------------------
- ``can_execute()`` in execution_authority_context checks ``is_halted()``
  when ``NIJA_STABILITY_GOVERNOR_HALT_ENABLED=true``.
- ``_record_execution_anomaly()`` in trading_state_machine calls
  ``notify_anomaly()`` to increment anomaly counters.
- ``get_detailed_status()`` in health_check includes governor snapshot.
- ``NijaApexStrategy`` exploration paths use ``exploration_damping()``
  when ``NIJA_STABILITY_GOVERNOR_ENABLED=true``.

Feature flags
-------------
NIJA_STABILITY_GOVERNOR_ENABLED     — master enable (default: false)
NIJA_STABILITY_GOVERNOR_HALT_ENABLED — engage HALT dispatch block (default: false)
NIJA_SG_GUARDED_V_THRESHOLD         — V_t threshold for GUARDED (default: 0.25)
NIJA_SG_HALT_V_THRESHOLD            — V_t threshold for HALT (default: 0.60)
NIJA_SG_RISING_TO_GUARDED           — consecutive V_t rises → GUARDED (default: 3)
NIJA_SG_RISING_TO_HALT              — consecutive V_t rises in GUARDED → HALT (default: 2)
NIJA_SG_RECOVERY_QUORUM             — consecutive improvements to exit RECOVERING (default: 5)
NIJA_SG_STABLE_COOLDOWN             — cycles before GUARDED→STABLE downgrade (default: 4)
NIJA_SG_ANOMALY_DECAY_S             — anomaly pressure half-life in seconds (default: 600)
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger("nija.stability_governor")


# ---------------------------------------------------------------------------
# Public enumerations
# ---------------------------------------------------------------------------

class GovernorMode(str, Enum):
    """Stability governor FSM states."""

    BOOT = "BOOT"
    OBSERVE = "OBSERVE"
    STABLE = "STABLE"
    GUARDED = "GUARDED"
    HALT = "HALT"
    RECOVERING = "RECOVERING"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StabilityVector:
    """Compact runtime stability signal snapshot.

    All boolean signals are fail-closed: unavailability is treated as a
    failure (False).  Float pressure signals are clamped to [0, 1].
    """

    runtime_authority_ok: bool
    """True when coordinator runtime_authority_state is EXECUTING."""

    execution_permitted: bool
    """True when coordinator.execution_permitted is True."""

    global_epoch_current: bool
    """True when activation_epoch == global_epoch (no stale intent)."""

    lease_valid: bool
    """True when distributed writer fencing token is valid."""

    heartbeat_fresh: bool
    """True when heartbeat marker is fresh and stage-sufficient."""

    nonce_ready: bool
    """True when nonce gate is healthy."""

    anomaly_pressure: float
    """Normalized anomaly frequency [0, 1] from internal counter."""

    cluster_pressure: float
    """Maximum regime cluster pressure from ExplorationGovernor [0, 1]."""

    dispatch_health: bool
    """True when broker health gate is ok."""

    kill_switch_active: bool
    """True when coordinator kill switch is engaged."""


@dataclass(frozen=True)
class StabilityPotential:
    """Lyapunov potential computed from a StabilityVector."""

    value: float
    """V_t ∈ [0, 1]: 0 = fully stable, 1 = maximally unstable."""

    delta: float
    """V_t − V_{t-1}: positive means worsening, negative means recovering."""

    breakdown: Dict[str, float]
    """Per-component contributions to V_t."""


@dataclass(frozen=True)
class GovernorSnapshot:
    """Immutable snapshot of governor state for observability."""

    mode: GovernorMode
    v_potential: float
    v_delta: float
    rising_count: int
    recovery_window: int
    stable_count: int
    reason: str
    transition_count: int
    last_transition_ts: float
    exploration_damping: float
    anomaly_counts: Dict[str, int]
    enabled: bool


# ---------------------------------------------------------------------------
# Main governor class
# ---------------------------------------------------------------------------

class StabilityGovernor:
    """Lyapunov-style policy layer + deterministic FSM governor.

    This class is the single integration point for stability control.
    All external callers should use the process-wide singleton returned by
    :func:`get_stability_governor`.

    Thread-safety: all public methods acquire ``self._lock``.
    """

    # Lyapunov potential component weights (must sum to ~1.0).
    _WEIGHTS: Dict[str, float] = {
        "authority_regression": 0.30,   # runtime authority not EXECUTING
        "lease_failure": 0.20,          # writer fencing token invalid
        "heartbeat_failure": 0.18,      # heartbeat stale / insufficient stage
        "nonce_failure": 0.12,          # nonce gate unhealthy
        "anomaly_pressure": 0.10,       # normalized anomaly rate
        "cluster_pressure": 0.05,       # exploration cluster pressure
        "dispatch_health_failure": 0.05,# broker health gate failure
    }

    def __init__(self) -> None:
        self._lock = threading.RLock()

        # ── feature flags (read once at construction, hot-reloaded on evaluate) ─
        self._enabled: bool = self._read_enabled()

        # ── FSM state ────────────────────────────────────────────────────────
        self._mode: GovernorMode = GovernorMode.BOOT
        self._transition_count: int = 0
        self._last_transition_ts: float = time.monotonic()

        # ── Lyapunov history ─────────────────────────────────────────────────
        self._prev_v: float = 0.0
        self._rising_count: int = 0   # consecutive V_t increases (delta > threshold)
        self._recovery_window: int = 0  # consecutive cycles V_t ≤ de-escalation threshold in RECOVERING
        self._stable_count: int = 0   # consecutive cycles V_t low in GUARDED
        self._high_v_count: int = 0   # consecutive cycles V_t > current escalation threshold
        self._low_v_count: int = 0    # consecutive cycles V_t ≤ de-escalation threshold

        # ── Anomaly counters (decaying) ───────────────────────────────────────
        self._anomaly_events: Deque[float] = deque(maxlen=200)
        self._anomaly_kind_counts: Dict[str, int] = {}

        # ── Observe boot-up counter ───────────────────────────────────────────
        self._observe_cycles: int = 0

        logger.info(
            "🛡️  StabilityGovernor initialised | enabled=%s halt_enabled=%s",
            self._enabled,
            self._read_halt_enabled(),
        )

    # -------------------------------------------------------------------------
    # Public interface
    # -------------------------------------------------------------------------

    def step(self) -> GovernorSnapshot:
        """Gather live signals, update V_t, advance FSM, return snapshot.

        This is the core FSM tick: idempotent except for state advancement.
        Called periodically (once per trading cycle) or from ``evaluate()``.
        It does NOT block execution paths — see ``is_halted()``.
        """
        with self._lock:
            self._enabled = self._read_enabled()

            if not self._enabled and self._mode == GovernorMode.BOOT:
                self._mode = GovernorMode.OBSERVE
                self._record_transition("observe_mode_disabled")

            vector = self._gather_vector_locked()
            potential = self._compute_potential_locked(vector)
            self._advance_fsm_locked(potential, vector)

            return self._build_snapshot_locked(potential)

    def notify_anomaly(self, kind: str, detail: str = "") -> None:
        """Record an execution anomaly event.

        Called by ``_record_execution_anomaly`` in trading_state_machine.
        Each call increments the rolling anomaly counter which feeds V_t.
        """
        if not self._read_enabled():
            return
        with self._lock:
            now = time.monotonic()
            self._anomaly_events.append(now)
            kind = str(kind or "unknown").strip()
            self._anomaly_kind_counts[kind] = self._anomaly_kind_counts.get(kind, 0) + 1
        logger.debug("StabilityGovernor anomaly recorded kind=%s detail=%s", kind, detail)

    def is_halted(self) -> bool:
        """Return True when the governor is in HALT mode.

        Used by ``can_execute()`` in execution_authority_context when
        ``NIJA_STABILITY_GOVERNOR_HALT_ENABLED=true``.  This method must
        never raise — it defaults to False on any error so as not to
        accidentally block dispatch when the governor is unavailable.
        """
        try:
            with self._lock:
                return self._mode == GovernorMode.HALT
        except Exception:
            return False

    def get_snapshot(self) -> GovernorSnapshot:
        """Return the current governor snapshot without re-evaluating."""
        with self._lock:
            try:
                vector = self._gather_vector_locked()
                potential = self._compute_potential_locked(vector)
            except Exception:
                potential = StabilityPotential(value=0.0, delta=0.0, breakdown={})
            return self._build_snapshot_locked(potential)

    def exploration_damping(self) -> float:
        """Return a [0, 1] multiplier for live near-miss admission.

        - STABLE / OBSERVE / BOOT: 1.0 (no damping)
        - GUARDED:                 0.5 (50 % damping)
        - RECOVERING:              0.75 (25 % damping)
        - HALT:                    0.0 (block all live exploration)
        """
        with self._lock:
            return self._damping_for_mode_locked(self._mode)

    def reset_for_testing(self) -> None:
        """Reset all internal state; for use in unit tests only."""
        with self._lock:
            self._mode = GovernorMode.BOOT
            self._transition_count = 0
            self._last_transition_ts = time.monotonic()
            self._prev_v = 0.0
            self._rising_count = 0
            self._recovery_window = 0
            self._stable_count = 0
            self._high_v_count = 0    # consecutive cycles V_t > escalation threshold
            self._low_v_count = 0     # consecutive cycles V_t ≤ de-escalation threshold
            self._anomaly_events.clear()
            self._anomaly_kind_counts.clear()
            self._observe_cycles = 0

    # -------------------------------------------------------------------------
    # Internal helpers — must be called under self._lock
    # -------------------------------------------------------------------------

    def _gather_vector_locked(self) -> StabilityVector:
        """Pull live signals from existing authority systems.

        All reads are wrapped in try/except — failures default to the
        most conservative (fail-closed) value.
        """
        runtime_authority_ok = False
        execution_permitted = False
        global_epoch_current = False
        lease_valid = False
        heartbeat_fresh = False
        nonce_ready = False
        dispatch_health = False
        kill_switch_active = False
        cluster_pressure = 0.0

        # ── Coordinator snapshot ──────────────────────────────────────────────
        try:
            try:
                from bot.startup_coordinator import get_startup_coordinator, RuntimeAuthorityState
            except ImportError:
                from startup_coordinator import get_startup_coordinator, RuntimeAuthorityState  # type: ignore
            coord = get_startup_coordinator()
            snap = coord.build_snapshot(
                trading_state=os.getenv("NIJA_RUNTIME_TRADING_STATE", ""),
                activation_intent=(
                    os.getenv("LIVE_CAPITAL_VERIFIED", "").lower() in ("true", "1", "yes")
                    or os.getenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "").lower() in ("true", "1", "yes")
                ),
            )
            runtime_authority_ok = snap.runtime_authority_state == RuntimeAuthorityState.EXECUTING.value
            execution_permitted = bool(snap.execution_permitted)
            global_epoch_current = snap.activation_epoch == snap.global_epoch
            nonce_ready = bool(snap.nonce_ready)
            dispatch_health = bool(snap.dispatch_health_ready)
            kill_switch_active = bool(snap.kill_switch_active)
        except Exception as _coord_exc:
            logger.debug("StabilityGovernor: coordinator snapshot unavailable: %s", _coord_exc)

        # ── Writer lease / heartbeat ──────────────────────────────────────────
        try:
            try:
                from bot.execution_authority_context import assert_distributed_writer_authority
            except ImportError:
                from execution_authority_context import assert_distributed_writer_authority  # type: ignore
            assert_distributed_writer_authority()
            lease_valid = True
        except Exception:
            lease_valid = False

        try:
            try:
                from bot.trading_state_machine import (
                    _heartbeat_marker_path,
                    _required_heartbeat_stage,
                    heartbeat_marker_is_fresh,
                    heartbeat_marker_stage_is_sufficient,
                )
            except ImportError:
                from trading_state_machine import (  # type: ignore
                    _heartbeat_marker_path,
                    _required_heartbeat_stage,
                    heartbeat_marker_is_fresh,
                    heartbeat_marker_stage_is_sufficient,
                )
            _path = _heartbeat_marker_path()
            _fresh = heartbeat_marker_is_fresh(_path)
            if _fresh:
                heartbeat_fresh = heartbeat_marker_stage_is_sufficient(_path, _required_heartbeat_stage())
            else:
                heartbeat_fresh = False
        except Exception:
            heartbeat_fresh = False

        # ── ExplorationGovernor cluster pressure ──────────────────────────────
        try:
            try:
                from bot.exploration_governor import get_exploration_governor as _get_eg
            except ImportError:
                from exploration_governor import get_exploration_governor as _get_eg  # type: ignore
            _sv = _get_eg().get_state_vector()
            cluster_pressure = float(_sv.cluster_pressure)
        except Exception:
            cluster_pressure = 0.0

        # ── Anomaly pressure (decaying rolling window) ────────────────────────
        anomaly_pressure = self._compute_anomaly_pressure_locked()

        return StabilityVector(
            runtime_authority_ok=runtime_authority_ok,
            execution_permitted=execution_permitted,
            global_epoch_current=global_epoch_current,
            lease_valid=lease_valid,
            heartbeat_fresh=heartbeat_fresh,
            nonce_ready=nonce_ready,
            anomaly_pressure=anomaly_pressure,
            cluster_pressure=max(0.0, min(1.0, cluster_pressure)),
            dispatch_health=dispatch_health,
            kill_switch_active=kill_switch_active,
        )

    def _compute_anomaly_pressure_locked(self) -> float:
        """Compute normalized anomaly pressure using exponential decay."""
        decay_half_life_s = float(os.getenv("NIJA_SG_ANOMALY_DECAY_S", "600") or 600.0)
        if decay_half_life_s <= 0:
            return 0.0
        now = time.monotonic()
        weighted_sum = 0.0
        for ts in self._anomaly_events:
            elapsed = max(0.0, now - ts)
            weighted_sum += math.exp(-math.log(2.0) * elapsed / decay_half_life_s)
        # Normalise: 10 events at time-zero → pressure = 1.0
        return min(1.0, weighted_sum / 10.0)

    def _compute_potential_locked(self, vector: StabilityVector) -> StabilityPotential:
        """Compute scalar Lyapunov potential V_t from vector components."""
        breakdown: Dict[str, float] = {}

        # Authority regression: worst if both runtime_authority and execution_permitted fail
        authority_risk = 0.0
        if not vector.runtime_authority_ok:
            authority_risk += 0.60
        if not vector.execution_permitted:
            authority_risk += 0.30
        if not vector.global_epoch_current:
            authority_risk += 0.10
        authority_risk = min(1.0, authority_risk)
        breakdown["authority_regression"] = self._WEIGHTS["authority_regression"] * authority_risk

        # Lease failure
        lease_risk = 0.0 if vector.lease_valid else 1.0
        breakdown["lease_failure"] = self._WEIGHTS["lease_failure"] * lease_risk

        # Heartbeat failure
        hb_risk = 0.0 if vector.heartbeat_fresh else 1.0
        breakdown["heartbeat_failure"] = self._WEIGHTS["heartbeat_failure"] * hb_risk

        # Nonce failure
        nonce_risk = 0.0 if vector.nonce_ready else 1.0
        breakdown["nonce_failure"] = self._WEIGHTS["nonce_failure"] * nonce_risk

        # Anomaly pressure (already ∈ [0,1])
        breakdown["anomaly_pressure"] = self._WEIGHTS["anomaly_pressure"] * vector.anomaly_pressure

        # Cluster pressure (already ∈ [0,1])
        breakdown["cluster_pressure"] = self._WEIGHTS["cluster_pressure"] * vector.cluster_pressure

        # Dispatch health failure
        dispatch_risk = 0.0 if vector.dispatch_health else 1.0
        breakdown["dispatch_health_failure"] = self._WEIGHTS["dispatch_health_failure"] * dispatch_risk

        v_t = sum(breakdown.values())
        v_t = max(0.0, min(1.0, v_t))
        delta = v_t - self._prev_v
        self._prev_v = v_t

        return StabilityPotential(value=v_t, delta=delta, breakdown=breakdown)

    def _advance_fsm_locked(self, potential: StabilityPotential, vector: StabilityVector) -> None:
        """Advance the governor FSM according to V_t, threshold crossings, and kill switch.

        Design principles:
        - ``kill_switch_active`` is the only *immediate* HALT invariant.  All other
          signals (lease, heartbeat, nonce) feed into V_t and escalate through the
          normal STABLE→GUARDED→HALT path, avoiding false-positive hard halts.
        - GUARDED→HALT uses ``_high_v_count`` (consecutive cycles V_t > halt_threshold)
          rather than delta direction, so a persistently high but flat V_t still escalates.
        - RECOVERING→STABLE uses ``_low_v_count`` (consecutive cycles V_t ≤ guarded_threshold)
          for the same reason: a flat low V_t should complete recovery.
        """
        guarded_threshold = float(os.getenv("NIJA_SG_GUARDED_V_THRESHOLD", "0.25") or 0.25)
        halt_threshold = float(os.getenv("NIJA_SG_HALT_V_THRESHOLD", "0.60") or 0.60)
        rising_to_guarded = int(os.getenv("NIJA_SG_RISING_TO_GUARDED", "3") or 3)
        rising_to_halt = int(os.getenv("NIJA_SG_RISING_TO_HALT", "2") or 2)
        recovery_quorum = int(os.getenv("NIJA_SG_RECOVERY_QUORUM", "5") or 5)
        stable_cooldown = int(os.getenv("NIJA_SG_STABLE_COOLDOWN", "4") or 4)

        # Only kill_switch is a true external hard-halt.  Lease/nonce/heartbeat
        # failures are captured in V_t and drive the escalation path naturally.
        hard_halt = bool(vector.kill_switch_active)

        # ── Threshold-crossing counters ───────────────────────────────────────
        # _rising_count: consecutive cycles V_t > guarded_threshold (STABLE→GUARDED)
        # _high_v_count: consecutive cycles V_t > halt_threshold (GUARDED→HALT)
        # _stable_count: consecutive cycles V_t ≤ guarded_threshold (GUARDED→STABLE)
        if potential.value > guarded_threshold:
            self._rising_count += 1
        else:
            self._rising_count = 0

        if potential.value > halt_threshold:
            self._high_v_count += 1
        else:
            self._high_v_count = 0

        if potential.value <= guarded_threshold:
            self._stable_count += 1
            self._low_v_count += 1
        else:
            self._stable_count = 0
            self._low_v_count = 0

        # Recovery window: cycles while in RECOVERING with V_t ≤ guarded_threshold
        if self._mode == GovernorMode.RECOVERING and potential.value <= guarded_threshold:
            self._recovery_window += 1
        elif self._mode != GovernorMode.RECOVERING:
            self._recovery_window = 0

        mode = self._mode

        # ── BOOT: always advance to OBSERVE ────────────────────────────────
        if mode == GovernorMode.BOOT:
            self._transition_to_locked(GovernorMode.OBSERVE, "boot_complete")
            return

        # ── Hard-halt: kill switch overrides everything ─────────────────────
        if hard_halt and mode != GovernorMode.HALT:
            self._transition_to_locked(GovernorMode.HALT, "kill_switch_active")
            return

        # ── OBSERVE: advance to STABLE once V_t is low ─────────────────────
        if mode == GovernorMode.OBSERVE:
            self._observe_cycles += 1
            if self._observe_cycles >= 2 and potential.value <= guarded_threshold:
                self._transition_to_locked(GovernorMode.STABLE, "initial_stable")
            return

        # ── STABLE: move to GUARDED on N consecutive cycles above guarded threshold ─
        if mode == GovernorMode.STABLE:
            # _rising_count counts consecutive cycles V_t > guarded_threshold
            if self._rising_count >= rising_to_guarded:
                self._transition_to_locked(
                    GovernorMode.GUARDED,
                    f"v_above_threshold count={self._rising_count} v={potential.value:.3f}",
                )
            return

        # ── GUARDED: escalate to HALT or de-escalate ────────────────────────
        if mode == GovernorMode.GUARDED:
            # Escalate: V_t above halt threshold for N consecutive cycles
            if self._high_v_count >= rising_to_halt:
                self._transition_to_locked(
                    GovernorMode.HALT,
                    f"v_critical count={self._high_v_count} v={potential.value:.3f}",
                )
                return
            # De-escalate: V_t low for stable_cooldown consecutive cycles
            if self._stable_count >= stable_cooldown:
                self._transition_to_locked(
                    GovernorMode.STABLE,
                    f"guarded_resolved stable_count={self._stable_count}",
                )
            return

        # ── HALT: enter RECOVERING when kill switch cleared and V_t falling ─
        if mode == GovernorMode.HALT:
            if (
                not hard_halt
                and vector.runtime_authority_ok
                and potential.delta < -0.005
                and potential.value <= halt_threshold
            ):
                self._transition_to_locked(
                    GovernorMode.RECOVERING,
                    f"halt_recovery_started v={potential.value:.3f}",
                )
            return

        # ── RECOVERING: complete recovery to STABLE ─────────────────────────
        if mode == GovernorMode.RECOVERING:
            if hard_halt:
                self._transition_to_locked(GovernorMode.HALT, "hard_invariant_during_recovery")
                return
            # Regression: V_t spikes above guarded threshold
            if potential.value > guarded_threshold and potential.delta > 0.005:
                self._transition_to_locked(
                    GovernorMode.GUARDED,
                    f"recovery_regressed v={potential.value:.3f}",
                )
                return
            # Completion: sufficient low-V_t cycles accumulated
            if self._recovery_window >= recovery_quorum and potential.value <= guarded_threshold:
                self._transition_to_locked(
                    GovernorMode.STABLE,
                    f"recovery_complete window={self._recovery_window}",
                )
            return

    def _transition_to_locked(self, new_mode: GovernorMode, reason: str) -> None:
        """Record a mode transition."""
        old_mode = self._mode
        if new_mode == old_mode:
            return
        self._mode = new_mode
        self._transition_count += 1
        self._last_transition_ts = time.monotonic()
        # Reset hysteresis counters on transition
        self._rising_count = 0
        self._recovery_window = 0
        self._stable_count = 0
        self._high_v_count = 0
        self._low_v_count = 0
        self._observe_cycles = 0
        logger.warning(
            "🛡️  StabilityGovernor transition %s → %s reason=%s",
            old_mode.value,
            new_mode.value,
            reason,
        )

    def _record_transition(self, reason: str) -> None:
        """Record a non-mode-changing transition event (e.g. OBSERVE initial)."""
        self._transition_count += 1
        self._last_transition_ts = time.monotonic()

    def _build_snapshot_locked(self, potential: StabilityPotential) -> GovernorSnapshot:
        """Build a frozen snapshot from current internal state."""
        return GovernorSnapshot(
            mode=self._mode,
            v_potential=round(potential.value, 6),
            v_delta=round(potential.delta, 6),
            rising_count=self._rising_count,
            recovery_window=self._recovery_window,
            stable_count=self._stable_count,
            reason=self._mode.value,
            transition_count=self._transition_count,
            last_transition_ts=self._last_transition_ts,
            exploration_damping=self._damping_for_mode_locked(self._mode),
            anomaly_counts=dict(self._anomaly_kind_counts),
            enabled=self._enabled,
        )

    @staticmethod
    def _damping_for_mode_locked(mode: GovernorMode) -> float:
        if mode == GovernorMode.HALT:
            return 0.0
        if mode == GovernorMode.GUARDED:
            return 0.5
        if mode == GovernorMode.RECOVERING:
            return 0.75
        return 1.0

    @staticmethod
    def _read_enabled() -> bool:
        return os.getenv("NIJA_STABILITY_GOVERNOR_ENABLED", "").strip().lower() in (
            "1", "true", "yes", "enabled", "on"
        )

    @staticmethod
    def _read_halt_enabled() -> bool:
        return os.getenv("NIJA_STABILITY_GOVERNOR_HALT_ENABLED", "").strip().lower() in (
            "1", "true", "yes", "enabled", "on"
        )



    def evaluate(
        self,
        *,
        runtime_snapshot: "Optional[Any]" = None,
        state_live_active: bool = False,
        lease_valid: bool = False,
        lease_generation_current: bool = False,
        heartbeat_fresh: bool = False,
        heartbeat_stage_sufficient: bool = False,
        broker_health_ok: bool = False,
        dispatch_enabled: bool = False,
        circuit_breaker_closed: bool = False,
    ) -> "StabilityAuthorityDecision":
        """Evaluate stability and return a unified authority decision.

        This method satisfies the API contract required by
        :func:`execution_authority_context._evaluate_stability_authority`.

        It runs the Lyapunov FSM evaluation (gathering live signals from the
        environment) and then maps the FSM snapshot to a
        :class:`StabilityAuthorityDecision` that callers can query via
        ``.allow``, ``.size_multiplier``, ``.throttle``, ``.halt_state``,
        ``.stress_score``, ``.collapsed_risk_score``, and ``.reason``.

        Parameters
        ----------
        runtime_snapshot:
            Coordinator authority snapshot.  Used to check for authority
            ambiguity (``coordinator_state`` in {empty, UNKNOWN, UNAVAILABLE}).
        state_live_active, lease_valid, ..., circuit_breaker_closed:
            Pre-checked gate conditions from the caller.  All must be True for
            the base ``allow`` flag to be set.
        """
        snap = self.get_snapshot()

        # Collect predictors for meta-data passthrough (best-effort, fail-open)
        predictors: Dict[str, float] = {}
        try:
            with self._lock:
                preds = self._anomaly_kind_counts
                predictors = {k: float(v) for k, v in preds.items()}
        except Exception:
            pass

        # Authority ambiguity check — fail closed when coordinator state unknown
        authority_ambiguous = runtime_snapshot is None or str(
            getattr(runtime_snapshot, "coordinator_state", "")
        ).strip() in {"", "UNKNOWN", "UNAVAILABLE"}
        if authority_ambiguous:
            return StabilityAuthorityDecision(
                allow=False,
                size_multiplier=0.0,
                throttle=0.0,
                halt_state="UNKNOWN",
                reason="authority_ambiguity_fail_closed",
                stability_state=_fsm_mode_to_stability_state(snap.mode).value,
                stress_score=round(float(snap.v_potential), 4),
                collapsed_risk_score=1.0,
                controls=AdaptiveControls(
                    risk_budget=0.0,
                    trade_frequency_cap=0.0,
                    confidence_threshold=0.99,
                    max_concurrent_exposure=1,
                ),
                active_invariants=("authority_ambiguity_fail_closed",),
                predictors=predictors,
            )

        base_allow = bool(
            state_live_active
            and lease_valid
            and lease_generation_current
            and heartbeat_fresh
            and heartbeat_stage_sufficient
            and broker_health_ok
            and dispatch_enabled
            and circuit_breaker_closed
        )
        return _governor_to_authority_decision(snap, base_allow=base_allow, predictors=predictors)

    # -- SEAK compatibility (is_halted/exploration_damping already provided above)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_governor_instance: Optional[StabilityGovernor] = None
_governor_lock = threading.Lock()


def get_stability_governor(reset: bool = False) -> StabilityGovernor:
    """Return the process-wide StabilityGovernor singleton.

    Parameters
    ----------
    reset:
        When True, replaces the existing instance.  For testing only.
    """
    global _governor_instance
    with _governor_lock:
        if reset or _governor_instance is None:
            _governor_instance = StabilityGovernor()
    return _governor_instance
# ---------------------------------------------------------------------------
# Compatibility layer — provides the evaluate() API consumed by
# execution_authority_context._evaluate_stability_authority()
# ---------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path

_DATA_DIR = _Path(__file__).parent.parent / "data"


def _clamp(value: float, lo: float, hi: float) -> float:  # noqa: F811
    return max(lo, min(hi, value))


def _safe_float(value: Any, default: float = 0.0) -> float:  # noqa: F811
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class StabilityState(Enum):
    """Compatibility state enum matching the older adaptive-governor API."""

    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    CONTAINMENT = "CONTAINMENT"
    HALTED = "HALTED"
    RECOVERING = "RECOVERING"


@dataclass(frozen=True)
class AdaptiveControls:
    """Rate-limited adaptive trading controls (compatibility type)."""

    risk_budget: float
    trade_frequency_cap: float
    confidence_threshold: float
    max_concurrent_exposure: int


@dataclass(frozen=True)
class StabilityAuthorityDecision:
    """Unified stability verdict returned by :meth:`StabilityGovernor.evaluate`."""

    allow: bool
    size_multiplier: float
    throttle: float
    halt_state: str
    reason: str
    stability_state: str
    stress_score: float
    collapsed_risk_score: float
    controls: AdaptiveControls
    active_invariants: tuple = field(default_factory=tuple)
    predictors: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


def _fsm_mode_to_stability_state(mode: GovernorMode) -> StabilityState:
    """Map our FSM mode to the compatibility StabilityState enum."""
    _map = {
        GovernorMode.BOOT: StabilityState.NORMAL,
        GovernorMode.OBSERVE: StabilityState.NORMAL,
        GovernorMode.STABLE: StabilityState.NORMAL,
        GovernorMode.GUARDED: StabilityState.DEGRADED,
        GovernorMode.HALT: StabilityState.HALTED,
        GovernorMode.RECOVERING: StabilityState.RECOVERING,
    }
    return _map.get(mode, StabilityState.NORMAL)


def _governor_to_authority_decision(
    snap: GovernorSnapshot,
    *,
    base_allow: bool,
    predictors: Dict[str, float],
) -> StabilityAuthorityDecision:
    """Convert a :class:`GovernorSnapshot` to a :class:`StabilityAuthorityDecision`."""
    stability_state = _fsm_mode_to_stability_state(snap.mode)
    halted = snap.mode == GovernorMode.HALT
    stress = float(snap.v_potential)
    allow = bool(base_allow and not halted)
    size_mult: float
    throttle: float
    if halted:
        size_mult = 0.0
        throttle = 0.05
    elif snap.mode == GovernorMode.GUARDED:
        size_mult = _clamp(snap.exploration_damping, 0.05, 0.75)
        throttle = 0.5
    elif snap.mode == GovernorMode.RECOVERING:
        size_mult = _clamp(snap.exploration_damping, 0.10, 0.35)
        throttle = 0.6
    else:
        size_mult = 1.0
        throttle = 1.0
    controls = AdaptiveControls(
        risk_budget=round(size_mult, 4),
        trade_frequency_cap=round(throttle, 4),
        confidence_threshold=0.50 if snap.mode == GovernorMode.STABLE else 0.75,
        max_concurrent_exposure=12 if snap.mode == GovernorMode.STABLE else 4,
    )
    reason: str
    if halted:
        reason = "state_halted"
    elif snap.mode == GovernorMode.GUARDED:
        reason = f"guarded_mode(v={snap.v_potential:.3f})"
    elif snap.mode == GovernorMode.RECOVERING:
        reason = "staged_recovery_active"
    else:
        reason = "normal"
    return StabilityAuthorityDecision(
        allow=allow,
        size_multiplier=round(_clamp(size_mult, 0.0, 1.0), 4),
        throttle=round(_clamp(throttle, 0.05, 1.0), 4),
        halt_state=stability_state.value,
        reason=reason,
        stability_state=stability_state.value,
        stress_score=round(stress, 4),
        collapsed_risk_score=round(_clamp(max(stress, 0.95 if halted else 0.0), 0.0, 1.0), 4),
        controls=controls,
        active_invariants=(),
        predictors=dict(predictors),
    )
