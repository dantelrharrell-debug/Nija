from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MarginHealthSnapshot:
    buying_power_usd: float = 0.0
    maintenance_margin_ratio: float = 0.0
    liquidation_buffer_ratio: float = 1.0
    borrow_available: bool = True


@dataclass
class MarginGateDecision:
    allowed: bool
    reason: str = "ok"


class MarginHealthGate:
    """Broker-agnostic margin safety gate used before order dispatch."""

    def __init__(
        self,
        *,
        min_liquidation_buffer_ratio: float = 0.10,
        max_maintenance_margin_ratio: float = 0.80,
    ) -> None:
        self._min_liquidation_buffer_ratio = max(0.0, float(min_liquidation_buffer_ratio))
        self._max_maintenance_margin_ratio = max(0.0, float(max_maintenance_margin_ratio))

    def assess(
        self,
        *,
        requested_notional_usd: float,
        side: str,
        leverage: Optional[float] = None,
        reduce_only: bool = False,
        borrow_intent: Optional[str] = None,
        snapshot: Optional[MarginHealthSnapshot] = None,
    ) -> MarginGateDecision:
        if reduce_only:
            return MarginGateDecision(True, "reduce_only")

        snap = snapshot or MarginHealthSnapshot()

        if requested_notional_usd > 0 and snap.buying_power_usd > 0 and requested_notional_usd > snap.buying_power_usd:
            return MarginGateDecision(
                False,
                f"insufficient_buying_power:${snap.buying_power_usd:.2f}<${requested_notional_usd:.2f}",
            )

        if snap.maintenance_margin_ratio >= self._max_maintenance_margin_ratio:
            return MarginGateDecision(
                False,
                f"maintenance_margin_ratio_too_high:{snap.maintenance_margin_ratio:.4f}",
            )

        if snap.liquidation_buffer_ratio < self._min_liquidation_buffer_ratio:
            return MarginGateDecision(
                False,
                f"liquidation_buffer_too_low:{snap.liquidation_buffer_ratio:.4f}",
            )

        opening_short = side.lower() in {"sell", "short"}
        requires_borrow = opening_short or (borrow_intent or "").lower() in {"borrow", "required"}
        if requires_borrow and not snap.borrow_available:
            return MarginGateDecision(False, "borrow_unavailable")

        if leverage is not None and leverage <= 0:
            return MarginGateDecision(False, "invalid_leverage")

        return MarginGateDecision(True, "ok")

