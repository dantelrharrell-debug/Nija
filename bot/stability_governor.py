"""
Stability-controlled adaptive trading governor.

This module provides a single stability authority layer that sits above
execution gating and returns a unified verdict:
{allow, size_multiplier, throttle, halt_state, reason}.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.stability_governor")

DATA_DIR = Path(__file__).parent.parent / "data"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class StabilityState(Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    CONTAINMENT = "CONTAINMENT"
    HALTED = "HALTED"
    RECOVERING = "RECOVERING"


@dataclass(frozen=True)
class AdaptiveControls:
    risk_budget: float
    trade_frequency_cap: float
    confidence_threshold: float
    max_concurrent_exposure: int


@dataclass(frozen=True)
class StabilityAuthorityDecision:
    allow: bool
    size_multiplier: float
    throttle: float
    halt_state: str
    reason: str
    stability_state: str
    stress_score: float
    collapsed_risk_score: float
    controls: AdaptiveControls
    active_invariants: tuple[str, ...] = field(default_factory=tuple)
    predictors: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class StabilityGovernor:
    """Adaptive stability authority with anti-collapse guarantees."""

    AUDIT_FILE = DATA_DIR / "stability_governor_audit.jsonl"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = StabilityState.NORMAL
        self._pending_state = StabilityState.NORMAL
        self._pending_count = 0
        self._cooldown_remaining = 0
        self._last_stress_score = 0.0
        self._last_size_multiplier = 1.0
        self._last_decision: Optional[StabilityAuthorityDecision] = None
        self._last_predictors: Dict[str, float] = {}

        self._mode_persistence = max(1, int(os.getenv("NIJA_STABILITY_MODE_PERSISTENCE", "2")))
        self._mode_cooldown = max(0, int(os.getenv("NIJA_STABILITY_MODE_COOLDOWN", "2")))

        self._degraded_threshold = _clamp(_safe_float(os.getenv("NIJA_STABILITY_DEGRADED_THRESHOLD", "0.45")), 0.05, 0.95)
        self._containment_threshold = _clamp(_safe_float(os.getenv("NIJA_STABILITY_CONTAINMENT_THRESHOLD", "0.70")), 0.10, 0.99)
        self._recover_threshold = _clamp(_safe_float(os.getenv("NIJA_STABILITY_RECOVER_THRESHOLD", "0.25")), 0.01, 0.80)
        self._hard_drawdown_pct = _clamp(_safe_float(os.getenv("NIJA_STABILITY_HARD_DRAWDOWN_PCT", "5.0")), 0.5, 50.0)

        self._controls = AdaptiveControls(
            risk_budget=_clamp(_safe_float(os.getenv("NIJA_STABILITY_BASE_RISK_BUDGET", "1.0")), 0.05, 1.0),
            trade_frequency_cap=_clamp(_safe_float(os.getenv("NIJA_STABILITY_BASE_TRADE_FREQUENCY_CAP", "1.0")), 0.05, 1.0),
            confidence_threshold=_clamp(_safe_float(os.getenv("NIJA_STABILITY_BASE_CONFIDENCE_THRESHOLD", "0.50")), 0.05, 0.99),
            max_concurrent_exposure=max(1, int(os.getenv("NIJA_STABILITY_BASE_MAX_CONCURRENT_EXPOSURE", "12"))),
        )
        self._max_budget_step = _clamp(_safe_float(os.getenv("NIJA_STABILITY_MAX_BUDGET_STEP", "0.12")), 0.01, 0.5)
        self._max_freq_step = _clamp(_safe_float(os.getenv("NIJA_STABILITY_MAX_FREQ_STEP", "0.12")), 0.01, 0.5)
        self._max_conf_step = _clamp(_safe_float(os.getenv("NIJA_STABILITY_MAX_CONF_STEP", "0.08")), 0.01, 0.5)
        self._max_exposure_step = max(1, int(os.getenv("NIJA_STABILITY_MAX_EXPOSURE_STEP", "1")))

        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def evaluate(
        self,
        *,
        runtime_snapshot: Optional[Any],
        state_live_active: bool,
        lease_valid: bool,
        lease_generation_current: bool,
        heartbeat_fresh: bool,
        heartbeat_stage_sufficient: bool,
        broker_health_ok: bool,
        dispatch_enabled: bool,
        circuit_breaker_closed: bool,
    ) -> StabilityAuthorityDecision:
        with self._lock:
            predictors = self._collect_predictors()
            self._last_predictors = dict(predictors)

            authority_ambiguous = runtime_snapshot is None or str(getattr(runtime_snapshot, "coordinator_state", "")).strip() in {
                "",
                "UNKNOWN",
                "UNAVAILABLE",
            }
            hard_drawdown = predictors.get("daily_loss_pct", 0.0) >= self._hard_drawdown_pct
            hard_collapse = bool(
                predictors.get("global_halt_active", 0.0) > 0.5
                or predictors.get("execution_breaker_tripped", 0.0) > 0.5
                or hard_drawdown
            )

            stress_score = self._compute_stress_score(predictors)
            collapsed_risk_score = _clamp(max(stress_score, 0.95 if hard_collapse else 0.0), 0.0, 1.0)

            target_state = self._target_state(stress_score, hard_collapse)
            prev_state = self._state
            state = self._apply_state_hysteresis(target_state)
            self._controls = self._update_controls(stress_score, state)
            size_multiplier = self._size_multiplier_for_state(state, stress_score, self._controls)

            monotonic_size_ok = True
            if stress_score > (self._last_stress_score + 1e-9):
                if size_multiplier > (self._last_size_multiplier + 1e-9):
                    monotonic_size_ok = False
                    size_multiplier = self._last_size_multiplier

            staged_recovery_ok = not (prev_state == StabilityState.HALTED and state == StabilityState.NORMAL)
            if not staged_recovery_ok:
                state = StabilityState.RECOVERING
                size_multiplier = min(size_multiplier, 0.35)

            if state == StabilityState.RECOVERING:
                size_multiplier = min(size_multiplier, 0.35)
            if state == StabilityState.HALTED:
                size_multiplier = 0.0

            throttle = _clamp(self._controls.trade_frequency_cap, 0.05, 1.0)
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
            allow = bool(base_allow and not hard_collapse and not authority_ambiguous and state != StabilityState.HALTED)
            if state == StabilityState.RECOVERING:
                allow = bool(allow and collapsed_risk_score <= 0.65)

            authority_fail_closed_ok = (not authority_ambiguous) or (not allow)
            no_new_entries_hard_collapse_ok = (not hard_collapse) or (not allow)

            invariant_flags = {
                "no_new_entries_under_hard_collapse": no_new_entries_hard_collapse_ok,
                "monotonic_size_under_worsening_stress": monotonic_size_ok,
                "staged_recovery_required": staged_recovery_ok,
                "authority_ambiguity_fail_closed": authority_fail_closed_ok,
            }
            active_invariants = tuple(name for name, ok in invariant_flags.items() if not ok)

            reason = self._reason_for_decision(
                allow=allow,
                state=state,
                hard_collapse=hard_collapse,
                authority_ambiguous=authority_ambiguous,
                invariants=active_invariants,
                predictors=predictors,
            )
            halt_state = "HALTED" if state == StabilityState.HALTED else state.value

            decision = StabilityAuthorityDecision(
                allow=allow,
                size_multiplier=round(_clamp(size_multiplier, 0.0, 1.0), 4),
                throttle=round(throttle, 4),
                halt_state=halt_state,
                reason=reason,
                stability_state=state.value,
                stress_score=round(stress_score, 4),
                collapsed_risk_score=round(collapsed_risk_score, 4),
                controls=self._controls,
                active_invariants=active_invariants,
                predictors={k: round(v, 4) for k, v in predictors.items()},
            )
            self._last_stress_score = stress_score
            self._last_size_multiplier = float(decision.size_multiplier)
            self._last_decision = decision
            self._audit(decision)
            return decision

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            decision = self._last_decision
            controls = self._controls
            return {
                "stability_state": self._state.value,
                "decision": {
                    "allow": bool(decision.allow) if decision else False,
                    "size_multiplier": float(decision.size_multiplier) if decision else 1.0,
                    "throttle": float(decision.throttle) if decision else 1.0,
                    "halt_state": str(decision.halt_state) if decision else self._state.value,
                    "reason": str(decision.reason) if decision else "uninitialized",
                    "stress_score": float(decision.stress_score) if decision else 0.0,
                    "collapsed_risk_score": float(decision.collapsed_risk_score) if decision else 0.0,
                    "active_invariants": list(decision.active_invariants) if decision else [],
                },
                "controls": asdict(controls),
                "predictors": dict(self._last_predictors),
            }

    def _target_state(self, stress_score: float, hard_collapse: bool) -> StabilityState:
        if hard_collapse:
            return StabilityState.HALTED
        if self._state == StabilityState.HALTED:
            return StabilityState.RECOVERING if stress_score <= self._containment_threshold else StabilityState.HALTED
        if self._state == StabilityState.RECOVERING:
            if stress_score >= self._containment_threshold:
                return StabilityState.CONTAINMENT
            if stress_score <= self._recover_threshold:
                return StabilityState.NORMAL
            return StabilityState.RECOVERING
        if stress_score >= self._containment_threshold:
            return StabilityState.CONTAINMENT
        if stress_score >= self._degraded_threshold:
            return StabilityState.DEGRADED
        return StabilityState.NORMAL

    def _apply_state_hysteresis(self, target_state: StabilityState) -> StabilityState:
        if target_state == StabilityState.HALTED and self._state != StabilityState.HALTED:
            self._state = StabilityState.HALTED
            self._pending_state = target_state
            self._pending_count = 0
            self._cooldown_remaining = self._mode_cooldown
            return self._state
        if self._state == StabilityState.HALTED and target_state == StabilityState.RECOVERING:
            self._state = StabilityState.RECOVERING
            self._pending_state = target_state
            self._pending_count = 0
            self._cooldown_remaining = self._mode_cooldown
            return self._state

        if target_state == self._state:
            self._pending_state = target_state
            self._pending_count = 0
            if self._cooldown_remaining > 0:
                self._cooldown_remaining -= 1
            return self._state

        if self._cooldown_remaining > 0 and self._state != StabilityState.HALTED:
            self._cooldown_remaining -= 1
            return self._state

        if target_state != self._pending_state:
            self._pending_state = target_state
            self._pending_count = 1
            return self._state

        self._pending_count += 1
        if self._pending_count < self._mode_persistence:
            return self._state

        self._state = target_state
        self._pending_state = target_state
        self._pending_count = 0
        self._cooldown_remaining = self._mode_cooldown
        return self._state

    def _update_controls(self, stress_score: float, state: StabilityState) -> AdaptiveControls:
        target_budget = _clamp(1.0 - (0.80 * stress_score), 0.05, 1.0)
        target_freq = _clamp(1.0 - (0.75 * stress_score), 0.05, 1.0)
        target_conf = _clamp(0.50 + (0.45 * stress_score), 0.05, 0.99)
        target_exposure = max(1, int(round(self._controls.max_concurrent_exposure * (1.0 - 0.60 * stress_score))))

        if state == StabilityState.CONTAINMENT:
            target_budget = min(target_budget, 0.35)
            target_freq = min(target_freq, 0.45)
            target_conf = max(target_conf, 0.80)
            target_exposure = min(target_exposure, 3)
        elif state == StabilityState.HALTED:
            target_budget = 0.05
            target_freq = 0.05
            target_conf = 0.95
            target_exposure = 1
        elif state == StabilityState.RECOVERING:
            target_budget = min(target_budget, 0.40)
            target_freq = min(target_freq, 0.50)
            target_conf = max(target_conf, 0.75)
            target_exposure = min(target_exposure, 4)

        budget = self._rate_limit(self._controls.risk_budget, target_budget, self._max_budget_step)
        freq = self._rate_limit(self._controls.trade_frequency_cap, target_freq, self._max_freq_step)
        conf = self._rate_limit(self._controls.confidence_threshold, target_conf, self._max_conf_step)
        exposure = self._rate_limit_int(
            self._controls.max_concurrent_exposure,
            target_exposure,
            self._max_exposure_step,
        )
        return AdaptiveControls(
            risk_budget=round(_clamp(budget, 0.05, 1.0), 4),
            trade_frequency_cap=round(_clamp(freq, 0.05, 1.0), 4),
            confidence_threshold=round(_clamp(conf, 0.05, 0.99), 4),
            max_concurrent_exposure=max(1, exposure),
        )

    def _rate_limit(self, current: float, target: float, step: float) -> float:
        if target > current:
            return min(target, current + step)
        return max(target, current - step)

    def _rate_limit_int(self, current: int, target: int, step: int) -> int:
        if target > current:
            return min(target, current + step)
        return max(target, current - step)

    def _size_multiplier_for_state(
        self,
        state: StabilityState,
        stress_score: float,
        controls: AdaptiveControls,
    ) -> float:
        if state == StabilityState.HALTED:
            return 0.0
        if state == StabilityState.CONTAINMENT:
            return min(0.25, controls.risk_budget)
        if state == StabilityState.RECOVERING:
            return min(0.35, controls.risk_budget)
        if state == StabilityState.DEGRADED:
            return min(0.75, controls.risk_budget, 1.0 - 0.35 * stress_score)
        return min(1.0, controls.risk_budget)

    def _compute_stress_score(self, predictors: Dict[str, float]) -> float:
        stress = 0.0
        stress += 0.28 * _clamp(predictors.get("loss_cluster_pressure", 0.0), 0.0, 1.0)
        stress += 0.16 * _clamp(predictors.get("rejection_burst", 0.0), 0.0, 1.0)
        stress += 0.12 * _clamp(predictors.get("partial_fill_pressure", 0.0), 0.0, 1.0)
        stress += 0.15 * _clamp(predictors.get("liquidity_stress", 0.0), 0.0, 1.0)
        stress += 0.14 * _clamp(predictors.get("volatility_shock", 0.0), 0.0, 1.0)
        stress += 0.15 * _clamp(predictors.get("regime_confidence_decay", 0.0), 0.0, 1.0)
        return _clamp(stress, 0.0, 1.0)

    def _collect_predictors(self) -> Dict[str, float]:
        predictors = {
            "loss_cluster_pressure": 0.0,
            "rejection_burst": 0.0,
            "partial_fill_pressure": 0.0,
            "liquidity_stress": _clamp(_safe_float(os.getenv("NIJA_LIQUIDITY_STRESS_SCORE", "0.0")), 0.0, 1.0),
            "volatility_shock": 0.0,
            "regime_confidence_decay": _clamp(_safe_float(os.getenv("NIJA_REGIME_CONFIDENCE_DECAY", "0.0")), 0.0, 1.0),
            "global_halt_active": 0.0,
            "execution_breaker_tripped": 0.0,
            "daily_loss_pct": 0.0,
        }
        try:
            try:
                from bot.global_risk_governor import get_global_risk_governor
            except ImportError:
                from global_risk_governor import get_global_risk_governor  # type: ignore[import]
            risk_status = get_global_risk_governor().get_status()
            predictors["global_halt_active"] = 1.0 if risk_status.get("halt_active") else 0.0
            consecutive_losses = max(0.0, _safe_float(risk_status.get("consecutive_losses", 0.0)))
            max_consecutive = max(1.0, _safe_float((risk_status.get("config") or {}).get("max_consecutive_losses", 5.0)))
            predictors["loss_cluster_pressure"] = _clamp(consecutive_losses / max_consecutive, 0.0, 1.0)
            daily_pnl = _safe_float(risk_status.get("daily_pnl_usd", 0.0))
            cap = max(1.0, _safe_float(os.getenv("NIJA_STABILITY_DAILY_LOSS_REFERENCE_USD", "1000.0")))
            predictors["daily_loss_pct"] = _clamp(max(0.0, -daily_pnl) / cap * 100.0, 0.0, 100.0)
            vol_ratio = max(0.0, _safe_float(risk_status.get("volatility_ratio", 1.0)))
            predictors["volatility_shock"] = _clamp((vol_ratio - 1.0) / 2.0, 0.0, 1.0)
        except Exception:
            pass
        try:
            try:
                from bot.exploration_governor import get_exploration_governor
            except ImportError:
                from exploration_governor import get_exploration_governor  # type: ignore[import]
            state_vector = get_exploration_governor().get_state_vector(regime="unknown")
            predictors["loss_cluster_pressure"] = max(
                predictors["loss_cluster_pressure"],
                _clamp(_safe_float(getattr(state_vector, "cluster_pressure", 0.0)), 0.0, 1.0),
            )
            predictors["liquidity_stress"] = max(
                predictors["liquidity_stress"],
                _clamp(_safe_float(getattr(state_vector, "drawdown_pressure", 0.0)), 0.0, 1.0),
            )
            regime_confidence = _clamp(_safe_float(getattr(state_vector, "regime_confidence", 0.0)), 0.0, 1.0)
            predictors["regime_confidence_decay"] = max(
                predictors["regime_confidence_decay"],
                _clamp(1.0 - regime_confidence, 0.0, 1.0),
            )
        except Exception:
            pass
        try:
            try:
                from bot.trading_state_machine import get_execution_anomaly_snapshot
            except ImportError:
                from trading_state_machine import get_execution_anomaly_snapshot  # type: ignore[import]
            anomaly = get_execution_anomaly_snapshot()
            counts = anomaly.get("counts") or {}
            thresholds = anomaly.get("thresholds") or {}
            reject_count = max(0.0, _safe_float(counts.get("rejected_orders", 0.0)))
            reject_threshold = max(1.0, _safe_float(thresholds.get("rejected_orders", 5.0)))
            partial_count = max(0.0, _safe_float(counts.get("partial_fills", 0.0)))
            partial_threshold = max(1.0, _safe_float(thresholds.get("partial_fills", 3.0)))
            predictors["rejection_burst"] = _clamp(reject_count / reject_threshold, 0.0, 1.0)
            predictors["partial_fill_pressure"] = _clamp(partial_count / partial_threshold, 0.0, 1.0)
            predictors["execution_breaker_tripped"] = 1.0 if anomaly.get("tripped") else 0.0
        except Exception:
            pass
        return predictors

    def _reason_for_decision(
        self,
        *,
        allow: bool,
        state: StabilityState,
        hard_collapse: bool,
        authority_ambiguous: bool,
        invariants: tuple[str, ...],
        predictors: Dict[str, float],
    ) -> str:
        if authority_ambiguous:
            return "authority_ambiguity_fail_closed"
        if hard_collapse:
            return "hard_collapse_containment"
        if invariants:
            return f"invariant_violation:{','.join(invariants)}"
        if not allow:
            if state == StabilityState.HALTED:
                return "state_halted"
            return "stability_guard_denied"
        if state == StabilityState.RECOVERING:
            return "staged_recovery_active"
        if state == StabilityState.CONTAINMENT:
            return "containment_controls_active"
        if state == StabilityState.DEGRADED:
            return "degraded_controls_active"
        risk = _safe_float(predictors.get("loss_cluster_pressure", 0.0))
        return "normal" if risk < 0.40 else "normal_with_elevated_risk"

    def _audit(self, decision: StabilityAuthorityDecision) -> None:
        payload = {
            "timestamp": decision.timestamp,
            "allow": decision.allow,
            "size_multiplier": decision.size_multiplier,
            "throttle": decision.throttle,
            "halt_state": decision.halt_state,
            "reason": decision.reason,
            "stability_state": decision.stability_state,
            "stress_score": decision.stress_score,
            "collapsed_risk_score": decision.collapsed_risk_score,
            "active_invariants": list(decision.active_invariants),
            "controls": asdict(decision.controls),
            "predictors": decision.predictors,
        }
        try:
            with self.AUDIT_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, separators=(",", ":"), sort_keys=True))
                fh.write("\n")
        except Exception:
            logger.debug("stability audit write failed", exc_info=True)
        logger.info(
            "StabilityAuthority decision=%s",
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )


_STABILITY_GOVERNOR: Optional[StabilityGovernor] = None
_STABILITY_LOCK = threading.Lock()


def get_stability_governor() -> StabilityGovernor:
    global _STABILITY_GOVERNOR
    if _STABILITY_GOVERNOR is not None:
        return _STABILITY_GOVERNOR
    with _STABILITY_LOCK:
        if _STABILITY_GOVERNOR is None:
            _STABILITY_GOVERNOR = StabilityGovernor()
    return _STABILITY_GOVERNOR
