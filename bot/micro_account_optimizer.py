"""
MICRO ACCOUNT OPTIMIZER
=======================
Prevents dust creation *before* it happens by gating every new entry order.

A trade that looks small at entry time can easily fall below the $1 exchange
minimum after:
  • Round-trip fees (~1.4% on Coinbase, ~0.36% on Kraken)
  • A 10-20% adverse price move
  • Partial-fill slippage

This module computes the **minimum viable position size** for the current
account balance + broker, then exposes a single ``gate_entry()`` call that
returns ``GateDecision(allowed, recommended_size, reason)``.

Integration (trading_strategy.py)
----------------------------------
    from bot.micro_account_optimizer import get_micro_account_optimizer

    optimizer = get_micro_account_optimizer()
    decision  = optimizer.gate_entry(
        symbol         = symbol,
        position_size  = position_size,
        account_balance= account_balance,
        broker_name    = broker_name,
    )
    if not decision.allowed:
        logger.info(f"   ❌ Entry blocked by MicroAccountOptimizer: {decision.reason}")
        continue
    # Use decision.recommended_size if you want the floor-adjusted size
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger("nija.micro_account_optimizer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Exchange hard floor — the minimum position value that can ever be sold.
# Positions that could fall below this after fees+drawdown must be blocked.
EXCHANGE_SELL_FLOOR_USD: float = 1.00

# Safety multiplier on top of the exchange floor so we stay comfortably
# above it even after fees + a typical adverse move.
SAFETY_MULTIPLIER: float = 3.0  # recommended_min = floor × 3 = $3.00

# Round-trip fee rates by broker (maker+taker, conservative estimates)
BROKER_FEE_RATES: Dict[str, float] = {
    "coinbase": 0.014,   # ~1.4% round-trip
    "kraken":   0.0036,  # ~0.36% round-trip (maker 0.10% + taker 0.26%)
    "binance":  0.002,   # ~0.2% round-trip
    "okx":      0.002,
    "alpaca":   0.0,     # commission-free stocks
    "default":  0.015,   # conservative fallback
}

# Worst-case adverse move buffer added on top of fees
DRAWDOWN_BUFFER_PCT: float = 0.15  # 15% price drop before the position is reviewed

# Absolute floor — no trade below this USD value, ever
ABS_MIN_POSITION_USD: float = 5.00


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GateDecision:
    """Decision returned by ``MicroAccountOptimizer.gate_entry()``."""
    allowed: bool
    requested_size: float
    recommended_size: float   # >= requested_size if allowed; min viable size if blocked
    reason: str
    fee_cost_usd: float
    worst_case_value_usd: float  # value after fees + drawdown buffer


# ---------------------------------------------------------------------------
# Core optimizer
# ---------------------------------------------------------------------------

class MicroAccountOptimizer:
    """
    Gates new entry orders to prevent creation of dust positions.

    Checks:
    1. ABS_MIN_POSITION_USD — hard floor, no trade below $5.
    2. Fee break-even — position must be large enough that round-trip fees
       don't eat more than ``max_fee_pct`` of the position.
    3. Dust-survival check — position must survive DRAWDOWN_BUFFER_PCT adverse
       move AND still be above EXCHANGE_SELL_FLOOR_USD (× SAFETY_MULTIPLIER).

    Parameters
    ----------
    max_fee_pct:
        Maximum fraction of position that round-trip fees may consume before
        the trade is considered unproductive.  Default 0.05 (5%).
    """

    def __init__(self, max_fee_pct: float = 0.05) -> None:
        self.max_fee_pct = max_fee_pct
        self._lock = threading.Lock()
        logger.info(
            "💡 MicroAccountOptimizer initialised | abs_min=$%.2f | "
            "safety=%.1f× | drawdown_buffer=%.0f%%",
            ABS_MIN_POSITION_USD, SAFETY_MULTIPLIER, DRAWDOWN_BUFFER_PCT * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def gate_entry(
        self,
        symbol: str,
        position_size: float,
        account_balance: float,
        broker_name: str = "",
    ) -> GateDecision:
        """
        Decide whether a new entry is allowed and what the minimum viable
        position size is for the current account + broker.

        Parameters
        ----------
        symbol:
            Trading pair (used for logging only).
        position_size:
            Proposed position size in USD.
        account_balance:
            Current available balance in USD.
        broker_name:
            Broker identifier (e.g. ``"coinbase"``, ``"kraken"``).

        Returns
        -------
        GateDecision
        """
        with self._lock:
            return self._evaluate(symbol, position_size, account_balance, broker_name)

    def minimum_viable_size(self, broker_name: str = "") -> float:
        """
        Return the minimum position size (USD) that is guaranteed to survive
        fees + drawdown and remain above the exchange sell floor.
        """
        fee_rate = self._fee_rate(broker_name)
        # After round-trip fees and drawdown buffer the residual must be ≥ floor × safety
        # residual = size × (1 - fee_rate) × (1 - drawdown_buffer)
        # size = floor × safety / ((1 - fee_rate) × (1 - drawdown_buffer))
        denominator = (1.0 - fee_rate) * (1.0 - DRAWDOWN_BUFFER_PCT)
        if denominator <= 0:
            denominator = 0.01
        raw = (EXCHANGE_SELL_FLOOR_USD * SAFETY_MULTIPLIER) / denominator
        return max(ABS_MIN_POSITION_USD, raw)

    # ------------------------------------------------------------------
    # Internal logic
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        symbol: str,
        position_size: float,
        account_balance: float,
        broker_name: str,
    ) -> GateDecision:
        fee_rate = self._fee_rate(broker_name)
        fee_cost = position_size * fee_rate
        worst_case = position_size * (1.0 - fee_rate) * (1.0 - DRAWDOWN_BUFFER_PCT)
        survival_floor = EXCHANGE_SELL_FLOOR_USD * SAFETY_MULTIPLIER
        min_viable = self.minimum_viable_size(broker_name)

        # Gate 1 — absolute hard floor
        if position_size < ABS_MIN_POSITION_USD:
            return GateDecision(
                allowed=False,
                requested_size=position_size,
                recommended_size=min_viable,
                reason=(
                    f"Below absolute floor: ${position_size:.2f} < ${ABS_MIN_POSITION_USD:.2f}. "
                    f"Minimum viable size for {broker_name or 'this broker'}: ${min_viable:.2f}"
                ),
                fee_cost_usd=fee_cost,
                worst_case_value_usd=worst_case,
            )

        # Gate 2 — fee efficiency check
        if fee_cost > position_size * self.max_fee_pct:
            return GateDecision(
                allowed=False,
                requested_size=position_size,
                recommended_size=min_viable,
                reason=(
                    f"Fee-inefficient: fees ${fee_cost:.4f} = "
                    f"{fee_cost/position_size*100:.1f}% of ${position_size:.2f} "
                    f"(max allowed {self.max_fee_pct*100:.0f}%). "
                    f"Minimum viable: ${min_viable:.2f}"
                ),
                fee_cost_usd=fee_cost,
                worst_case_value_usd=worst_case,
            )

        # Gate 3 — dust-survival check
        if worst_case < survival_floor:
            return GateDecision(
                allowed=False,
                requested_size=position_size,
                recommended_size=min_viable,
                reason=(
                    f"Dust risk: ${position_size:.2f} after fees+{DRAWDOWN_BUFFER_PCT*100:.0f}% "
                    f"drawdown = ${worst_case:.4f} < ${survival_floor:.2f} safety floor. "
                    f"Minimum viable: ${min_viable:.2f}"
                ),
                fee_cost_usd=fee_cost,
                worst_case_value_usd=worst_case,
            )

        # All gates passed
        return GateDecision(
            allowed=True,
            requested_size=position_size,
            recommended_size=position_size,
            reason=f"OK — worst-case value ${worst_case:.4f} > ${survival_floor:.2f} floor",
            fee_cost_usd=fee_cost,
            worst_case_value_usd=worst_case,
        )

    @staticmethod
    def _fee_rate(broker_name: str) -> float:
        key = broker_name.lower() if broker_name else "default"
        return BROKER_FEE_RATES.get(key, BROKER_FEE_RATES["default"])


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[MicroAccountOptimizer] = None
_instance_lock = threading.Lock()


def get_micro_account_optimizer(max_fee_pct: float = 0.05) -> MicroAccountOptimizer:
    """Return the process-wide singleton MicroAccountOptimizer."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = MicroAccountOptimizer(max_fee_pct=max_fee_pct)
        return _instance
