"""Bounded regime-aware strategy allocation for NIJA.

This module ranks already-approved strategy signals using two sources:
1. the base signal score produced by SignalScoringEngine; and
2. closed-trade evidence from RegimePerformanceCalibrator.

Safety properties:
- Shadow-first by default. Live ranking requires BOTH
  NIJA_ADAPTIVE_STRATEGY_MODE=active and
  NIJA_ADAPTIVE_STRATEGY_APPROVED=true.
- Never changes SL/TP, position size, broker routing, execution authority,
  idempotency, or risk-engine decisions.
- No performance adjustment is applied until the regime+strategy bucket
  reaches the minimum sample size.
- Adjustments are bounded and statistically shrunk by the calibrator.
- A freeze recommendation can only reduce a strategy's ranking.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from bot.regime_performance_calibrator import (
    get_regime_performance_calibrator,
    normalize_regime,
)

logger = logging.getLogger("nija.adaptive_strategy_allocator")


def _finite(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class AdaptiveStrategyScore:
    strategy: str
    regime: str
    direction: str
    base_score: float
    adaptive_score: float
    selection_score: float
    performance_adjustment: float
    confluence_bonus: float
    sample_size: int
    reliability: float
    expectancy: float
    win_rate: float
    profit_factor: float
    freeze_recommended: bool
    eligible_for_learning: bool
    active: bool

    def to_dict(self) -> Dict[str, object]:
        return {
            "strategy": self.strategy,
            "regime": self.regime,
            "direction": self.direction,
            "base_score": round(self.base_score, 6),
            "adaptive_score": round(self.adaptive_score, 6),
            "selection_score": round(self.selection_score, 6),
            "performance_adjustment": round(self.performance_adjustment, 6),
            "confluence_bonus": round(self.confluence_bonus, 6),
            "sample_size": self.sample_size,
            "reliability": round(self.reliability, 6),
            "expectancy": round(self.expectancy, 8),
            "win_rate": round(self.win_rate, 6),
            "profit_factor": round(self.profit_factor, 6),
            "freeze_recommended": self.freeze_recommended,
            "eligible_for_learning": self.eligible_for_learning,
            "active": self.active,
        }


class AdaptiveStrategyAllocator:
    """Rank confirmed strategy candidates using bounded regime-specific evidence."""

    def __init__(self) -> None:
        self.mode = os.getenv("NIJA_ADAPTIVE_STRATEGY_MODE", "shadow").strip().lower()
        self.approved = os.getenv("NIJA_ADAPTIVE_STRATEGY_APPROVED", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.min_samples = max(5, int(os.getenv("NIJA_ADAPTIVE_STRATEGY_MIN_SAMPLES", "20")))
        self.max_performance_adjustment = _clip(
            _finite(os.getenv("NIJA_ADAPTIVE_STRATEGY_MAX_ADJUSTMENT", "0.12"), 0.12),
            0.0,
            0.25,
        )
        self.confluence_step = _clip(
            _finite(os.getenv("NIJA_ADAPTIVE_STRATEGY_CONFLUENCE_STEP", "0.02"), 0.02),
            0.0,
            0.05,
        )
        self.max_confluence_bonus = _clip(
            _finite(os.getenv("NIJA_ADAPTIVE_STRATEGY_MAX_CONFLUENCE", "0.06"), 0.06),
            0.0,
            0.15,
        )
        self.freeze_penalty = _clip(
            _finite(os.getenv("NIJA_ADAPTIVE_STRATEGY_FREEZE_PENALTY", "0.20"), 0.20),
            0.0,
            0.50,
        )
        self._calibrator = get_regime_performance_calibrator()

        logger.info(
            "AdaptiveStrategyAllocator initialised mode=%s approved=%s min_samples=%d "
            "max_adjustment=%.3f confluence_cap=%.3f",
            self.mode,
            self.approved,
            self.min_samples,
            self.max_performance_adjustment,
            self.max_confluence_bonus,
        )

    @property
    def active(self) -> bool:
        return self.mode == "active" and self.approved

    def evaluate(
        self,
        *,
        strategy: str,
        regime: object,
        direction: str,
        base_score: float,
        same_direction_confirmations: int = 1,
    ) -> AdaptiveStrategyScore:
        """Return a bounded ranking score for one already-confirmed candidate."""
        strategy_key = str(strategy or "unknown").strip() or "unknown"
        regime_key = normalize_regime(regime)
        direction_key = str(direction or "unknown").strip().lower()
        base = _clip(_finite(base_score), 0.0, 1.0)

        report = self._calibrator.get_recommendation(regime_key, strategy_key)
        sample_size = int(report.get("sample_size", 0) or 0)
        reliability = _clip(_finite(report.get("reliability")), 0.0, 1.0)
        eligible = bool(report.get("eligible_for_review")) and sample_size >= self.min_samples
        calibration_score = _clip(_finite(report.get("calibration_score")), -1.0, 1.0)

        performance_adjustment = 0.0
        if eligible:
            performance_adjustment = _clip(
                calibration_score * self.max_performance_adjustment,
                -self.max_performance_adjustment,
                self.max_performance_adjustment,
            )

        freeze_recommended = bool(report.get("freeze_recommended"))
        if freeze_recommended:
            # Freeze evidence must never increase rank.  Keep it bounded so
            # the risk/execution layers remain the final authority.
            performance_adjustment = min(
                performance_adjustment,
                -min(self.freeze_penalty, self.max_performance_adjustment),
            )

        confirmations = max(1, int(same_direction_confirmations or 1))
        confluence_bonus = min(
            self.max_confluence_bonus,
            max(0, confirmations - 1) * self.confluence_step,
        )

        adaptive = _clip(base + performance_adjustment + confluence_bonus, 0.0, 1.0)
        selection_score = adaptive if self.active else base

        return AdaptiveStrategyScore(
            strategy=strategy_key,
            regime=regime_key,
            direction=direction_key,
            base_score=base,
            adaptive_score=adaptive,
            selection_score=selection_score,
            performance_adjustment=performance_adjustment,
            confluence_bonus=confluence_bonus,
            sample_size=sample_size,
            reliability=reliability,
            expectancy=_finite(report.get("expectancy")),
            win_rate=_clip(_finite(report.get("win_rate")), 0.0, 1.0),
            profit_factor=max(0.0, _finite(report.get("profit_factor"))),
            freeze_recommended=freeze_recommended,
            eligible_for_learning=eligible,
            active=self.active,
        )

    def rank(
        self,
        rows: Sequence[Tuple[Any, float]],
    ) -> List[Tuple[Any, float, AdaptiveStrategyScore]]:
        """Rank (candidate, base_score) rows.

        The returned float is the selection score.  In shadow mode it remains
        the original base score, while adaptive_score is still calculated and
        attached for observability.
        """
        direction_counts: Dict[str, int] = {}
        for candidate, _ in rows:
            direction = str(getattr(candidate, "direction", "unknown") or "unknown").lower()
            direction_counts[direction] = direction_counts.get(direction, 0) + 1

        ranked: List[Tuple[Any, float, AdaptiveStrategyScore]] = []
        for candidate, base_score in rows:
            direction = str(getattr(candidate, "direction", "unknown") or "unknown").lower()
            detail = self.evaluate(
                strategy=str(getattr(candidate, "strategy", "unknown") or "unknown"),
                regime=getattr(candidate, "market_regime", "default"),
                direction=direction,
                base_score=base_score,
                same_direction_confirmations=direction_counts.get(direction, 1),
            )
            ranked.append((candidate, detail.selection_score, detail))

        ranked.sort(key=lambda row: row[1], reverse=True)

        if ranked:
            leader = ranked[0][2]
            logger.info(
                "ADAPTIVE_STRATEGY_RANK mode=%s active=%s strategy=%s regime=%s "
                "base=%.3f adaptive=%.3f selected=%.3f samples=%d confluence=%.3f",
                self.mode,
                self.active,
                leader.strategy,
                leader.regime,
                leader.base_score,
                leader.adaptive_score,
                leader.selection_score,
                leader.sample_size,
                leader.confluence_bonus,
            )
        return ranked


_ALLOCATOR: AdaptiveStrategyAllocator | None = None


def get_adaptive_strategy_allocator() -> AdaptiveStrategyAllocator:
    global _ALLOCATOR
    if _ALLOCATOR is None:
        _ALLOCATOR = AdaptiveStrategyAllocator()
    return _ALLOCATOR
