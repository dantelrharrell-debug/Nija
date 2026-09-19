from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class StrategySignal:
    """
    Canonical strategy-detector output.

    Signals are intent-only and must pass central scoring, confirmation,
    risk, and sizing layers before execution.
    """

    strategy: str
    symbol: str
    broker: str
    direction: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    entry_zone: Optional[Dict[str, float]] = None
    invalidation_level: Optional[float] = None
    suggested_stop: Optional[float] = None
    target_candidates: List[float] = field(default_factory=list)
    confidence: float = 0.0
    raw_score: float = 0.0
    market_regime: str = "uncertain"
    supporting_evidence: List[str] = field(default_factory=list)
    conflicting_evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "broker": self.broker,
            "direction": self.direction,
            "timestamp": self.timestamp,
            "entry_zone": self.entry_zone,
            "invalidation_level": self.invalidation_level,
            "suggested_stop": self.suggested_stop,
            "target_candidates": list(self.target_candidates),
            "confidence": float(self.confidence),
            "raw_score": float(self.raw_score),
            "market_regime": self.market_regime,
            "supporting_evidence": list(self.supporting_evidence),
            "conflicting_evidence": list(self.conflicting_evidence),
            "metadata": dict(self.metadata),
        }
