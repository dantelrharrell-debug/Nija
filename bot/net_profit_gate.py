"""
Net Profit Gate — Leak #1 fix
==============================
Ensures every signal's *expected net profit* beats total round-trip costs
(spread + slippage + fees) by a configurable safety multiple (default 2×).

Formula
-------
Round-trip cost estimate = spread_pct + slippage_pct + fee_pct (entry + exit)
Profit target % is pulled from the analysis dict.

Gate:  profit_target_pct  ≥  round_trip_cost_pct × safety_multiple

If the gate fails the signal is rejected before any position-sizing or order
placement occurs, avoiding trades that earn less than their own costs.

Usage
-----
::

    from bot.net_profit_gate import get_net_profit_gate

    gate = get_net_profit_gate()
    ok, reason = gate.check(
        symbol="BTC-USD",
        profit_target_pct=0.03,   # 3% from analysis
        spread_pct=0.004,         # 0.4% bid/ask spread
        slippage_pct=0.003,       # 0.3% estimated slippage
        fee_pct=0.006,            # 0.6% round-trip fees (entry + exit)
    )
    if not ok:
        continue  # skip signal

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger("nija.net_profit_gate")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Coinbase advanced-trade round-trip fee for taker orders: ~0.6% (0.3% × 2)
DEFAULT_FEE_PCT: float = 0.006
# Estimated slippage on a liquid pair (BTC/ETH/SOL).  Conservative default.
DEFAULT_SLIPPAGE_PCT: float = 0.003
# Minimum: profit target must be at least this many times the round-trip cost
DEFAULT_SAFETY_MULTIPLE: float = 2.0
# Minimum absolute profit target we'll ever allow (even if multiple passes)
MIN_PROFIT_TARGET_PCT: float = 0.005  # 0.5%


@dataclass
class GateResult:
    approved: bool
    symbol: str
    profit_target_pct: float
    round_trip_cost_pct: float
    required_pct: float
    safety_multiple: float
    reason: str


class NetProfitGate:
    """Pre-flight gate: blocks entries whose profit target doesn't clear costs."""

    def __init__(
        self,
        default_fee_pct: float = DEFAULT_FEE_PCT,
        default_slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
        safety_multiple: float = DEFAULT_SAFETY_MULTIPLE,
        enabled: bool = True,
    ) -> None:
        self.default_fee_pct = default_fee_pct
        self.default_slippage_pct = default_slippage_pct
        self.safety_multiple = safety_multiple
        self.enabled = enabled
        logger.info(
            "💰 Net Profit Gate initialised | safety_multiple=%.1f× | "
            "fee=%.2f%% | slippage=%.2f%%",
            safety_multiple,
            default_fee_pct * 100,
            default_slippage_pct * 100,
        )

    def check(
        self,
        symbol: str,
        profit_target_pct: float,
        spread_pct: float,
        slippage_pct: Optional[float] = None,
        fee_pct: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Verify that *profit_target_pct* clears the round-trip cost estimate
        by at least *safety_multiple* times.

        Args:
            symbol:            Trading pair (for logging).
            profit_target_pct: Expected gross profit as a fraction (e.g. 0.03
                               for 3%).  Use the *first* / primary take-profit.
            spread_pct:        Bid/ask spread as a fraction (e.g. 0.004 = 0.4%).
            slippage_pct:      Estimated slippage fraction.  Falls back to the
                               constructor default when *None*.
            fee_pct:           Round-trip exchange fees as a fraction (entry +
                               exit combined).  Falls back to the constructor
                               default when *None*.

        Returns:
            Tuple of ``(approved: bool, reason: str)``.  When *approved* is
            False the caller should skip the signal.
        """
        if not self.enabled:
            return True, "gate disabled"

        slip = slippage_pct if slippage_pct is not None else self.default_slippage_pct
        fee = fee_pct if fee_pct is not None else self.default_fee_pct

        round_trip_cost = spread_pct + slip + fee
        required = round_trip_cost * self.safety_multiple

        result = GateResult(
            approved=profit_target_pct >= required and profit_target_pct >= MIN_PROFIT_TARGET_PCT,
            symbol=symbol,
            profit_target_pct=profit_target_pct,
            round_trip_cost_pct=round_trip_cost,
            required_pct=required,
            safety_multiple=self.safety_multiple,
            reason="",
        )

        if not result.approved:
            if profit_target_pct < MIN_PROFIT_TARGET_PCT:
                result.reason = (
                    f"profit target {profit_target_pct*100:.2f}% < "
                    f"absolute minimum {MIN_PROFIT_TARGET_PCT*100:.1f}%"
                )
            else:
                result.reason = (
                    f"profit target {profit_target_pct*100:.2f}% < "
                    f"required {required*100:.2f}% "
                    f"(spread {spread_pct*100:.2f}% + slip {slip*100:.2f}% "
                    f"+ fees {fee*100:.2f}% = {round_trip_cost*100:.2f}% × {self.safety_multiple})"
                )
            logger.info("🚫 NET PROFIT GATE: %s rejected — %s", symbol, result.reason)
        else:
            net_after_costs = profit_target_pct - round_trip_cost
            logger.debug(
                "✅ Net Profit Gate: %s approved | target %.2f%% | costs %.2f%% | net %.2f%%",
                symbol,
                profit_target_pct * 100,
                round_trip_cost * 100,
                net_after_costs * 100,
            )

        return result.approved, result.reason


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[NetProfitGate] = None


def get_net_profit_gate(
    safety_multiple: float = DEFAULT_SAFETY_MULTIPLE,
    default_fee_pct: float = DEFAULT_FEE_PCT,
    default_slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
    enabled: bool = True,
) -> NetProfitGate:
    """Return the process-wide singleton, creating it on first call."""
    global _instance
    if _instance is None:
        _instance = NetProfitGate(
            default_fee_pct=default_fee_pct,
            default_slippage_pct=default_slippage_pct,
            safety_multiple=safety_multiple,
            enabled=enabled,
        )
    return _instance
