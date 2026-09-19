from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from bot.control.strategy_signal import StrategySignal


@dataclass
class ScoreResult:
    score: float
    confidence: float
    reasons: List[str]
    rejected: bool = False


class SignalScoringEngine:
    """
    Central scoring for StrategySignal candidates.
    """

    def __init__(self, min_score: float = 0.55, reject_conflict_penalty: float = 0.30) -> None:
        self.min_score = min_score
        self.reject_conflict_penalty = reject_conflict_penalty

    def score(self, signal: StrategySignal, context: Dict[str, float]) -> ScoreResult:
        regime_alignment = float(context.get("regime_alignment", 0.5))
        trend = float(context.get("trend_strength", 0.5))
        momentum = float(context.get("momentum_strength", 0.5))
        volume = float(context.get("volume_quality", 0.5))
        volatility = float(context.get("volatility_quality", 0.5))
        rr = float(context.get("reward_risk_quality", 0.5))
        spread_penalty = max(0.0, min(1.0, float(context.get("spread_penalty", 0.0))))
        liquidity_penalty = max(0.0, min(1.0, float(context.get("liquidity_penalty", 0.0))))

        base = signal.confidence if signal.confidence > 0 else signal.raw_score
        score = (
            0.25 * base
            + 0.15 * regime_alignment
            + 0.10 * trend
            + 0.10 * momentum
            + 0.10 * volume
            + 0.10 * volatility
            + 0.20 * rr
        )
        score -= 0.05 * spread_penalty
        score -= 0.05 * liquidity_penalty

        reasons: List[str] = []
        if signal.conflicting_evidence:
            penalty = min(self.reject_conflict_penalty, 0.05 * len(signal.conflicting_evidence))
            score -= penalty
            reasons.append(f"conflict_penalty:{penalty:.3f}")
        score = max(0.0, min(1.0, score))
        rejected = score < self.min_score
        if rejected:
            reasons.append(f"score_below_floor:{score:.3f}<{self.min_score:.3f}")
        return ScoreResult(score=score, confidence=score, reasons=reasons, rejected=rejected)
