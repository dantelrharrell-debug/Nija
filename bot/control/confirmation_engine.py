from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from bot.control.strategy_signal import StrategySignal


@dataclass
class ConfirmationDecision:
    approved: bool
    reasons: List[str]


class ConfirmationEngine:
    """
    Signal confirmation layer between scoring and risk.
    """

    def __init__(self, min_confirmation_score: float = 0.55, max_signal_age_seconds: int = 180) -> None:
        self.min_confirmation_score = min_confirmation_score
        self.max_signal_age_seconds = max_signal_age_seconds

    def confirm(
        self,
        signal: StrategySignal,
        *,
        score: float,
        checks: Dict[str, bool],
    ) -> ConfirmationDecision:
        reasons: List[str] = []
        if score < self.min_confirmation_score:
            reasons.append(f"confirmation_score_too_low:{score:.3f}")
            return ConfirmationDecision(False, reasons)

        stale, stale_reason = self._is_stale(signal.timestamp)
        if stale:
            reasons.append(stale_reason)
            return ConfirmationDecision(False, reasons)

        required_checks = (
            "candle_close",
            "volume",
            "trend",
            "market_data_fresh",
            "broker_available",
        )
        for name in required_checks:
            if name not in checks:
                reasons.append(f"confirmation_not_provided:{name}")
                return ConfirmationDecision(False, reasons)
            if not bool(checks.get(name)):
                reasons.append(f"confirmation_failed:{name}")
                return ConfirmationDecision(False, reasons)
        if not bool(checks.get("spread_ok", True)):
            reasons.append("spread_rejected")
            return ConfirmationDecision(False, reasons)
        if not bool(checks.get("liquidity_ok", True)):
            reasons.append("liquidity_rejected")
            return ConfirmationDecision(False, reasons)
        reasons.append("confirmation_passed")
        return ConfirmationDecision(True, reasons)

    def _is_stale(self, iso_timestamp: str) -> Tuple[bool, str]:
        try:
            created_at = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        except ValueError:
            return True, "invalid_signal_timestamp"
        if created_at.tzinfo is None:
            return True, "naive_signal_timestamp"
        age = (datetime.now(timezone.utc) - created_at.astimezone(timezone.utc)).total_seconds()
        if age > self.max_signal_age_seconds:
            return True, f"stale_signal:{age:.1f}s"
        return False, ""
