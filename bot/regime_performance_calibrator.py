"""Shadow-mode regime-aware performance calibration for NIJA.

This module observes fully closed trades and produces bounded, statistically
shrunk recommendations. It never places orders. Live execution may consume
downside-only controls only after both operator gates are enabled and the
bucket meets the minimum sample requirement; otherwise controls are neutral.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("nija.regime_calibration")

REGIME_ALIASES: Dict[str, str] = {
    "strong_trend": "trending",
    "weak_trend": "trending",
    "expansion": "trending",
    "uptrend": "trending",
    "downtrend": "trending",
    "trending": "trending",
    "ranging": "ranging",
    "range": "ranging",
    "sideways": "ranging",
    "consolidation": "ranging",
    "mean_reversion": "ranging",
    "volatile": "volatile",
    "high_vol": "volatile",
    "high_volatility": "volatile",
    "volatility_explosion": "volatile",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def normalize_regime(regime: object) -> str:
    """Map the runtime's regime variants into stable calibration families."""
    raw = getattr(regime, "value", regime)
    key = str(raw or "default").strip().lower()
    return REGIME_ALIASES.get(key, key if key else "default")


@dataclass(frozen=True)
class CalibrationObservation:
    """One immutable, fully closed trade used by the shadow calibrator."""

    timestamp: str
    symbol: str
    regime: str
    strategy: str
    broker: str
    side: str
    net_return: float
    gross_return: float
    execution_cost_return: float
    mfe_return: float
    mae_return: float
    exit_reason: str
    confidence: Optional[float] = None

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "CalibrationObservation":
        confidence_raw = raw.get("confidence")
        confidence = None if confidence_raw is None else _finite(confidence_raw)
        return cls(
            timestamp=str(raw.get("timestamp") or _utc_now()),
            symbol=str(raw.get("symbol") or "unknown"),
            regime=normalize_regime(raw.get("regime")),
            strategy=str(raw.get("strategy") or "unknown"),
            broker=str(raw.get("broker") or "unknown"),
            side=str(raw.get("side") or "unknown").lower(),
            net_return=_finite(raw.get("net_return")),
            gross_return=_finite(raw.get("gross_return")),
            execution_cost_return=max(0.0, _finite(raw.get("execution_cost_return"))),
            mfe_return=max(0.0, _finite(raw.get("mfe_return"))),
            mae_return=min(0.0, _finite(raw.get("mae_return"))),
            exit_reason=str(raw.get("exit_reason") or "unknown"),
            confidence=confidence,
        )


class RegimePerformanceCalibrator:
    """Persist observations and calculate conservative shadow recommendations."""

    def __init__(
        self,
        state_path: str = "data/regime_performance_calibration.json",
        window: int = 200,
        shrinkage_k: float = 20.0,
    ) -> None:
        self.state_path = Path(state_path)
        self.window = max(20, int(window))
        self.shrinkage_k = max(1.0, float(shrinkage_k))
        self._lock = threading.RLock()
        self._observations: Deque[CalibrationObservation] = deque(maxlen=self.window)

        # Strategy-selection learning is deliberately separate from risk sizing.
        # It observes by default and can only change candidate ordering when both
        # explicit operator gates are enabled.
        self.selection_mode = os.getenv(
            "NIJA_ADAPTIVE_STRATEGY_MODE", "shadow"
        ).strip().lower()
        self.selection_approved = os.getenv(
            "NIJA_ADAPTIVE_STRATEGY_APPROVED", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        self.selection_min_samples = max(
            5, int(os.getenv("NIJA_ADAPTIVE_STRATEGY_MIN_SAMPLES", "20"))
        )
        self.selection_max_adjustment = max(
            0.0,
            min(
                0.25,
                _finite(
                    os.getenv("NIJA_ADAPTIVE_STRATEGY_MAX_ADJUSTMENT", "0.12"),
                    0.12,
                ),
            ),
        )
        self.selection_confluence_step = max(
            0.0,
            min(
                0.05,
                _finite(
                    os.getenv("NIJA_ADAPTIVE_STRATEGY_CONFLUENCE_STEP", "0.02"),
                    0.02,
                ),
            ),
        )
        self.selection_max_confluence = max(
            0.0,
            min(
                0.15,
                _finite(
                    os.getenv("NIJA_ADAPTIVE_STRATEGY_MAX_CONFLUENCE", "0.06"),
                    0.06,
                ),
            ),
        )
        self.selection_freeze_penalty = max(
            0.0,
            min(
                0.50,
                _finite(
                    os.getenv("NIJA_ADAPTIVE_STRATEGY_FREEZE_PENALTY", "0.20"),
                    0.20,
                ),
            ),
        )
        self._load()

    def record_closed_trade(self, **raw: object) -> Dict[str, object]:
        """Record a full-close outcome and return its current bucket report."""
        observation = CalibrationObservation.from_dict(raw)
        with self._lock:
            self._observations.append(observation)
            self._save()
            report = self.get_recommendation(observation.regime, observation.strategy)
        logger.info(
            "REGIME_CALIBRATION_SHADOW regime=%s strategy=%s samples=%d score=%.3f "
            "size_mult=%.3f confidence_delta=%.3f eligible=%s",
            observation.regime,
            observation.strategy,
            report["sample_size"],
            report["calibration_score"],
            report["position_size_multiplier"],
            report["confidence_threshold_delta"],
            report["eligible_for_review"],
        )
        return report

    def get_recommendation(self, regime: object, strategy: str = "unknown") -> Dict[str, object]:
        """Calculate metrics and a bounded recommendation for one bucket."""
        regime_key = normalize_regime(regime)
        strategy_key = str(strategy or "unknown")
        with self._lock:
            trades = [
                item for item in self._observations
                if item.regime == regime_key and item.strategy == strategy_key
            ]
        return self._calculate(regime_key, strategy_key, trades)

    def report_all(self) -> List[Dict[str, object]]:
        """Return reports for all observed regime/strategy buckets."""
        with self._lock:
            buckets: Dict[tuple[str, str], List[CalibrationObservation]] = defaultdict(list)
            for item in self._observations:
                buckets[(item.regime, item.strategy)].append(item)
        return [self._calculate(regime, strategy, trades) for (regime, strategy), trades in sorted(buckets.items())]

    @property
    def adaptive_selection_active(self) -> bool:
        """Whether learned performance is allowed to change strategy ordering."""
        return self.selection_mode == "active" and self.selection_approved

    def score_strategy_candidate(
        self,
        *,
        strategy: str,
        regime: object,
        direction: str,
        base_score: float,
        same_direction_confirmations: int = 1,
    ) -> Dict[str, object]:
        """Score one already-confirmed strategy candidate.

        The normal signal score remains authoritative in shadow mode. When
        active, only a bounded regime+strategy performance adjustment and a
        bounded same-direction confluence bonus may alter candidate ordering.
        No execution, protection, or sizing controls are changed here.
        """
        strategy_key = str(strategy or "unknown").strip() or "unknown"
        regime_key = normalize_regime(regime)
        direction_key = str(direction or "unknown").strip().lower()
        base = max(0.0, min(1.0, _finite(base_score)))

        report = self.get_recommendation(regime_key, strategy_key)
        sample_size = int(report.get("sample_size", 0) or 0)
        reliability = max(0.0, min(1.0, _finite(report.get("reliability"))))
        eligible = (
            bool(report.get("eligible_for_review"))
            and sample_size >= self.selection_min_samples
        )
        calibration_score = max(
            -1.0, min(1.0, _finite(report.get("calibration_score")))
        )

        performance_adjustment = 0.0
        if eligible:
            performance_adjustment = max(
                -self.selection_max_adjustment,
                min(
                    self.selection_max_adjustment,
                    calibration_score * self.selection_max_adjustment,
                ),
            )

        freeze_recommended = bool(report.get("freeze_recommended"))
        if freeze_recommended:
            # A deteriorating strategy can never be promoted by the learning
            # layer. This is ranking-only; the downstream risk engine remains
            # the final execution authority.
            performance_adjustment = min(
                performance_adjustment,
                -min(
                    self.selection_freeze_penalty,
                    self.selection_max_adjustment,
                ),
            )

        confirmations = max(1, int(same_direction_confirmations or 1))
        confluence_bonus = min(
            self.selection_max_confluence,
            max(0, confirmations - 1) * self.selection_confluence_step,
        )

        adaptive_score = max(
            0.0,
            min(1.0, base + performance_adjustment + confluence_bonus),
        )
        selection_score = adaptive_score if self.adaptive_selection_active else base

        return {
            "strategy": strategy_key,
            "regime": regime_key,
            "direction": direction_key,
            "base_score": round(base, 6),
            "adaptive_score": round(adaptive_score, 6),
            "selection_score": round(selection_score, 6),
            "performance_adjustment": round(performance_adjustment, 6),
            "confluence_bonus": round(confluence_bonus, 6),
            "sample_size": sample_size,
            "reliability": round(reliability, 6),
            "expectancy": round(_finite(report.get("expectancy")), 8),
            "win_rate": round(
                max(0.0, min(1.0, _finite(report.get("win_rate")))),
                6,
            ),
            "profit_factor": round(
                max(0.0, _finite(report.get("profit_factor"))),
                6,
            ),
            "freeze_recommended": freeze_recommended,
            "eligible_for_learning": eligible,
            "active": self.adaptive_selection_active,
        }

    def rank_strategy_candidates(
        self,
        rows: Sequence[Tuple[Any, float]],
    ) -> List[Tuple[Any, float, Dict[str, object]]]:
        """Rank confirmed candidate/base-score pairs.

        In shadow mode the returned selection score is exactly the base score,
        making this path observational only.
        """
        direction_counts: Dict[str, int] = {}
        for candidate, _ in rows:
            direction = str(
                getattr(candidate, "direction", "unknown") or "unknown"
            ).lower()
            direction_counts[direction] = direction_counts.get(direction, 0) + 1

        ranked: List[Tuple[Any, float, Dict[str, object]]] = []
        for candidate, base_score in rows:
            direction = str(
                getattr(candidate, "direction", "unknown") or "unknown"
            ).lower()
            detail = self.score_strategy_candidate(
                strategy=str(
                    getattr(candidate, "strategy", "unknown") or "unknown"
                ),
                regime=getattr(candidate, "market_regime", "default"),
                direction=direction,
                base_score=base_score,
                same_direction_confirmations=direction_counts.get(direction, 1),
            )
            ranked.append(
                (candidate, float(detail["selection_score"]), detail)
            )

        ranked.sort(key=lambda row: row[1], reverse=True)
        if ranked:
            leader = ranked[0][2]
            logger.info(
                "ADAPTIVE_STRATEGY_RANK mode=%s active=%s strategy=%s "
                "regime=%s base=%.3f adaptive=%.3f selected=%.3f "
                "samples=%d confluence=%.3f",
                self.selection_mode,
                self.adaptive_selection_active,
                leader["strategy"],
                leader["regime"],
                float(leader["base_score"]),
                float(leader["adaptive_score"]),
                float(leader["selection_score"]),
                int(leader["sample_size"]),
                float(leader["confluence_bonus"]),
            )
        return ranked

    def get_control_preview(self, regime: object, strategy: str = "APEX_V71") -> Dict[str, object]:
        """Return downside-only controls suitable for walk-forward evaluation.

        Positive recommendations never increase risk.  The first live-capable
        version may only reduce size or tighten confidence requirements.
        """
        report = self.get_recommendation(regime, strategy)
        eligible = bool(report["eligible_for_review"])
        return {
            "eligible": eligible,
            "position_size_multiplier": (
                min(1.0, float(report["position_size_multiplier"])) if eligible else 1.0
            ),
            "confidence_threshold_delta": (
                max(0.0, float(report["confidence_threshold_delta"])) if eligible else 0.0
            ),
            "freeze_recommended": bool(report["freeze_recommended"]),
            "sample_size": int(report["sample_size"]),
        }

    def get_live_controls(self, regime: object, strategy: str = "APEX_V71") -> Dict[str, object]:
        """Return fail-closed live controls after two explicit operator gates.

        Both environment flags must be true.  With either absent, neutral
        controls are returned and the execution path remains unchanged.
        """
        requested = os.getenv("NIJA_REGIME_CALIBRATION_LIVE", "false").strip().lower() == "true"
        approved = os.getenv("NIJA_REGIME_CALIBRATION_APPROVED", "false").strip().lower() == "true"
        preview = self.get_control_preview(regime, strategy)
        active = requested and approved and bool(preview["eligible"])
        return {
            **preview,
            "active": active,
            "position_size_multiplier": preview["position_size_multiplier"] if active else 1.0,
            "confidence_threshold_delta": preview["confidence_threshold_delta"] if active else 0.0,
        }

    def _calculate(
        self,
        regime: str,
        strategy: str,
        trades: Iterable[CalibrationObservation],
    ) -> Dict[str, object]:
        rows = list(trades)
        sample_size = len(rows)
        if not rows:
            return self._empty_report(regime, strategy)

        returns = [row.net_return for row in rows]
        wins = [value for value in returns if value > 0.0]
        losses = [value for value in returns if value < 0.0]
        gross_wins = sum(wins)
        gross_losses = abs(sum(losses))
        expectancy = sum(returns) / sample_size
        profit_factor = gross_wins / gross_losses if gross_losses > 0.0 else (3.0 if gross_wins > 0.0 else 0.0)
        win_rate = len(wins) / sample_size
        max_drawdown = self._max_drawdown(returns)
        avg_mfe = sum(row.mfe_return for row in rows) / sample_size
        avg_execution_cost = sum(row.execution_cost_return for row in rows) / sample_size
        positive_capture = [
            max(0.0, row.net_return) / row.mfe_return
            for row in rows if row.mfe_return > 0.0
        ]
        mfe_capture = min(1.0, sum(positive_capture) / len(positive_capture)) if positive_capture else 0.0

        reliability = sample_size / (sample_size + self.shrinkage_k)
        expectancy_component = max(-1.0, min(1.0, expectancy / 0.01))
        profit_factor_component = max(-1.0, min(1.0, (profit_factor - 1.0) / 1.5))
        win_rate_component = max(-1.0, min(1.0, (win_rate - 0.5) / 0.25))
        drawdown_component = max(0.0, min(1.0, max_drawdown / 0.05))
        execution_component = max(0.0, min(1.0, avg_execution_cost / 0.01))
        calibration_score = reliability * (
            0.30 * expectancy_component
            + 0.20 * profit_factor_component
            + 0.15 * win_rate_component
            + 0.15 * mfe_capture
            - 0.15 * drawdown_component
            - 0.05 * execution_component
        )

        adjustment_cap = self._adjustment_cap(sample_size)
        signed_adjustment = max(-adjustment_cap, min(adjustment_cap, calibration_score * adjustment_cap))
        confidence_delta = -signed_adjustment
        freeze = sample_size >= 20 and (max_drawdown >= 0.05 or expectancy <= -0.005)
        position_multiplier = 1.0 if sample_size < 20 else 1.0 + signed_adjustment
        if freeze:
            position_multiplier = min(position_multiplier, 0.75)
            confidence_delta = max(confidence_delta, 0.10)

        return {
            "regime": regime,
            "strategy": strategy,
            "sample_size": sample_size,
            "reliability": round(reliability, 6),
            "expectancy": round(expectancy, 8),
            "profit_factor": round(profit_factor, 6),
            "win_rate": round(win_rate, 6),
            "max_drawdown": round(max_drawdown, 8),
            "avg_mfe": round(avg_mfe, 8),
            "mfe_capture": round(mfe_capture, 6),
            "avg_execution_cost": round(avg_execution_cost, 8),
            "calibration_score": round(calibration_score, 6),
            "position_size_multiplier": round(position_multiplier, 6),
            "confidence_threshold_delta": round(confidence_delta, 6),
            "freeze_recommended": freeze,
            "eligible_for_review": sample_size >= 20,
            "shadow_only": True,
        }

    @staticmethod
    def _adjustment_cap(sample_size: int) -> float:
        if sample_size < 20:
            return 0.0
        if sample_size < 50:
            return 0.05
        if sample_size < 100:
            return 0.10
        return 0.15

    @staticmethod
    def _max_drawdown(returns: Iterable[float]) -> float:
        equity = 1.0
        peak = 1.0
        max_drawdown = 0.0
        for value in returns:
            equity *= max(0.0, 1.0 + value)
            peak = max(peak, equity)
            if peak > 0.0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)
        return max_drawdown

    @staticmethod
    def _empty_report(regime: str, strategy: str) -> Dict[str, object]:
        return {
            "regime": regime,
            "strategy": strategy,
            "sample_size": 0,
            "reliability": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "avg_mfe": 0.0,
            "mfe_capture": 0.0,
            "avg_execution_cost": 0.0,
            "calibration_score": 0.0,
            "position_size_multiplier": 1.0,
            "confidence_threshold_delta": 0.0,
            "freeze_recommended": False,
            "eligible_for_review": False,
            "shadow_only": True,
        }

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            records = raw.get("observations", []) if isinstance(raw, dict) else []
            for record in records[-self.window:]:
                if isinstance(record, dict):
                    self._observations.append(CalibrationObservation.from_dict(record))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Regime calibrator could not load %s: %s", self.state_path, exc)

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        payload = {
            "schema_version": 1,
            "updated_at": _utc_now(),
            "shadow_only": True,
            "observations": [asdict(item) for item in self._observations],
        }
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.state_path)


_CALIBRATOR: Optional[RegimePerformanceCalibrator] = None
_CALIBRATOR_LOCK = threading.Lock()


def get_regime_performance_calibrator() -> RegimePerformanceCalibrator:
    """Return the process-wide shadow calibrator singleton."""
    global _CALIBRATOR
    with _CALIBRATOR_LOCK:
        if _CALIBRATOR is None:
            _CALIBRATOR = RegimePerformanceCalibrator()
        return _CALIBRATOR
