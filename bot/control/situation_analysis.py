"""Account-scoped situation analysis for Strategy Engine V2.

This layer is advisory/fail-closed: it summarizes market and execution context
before strategy selection. It never authorizes an order or bypasses risk.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, Optional

from bot.control.regime_engine import RegimeResult
from bot.control.trading_context import TradingContext
from bot.control.isolation_guards import _position_owner_key


@dataclass(frozen=True)
class SituationAssessment:
    scope_key: str
    market_regime: str
    regime_confidence: float
    volatility: float
    liquidity_ok: bool
    spread_ok: bool
    broker_available: bool
    market_data_fresh: bool
    authoritative_position_proven: bool
    open_positions: int
    risk_state: str
    eligible_for_strategy_evaluation: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SituationAnalysisEngine:
    """Combine market, broker, portfolio and authority facts without prediction."""

    def assess(
        self,
        *,
        trading_context: TradingContext,
        regime_result: RegimeResult,
        positions: Iterable[Dict[str, Any]] = (),
        checks: Optional[Dict[str, bool]] = None,
        authoritative_position_proven: bool = True,
    ) -> SituationAssessment:
        checks = checks or {}
        reasons: list[str] = []

        market_data_fresh = bool(checks.get("market_data_fresh", True))
        broker_available = bool(checks.get("broker_available", True))
        spread_ok = bool(checks.get("spread_ok", True))
        liquidity_ok = bool(checks.get("liquidity_ok", True))

        owned_positions = []
        for position in positions or ():
            if not isinstance(position, dict):
                reasons.append("invalid_position_record")
                continue
            owner = _position_owner_key(position)
            if owner is None:
                reasons.append("unscoped_position_record")
            elif owner == trading_context.owner_key:
                owned_positions.append(position)

        if not authoritative_position_proven:
            reasons.append("authoritative_position_unproven")
        if not market_data_fresh:
            reasons.append("market_data_stale")
        if not broker_available:
            reasons.append("broker_unavailable")
        if not spread_ok:
            reasons.append("spread_not_ok")
        if not liquidity_ok:
            reasons.append("liquidity_not_ok")

        regime = getattr(regime_result.regime, "value", regime_result.regime)
        confidence = float(getattr(regime_result, "confidence", 0.0) or 0.0)
        if str(regime) == "unknown" or confidence <= 0:
            reasons.append("market_regime_unproven")

        hard_blocks = {
            "authoritative_position_unproven",
            "market_data_stale",
            "broker_unavailable",
            "spread_not_ok",
            "liquidity_not_ok",
            "unscoped_position_record",
            "invalid_position_record",
            "market_regime_unproven",
        }
        eligible = not any(reason in hard_blocks for reason in reasons)
        risk_state = "clear" if eligible else "blocked"

        return SituationAssessment(
            scope_key=trading_context.scope_key,
            market_regime=str(regime),
            regime_confidence=confidence,
            volatility=float(getattr(regime_result, "volatility", 0.0) or 0.0),
            liquidity_ok=liquidity_ok,
            spread_ok=spread_ok,
            broker_available=broker_available,
            market_data_fresh=market_data_fresh,
            authoritative_position_proven=bool(authoritative_position_proven),
            open_positions=len(owned_positions),
            risk_state=risk_state,
            eligible_for_strategy_evaluation=eligible,
            reasons=tuple(reasons),
        )
