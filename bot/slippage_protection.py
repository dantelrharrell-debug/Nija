"""
NIJA Slippage Protection
=========================

Pre-trade gate that estimates execution costs from live market data and
blocks (or warns on) orders where the expected slippage would consume an
unacceptable fraction of the anticipated profit.

How it works
------------
1. Before placing a buy or sell order the caller passes the current bid,
   ask, order size, 24-hour volume and recent volatility to
   ``SlippageProtector.check()``.
2. The underlying ``SlippageModel`` estimates the expected and worst-case
   slippage in basis points.
3. The gate compares the *worst-case* cost against the configured
   ``max_cost_pct`` threshold and returns a ``SlippageCheckResult``
   indicating whether the trade should proceed.
4. After the order is filled the caller should call ``record_fill()`` so
   the model can self-improve over time.

Usage::

    from bot.slippage_protection import get_slippage_protector

    protector = get_slippage_protector()

    result = protector.check(
        symbol="BTC-USD",
        side="buy",
        order_size_usd=5_000,
        bid=50_000,
        ask=50_010,
        volume_24h_usd=500_000_000,
        volatility_pct=0.018,
    )

    if not result.approved:
        print(f"Trade blocked – {result.reason}")
    else:
        # place order …
        protector.record_fill(
            symbol="BTC-USD",
            side="buy",
            expected_price=50_005,
            actual_fill_price=50_020,
        )

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("nija.slippage_protection")


# ---------------------------------------------------------------------------
# Import SlippageModel (graceful fallback if not available)
# ---------------------------------------------------------------------------
try:
    from slippage_model import SlippageModel, SlippageEstimate, MarketCondition
    _SLIPPAGE_MODEL_AVAILABLE = True
except ImportError:
    try:
        from bot.slippage_model import SlippageModel, SlippageEstimate, MarketCondition
        _SLIPPAGE_MODEL_AVAILABLE = True
    except ImportError:
        _SLIPPAGE_MODEL_AVAILABLE = False
        SlippageModel = None  # type: ignore
        SlippageEstimate = None  # type: ignore
        MarketCondition = None  # type: ignore
        logger.warning("⚠️  SlippageModel unavailable – slippage protection in pass-through mode")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SlippageCheckResult:
    """
    Result of a pre-trade slippage check.

    Attributes:
        approved:        Whether the trade should proceed.
        reason:          Human-readable explanation.
        expected_cost_pct: Expected total execution cost (spread + slippage).
        worst_case_pct:  95th-percentile total cost.
        market_condition: Detected market condition label.
        adjusted_price:  Realistic fill price after expected slippage.
        details:         Full per-component breakdown for logging.
    """
    approved: bool
    reason: str
    expected_cost_pct: float = 0.0
    worst_case_pct: float = 0.0
    market_condition: str = "unknown"
    adjusted_price: float = 0.0
    details: Dict = field(default_factory=dict)

    def __str__(self) -> str:
        status = "✅ APPROVED" if self.approved else "❌ BLOCKED"
        return (
            f"SlippageCheck {status}: {self.reason} "
            f"(expected={self.expected_cost_pct*100:.3f}% "
            f"worst={self.worst_case_pct*100:.3f}% "
            f"cond={self.market_condition})"
        )


# ---------------------------------------------------------------------------
# Slippage protector
# ---------------------------------------------------------------------------

class SlippageProtector:
    """
    Pre-trade slippage gate.

    The gate estimates worst-case execution cost and blocks entries whose
    cost would exceed ``max_cost_pct``.  A warning is emitted whenever
    the expected cost exceeds ``warn_cost_pct``, even if the trade is
    ultimately approved.

    Args:
        max_cost_pct:  Maximum acceptable worst-case execution cost as a
                       fraction (default 0.008 = 0.8 %).  Trades whose
                       worst-case cost exceeds this value are blocked.
        warn_cost_pct: Threshold that triggers a warning log message
                       (default 0.004 = 0.4 %).
        min_profit_pct: Minimum net profit percentage required to justify
                        the trade (default 0.005 = 0.5 %).  Used by
                        ``SlippageEstimate.should_skip()``.
        slippage_model_config: Optional dict forwarded to ``SlippageModel``.
    """

    def __init__(
        self,
        max_cost_pct: float = 0.008,
        warn_cost_pct: float = 0.004,
        min_profit_pct: float = 0.005,
        slippage_model_config: Optional[Dict] = None,
    ):
        self.max_cost_pct = max_cost_pct
        self.warn_cost_pct = warn_cost_pct
        self.min_profit_pct = min_profit_pct

        if _SLIPPAGE_MODEL_AVAILABLE and SlippageModel is not None:
            self._model: Optional[SlippageModel] = SlippageModel(config=slippage_model_config)
            logger.info(
                f"✅ SlippageProtector initialized "
                f"(max_cost={max_cost_pct*100:.2f}% "
                f"warn={warn_cost_pct*100:.2f}% "
                f"min_profit={min_profit_pct*100:.2f}%)"
            )
        else:
            self._model = None
            logger.warning("⚠️  SlippageProtector running in pass-through mode (SlippageModel unavailable)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        symbol: str,
        side: str,
        order_size_usd: float,
        bid: float,
        ask: float,
        volume_24h_usd: float = 0.0,
        bid_depth_usd: float = 0.0,
        ask_depth_usd: float = 0.0,
        volatility_pct: float = 0.02,
        market_condition: Optional[str] = None,
    ) -> SlippageCheckResult:
        """
        Evaluate pre-trade slippage risk for a proposed order.

        Args:
            symbol:           Trading pair (e.g. ``"BTC-USD"``).
            side:             ``"buy"`` or ``"sell"``.
            order_size_usd:   Proposed order value in USD.
            bid:              Current best bid price.
            ask:              Current best ask price.
            volume_24h_usd:   24-hour trading volume in USD.
            bid_depth_usd:    USD liquidity at the best bid.
            ask_depth_usd:    USD liquidity at the best ask.
            volatility_pct:   Recent price volatility as a decimal.
            market_condition: Override market condition classification.

        Returns:
            :class:`SlippageCheckResult` with approval decision and details.
        """
        # Pass-through when model is unavailable
        if self._model is None:
            return SlippageCheckResult(
                approved=True,
                reason="slippage_model_unavailable (pass-through)",
                market_condition="unknown",
            )

        try:
            estimate: SlippageEstimate = self._model.estimate(
                symbol=symbol,
                side=side,
                order_size_usd=order_size_usd,
                bid=bid,
                ask=ask,
                volume_24h_usd=volume_24h_usd,
                bid_depth_usd=bid_depth_usd,
                ask_depth_usd=ask_depth_usd,
                volatility_pct=volatility_pct,
                market_condition=market_condition,
            )
        except Exception as exc:
            logger.warning(f"SlippageProtector: model error for {symbol}: {exc}")
            return SlippageCheckResult(
                approved=True,
                reason=f"model_error: {exc} (pass-through)",
                market_condition="unknown",
            )

        mid_price = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
        adjusted = estimate.adjusted_price(mid_price) if mid_price > 0 else 0.0

        # Evaluate thresholds
        if estimate.worst_case_pct >= self.max_cost_pct:
            reason = (
                f"worst-case slippage {estimate.worst_case_pct*100:.3f}% "
                f"exceeds max {self.max_cost_pct*100:.2f}% "
                f"[cond={estimate.market_condition}]"
            )
            result = SlippageCheckResult(
                approved=False,
                reason=reason,
                expected_cost_pct=estimate.total_cost_pct,
                worst_case_pct=estimate.worst_case_pct,
                market_condition=estimate.market_condition,
                adjusted_price=adjusted,
                details=estimate.breakdown,
            )
            logger.info(f"   🚫 SlippageProtector BLOCKED {symbol} {side}: {reason}")
            return result

        # Warn if above warning threshold
        if estimate.total_cost_pct >= self.warn_cost_pct:
            logger.warning(
                f"   ⚠️  SlippageProtector WARNING {symbol} {side}: "
                f"expected cost {estimate.total_cost_pct*100:.3f}% "
                f"(>= warn threshold {self.warn_cost_pct*100:.2f}%) "
                f"[cond={estimate.market_condition}]"
            )

        reason = (
            f"ok – expected={estimate.total_cost_pct*100:.3f}% "
            f"worst={estimate.worst_case_pct*100:.3f}% "
            f"[cond={estimate.market_condition} conf={estimate.confidence:.0%}]"
        )

        result = SlippageCheckResult(
            approved=True,
            reason=reason,
            expected_cost_pct=estimate.total_cost_pct,
            worst_case_pct=estimate.worst_case_pct,
            market_condition=estimate.market_condition,
            adjusted_price=adjusted,
            details=estimate.breakdown,
        )
        logger.debug(f"   ✅ SlippageProtector APPROVED {symbol} {side}: {reason}")
        return result

    def record_fill(
        self,
        symbol: str,
        side: str,
        expected_price: float,
        actual_fill_price: float,
    ) -> float:
        """
        Record an actual fill price to improve future slippage estimates.

        Args:
            symbol:             Trading pair.
            side:               ``"buy"`` or ``"sell"``.
            expected_price:     Mid price or quoted price at signal time.
            actual_fill_price:  Actual price received from the exchange.

        Returns:
            Observed slippage in basis points (positive = adverse).
        """
        if self._model is None:
            return 0.0
        try:
            slip_bps = self._model.record_actual_slippage(
                symbol=symbol,
                expected_price=expected_price,
                actual_fill_price=actual_fill_price,
                side=side,
            )
            logger.debug(
                f"SlippageProtector recorded fill: {symbol} {side} "
                f"expected={expected_price:.4f} fill={actual_fill_price:.4f} "
                f"slippage={slip_bps:.2f}bps"
            )
            return slip_bps
        except Exception as exc:
            logger.debug(f"SlippageProtector.record_fill error for {symbol}: {exc}")
            return 0.0

    def get_stats(self, symbol: str) -> Dict:
        """Return historical slippage statistics for *symbol*."""
        if self._model is None:
            return {}
        try:
            return self._model.get_historical_stats(symbol)
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_PROTECTOR_INSTANCE: Optional[SlippageProtector] = None


def get_slippage_protector(
    max_cost_pct: float = 0.008,
    warn_cost_pct: float = 0.004,
    min_profit_pct: float = 0.005,
) -> SlippageProtector:
    """
    Return the global singleton :class:`SlippageProtector`.

    The first call creates the instance with the supplied configuration;
    subsequent calls ignore the arguments and return the cached instance.
    """
    global _PROTECTOR_INSTANCE
    if _PROTECTOR_INSTANCE is None:
        _PROTECTOR_INSTANCE = SlippageProtector(
            max_cost_pct=max_cost_pct,
            warn_cost_pct=warn_cost_pct,
            min_profit_pct=min_profit_pct,
        )
    return _PROTECTOR_INSTANCE
