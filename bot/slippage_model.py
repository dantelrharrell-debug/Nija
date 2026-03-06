"""
NIJA Slippage Model
====================

Simulates real execution costs before placing an order.

In live cryptocurrency markets the *actual* fill price is almost always
slightly worse than the quoted mid price.  The gap is driven by:

* **Bid-ask spread** – you buy at the ask and sell at the bid.
* **Market impact** – your order consumes book liquidity, temporarily
  moving price against you.
* **Execution slippage** – latency between signal and fill means the
  quoted price may have moved.

This module provides a lightweight, self-contained model for estimating
these costs *before* a trade is placed, allowing the bot to:

* Reject signals where expected total cost exceeds the profit target.
* Adjust position sizing to account for realistic net returns.
* Track predicted vs actual slippage over time to improve the model.

Usage::

    from bot.slippage_model import SlippageModel

    model = SlippageModel()

    estimate = model.estimate(
        symbol="BTC-USD",
        side="buy",
        order_size_usd=5_000,
        bid=50_000,
        ask=50_010,
        volume_24h_usd=500_000_000,
        bid_depth_usd=200_000,
        ask_depth_usd=180_000,
        volatility_pct=0.02,  # 2 % recent volatility
    )

    print(f"Expected cost : {estimate.total_cost_pct * 100:.3f}%")
    print(f"Worst-case    : {estimate.worst_case_pct * 100:.3f}%")

    if estimate.should_skip(min_profit_pct=0.005):
        print("⚠️  Execution cost too high – skipping trade")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.slippage_model")


# ---------------------------------------------------------------------------
# Market condition classification
# ---------------------------------------------------------------------------

class MarketCondition:
    """Market condition labels used to select the slippage regime."""
    CALM = "calm"
    VOLATILE = "volatile"
    ILLIQUID = "illiquid"
    TRENDING = "trending"
    RANGING = "ranging"

    @staticmethod
    def classify(
        spread_bps: float,
        volatility_pct: float,
        volume_24h_usd: float,
    ) -> str:
        """
        Classify current market conditions from observable metrics.

        Args:
            spread_bps:     Current bid-ask spread in basis points.
            volatility_pct: Recent price volatility expressed as a decimal
                            (e.g. 0.02 = 2 %).
            volume_24h_usd: 24-hour trading volume in USD.

        Returns:
            One of the :class:`MarketCondition` string constants.
        """
        if volume_24h_usd < 1_000_000 or spread_bps > 80:
            return MarketCondition.ILLIQUID
        if volatility_pct > 0.05:
            return MarketCondition.VOLATILE
        if spread_bps < 10 and volatility_pct < 0.015:
            return MarketCondition.CALM
        if volatility_pct > 0.025:
            return MarketCondition.TRENDING
        return MarketCondition.RANGING


# ---------------------------------------------------------------------------
# Slippage estimate
# ---------------------------------------------------------------------------

@dataclass
class SlippageEstimate:
    """
    Pre-trade cost estimate for a single order.

    Attributes:
        symbol:             Trading pair.
        side:               ``"buy"`` or ``"sell"``.
        order_size_usd:     Proposed order size in USD.
        spread_cost_pct:    Half-spread cost (paid on every round trip).
        slippage_pct:       Expected market-impact / execution slippage.
        total_cost_pct:     ``spread_cost_pct + slippage_pct``.
        worst_case_pct:     95th-percentile total cost (based on volatility
                            and historical observations).
        confidence:         Model confidence in [0, 1].
        market_condition:   Detected market condition label.
        breakdown:          Per-component cost breakdown for logging.
    """
    symbol: str
    side: str
    order_size_usd: float
    spread_cost_pct: float
    slippage_pct: float
    total_cost_pct: float
    worst_case_pct: float
    confidence: float
    market_condition: str
    breakdown: Dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def adjusted_price(self, quoted_price: float) -> float:
        """
        Apply expected slippage to *quoted_price* to obtain a realistic fill.

        For a buy order the fill will be *higher* than the quote; for a sell
        order it will be *lower*.
        """
        direction = 1.0 if self.side == "buy" else -1.0
        return quoted_price * (1.0 + direction * self.total_cost_pct)

    def should_skip(self, min_profit_pct: float = 0.005) -> bool:
        """
        Return ``True`` when the worst-case execution cost exceeds the
        minimum required profit threshold.

        Args:
            min_profit_pct: Minimum net profit percentage required to make
                the trade worthwhile (default 0.5 %).
        """
        return self.worst_case_pct >= min_profit_pct

    def __str__(self) -> str:
        return (
            f"SlippageEstimate({self.symbol} {self.side} ${self.order_size_usd:,.0f}: "
            f"total={self.total_cost_pct*100:.3f}% "
            f"worst={self.worst_case_pct*100:.3f}% "
            f"cond={self.market_condition} conf={self.confidence:.0%})"
        )


# ---------------------------------------------------------------------------
# Main model
# ---------------------------------------------------------------------------

# Regime-specific slippage parameters calibrated on crypto-market observations.
_SLIPPAGE_REGIMES: Dict[str, Dict] = {
    MarketCondition.CALM: {
        "base_bps": 3.0,      # 0.03 % base slippage
        "size_factor": 0.8,   # extra bps per $10k order
        "variance_bps": 2.0,  # ±2 bps variance
    },
    MarketCondition.VOLATILE: {
        "base_bps": 15.0,
        "size_factor": 2.5,
        "variance_bps": 8.0,
    },
    MarketCondition.ILLIQUID: {
        "base_bps": 25.0,
        "size_factor": 5.0,
        "variance_bps": 15.0,
    },
    MarketCondition.TRENDING: {
        "base_bps": 10.0,
        "size_factor": 1.5,
        "variance_bps": 5.0,
    },
    MarketCondition.RANGING: {
        "base_bps": 6.0,
        "size_factor": 1.0,
        "variance_bps": 3.0,
    },
}

# Minimum historical fills required before blending model + observed data.
_MIN_HISTORICAL_SAMPLES = 10
# Maximum stored per-symbol slippage observations.
_MAX_OBSERVATIONS = 200
# How quickly the blend shifts toward history (reaches 50/50 at 6× _MIN_HISTORICAL_SAMPLES fills).
_HISTORY_WEIGHT_SCALE_FACTOR = 6.0
# Depth impact: bps added per unit of order/depth ratio, capped at this value.
_DEPTH_IMPACT_SCALE = 20.0   # bps per 100 % depth consumption
_MAX_DEPTH_IMPACT_BPS = 50.0
# Volatility impact: fraction of volatility (as bps) added as slippage (10 %).
_VOLATILITY_IMPACT_FACTOR = 0.10
# Fraction of max spread that triggers a "near limit" warning.
_SPREAD_WARNING_THRESHOLD = 0.8


class SlippageModel:
    """
    Lightweight slippage simulation model.

    Estimates pre-trade execution costs from observable market data
    (bid/ask, depth, volume, volatility) and improves over time as real
    fills are recorded.

    The model works in three phases:
    1. **Pure model** – regime-based slippage formula (no history).
    2. **Blended** – weighted average of model + historical observations
       once :attr:`_MIN_HISTORICAL_SAMPLES` fills have been collected.
    3. **Confidence scaling** – confidence is reduced for illiquid markets
       or when depth/volume data is absent.
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: Optional overrides:
                - ``min_historical_samples`` (int)  – default 10
                - ``max_observations``       (int)  – default 200
        """
        cfg = config or {}
        self._min_samples = cfg.get("min_historical_samples", _MIN_HISTORICAL_SAMPLES)
        self._max_obs = cfg.get("max_observations", _MAX_OBSERVATIONS)

        # Observed slippage per symbol: symbol → list[float (bps)]
        self._history: Dict[str, List[float]] = {}

        logger.info("📊 SlippageModel initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(
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
    ) -> SlippageEstimate:
        """
        Estimate execution costs for a proposed order.

        Args:
            symbol:          Trading pair, e.g. ``"BTC-USD"``.
            side:            ``"buy"`` or ``"sell"``.
            order_size_usd:  Order value in USD.
            bid:             Current best bid price.
            ask:             Current best ask price.
            volume_24h_usd:  24-hour USD volume.
            bid_depth_usd:   USD value at the best bid level.
            ask_depth_usd:   USD value at the best ask level.
            volatility_pct:  Recent price volatility as a decimal.
            market_condition: Override automatic condition classification.

        Returns:
            :class:`SlippageEstimate` with per-component breakdown.
        """
        if bid <= 0 or ask <= 0:
            return self._zero_estimate(symbol, side, order_size_usd, "invalid prices")

        mid_price = (bid + ask) / 2.0
        spread = ask - bid
        spread_bps = (spread / mid_price) * 10_000.0

        # 1. Detect market condition
        if market_condition is None:
            market_condition = MarketCondition.classify(
                spread_bps=spread_bps,
                volatility_pct=volatility_pct,
                volume_24h_usd=volume_24h_usd,
            )

        regime = _SLIPPAGE_REGIMES.get(market_condition, _SLIPPAGE_REGIMES[MarketCondition.RANGING])

        # 2. Half-spread cost (unavoidable on a market order)
        half_spread_bps = spread_bps / 2.0

        # 3. Market-impact / execution slippage
        size_bps = (order_size_usd / 10_000.0) * regime["size_factor"]
        relevant_depth = ask_depth_usd if side == "buy" else bid_depth_usd
        if relevant_depth > 0:
            depth_ratio = order_size_usd / relevant_depth
            depth_bps = min(depth_ratio * _DEPTH_IMPACT_SCALE, _MAX_DEPTH_IMPACT_BPS)
        else:
            depth_bps = regime["base_bps"] * 0.5  # rough estimate when depth unknown

        # Convert volatility to bps using calibrated factor (10 % of vol in bps).
        vol_bps = volatility_pct * 1_000.0 * _VOLATILITY_IMPACT_FACTOR

        model_slippage_bps = regime["base_bps"] + size_bps + depth_bps + vol_bps

        # 4. Blend with historical data when available
        history = self._history.get(symbol, [])
        if len(history) >= self._min_samples:
            recent = history[-self._min_samples:]
            hist_avg_bps = max(0.0, sum(recent) / len(recent))
            hist_weight = min(0.5, len(history) / (_MIN_HISTORICAL_SAMPLES * _HISTORY_WEIGHT_SCALE_FACTOR))
            slippage_bps = (1.0 - hist_weight) * model_slippage_bps + hist_weight * hist_avg_bps

            # 95th-percentile worst case
            sorted_hist = sorted(history)
            p95_idx = max(0, int(len(sorted_hist) * 0.95) - 1)
            worst_bps = max(float(sorted_hist[p95_idx]), slippage_bps + regime["variance_bps"])
            confidence = min(0.95, 0.80 + hist_weight * 0.3)
        else:
            slippage_bps = model_slippage_bps
            worst_bps = slippage_bps + 2.0 * regime["variance_bps"]
            confidence = 0.80

        # 5. Confidence scaling for data quality
        if volume_24h_usd == 0:
            confidence *= 0.85
        if relevant_depth == 0:
            confidence *= 0.80
        if market_condition == MarketCondition.ILLIQUID:
            confidence *= 0.75
        confidence = max(0.0, min(1.0, confidence))

        # 6. Convert bps to fraction
        total_cost_pct = (half_spread_bps + slippage_bps) / 10_000.0
        worst_case_pct = (half_spread_bps + worst_bps) / 10_000.0

        breakdown = {
            "half_spread_bps": round(half_spread_bps, 2),
            "base_slippage_bps": round(regime["base_bps"], 2),
            "size_impact_bps": round(size_bps, 2),
            "depth_impact_bps": round(depth_bps, 2),
            "volatility_impact_bps": round(vol_bps, 2),
            "total_slippage_bps": round(slippage_bps, 2),
            "worst_case_bps": round(worst_bps, 2),
        }

        estimate = SlippageEstimate(
            symbol=symbol,
            side=side,
            order_size_usd=order_size_usd,
            spread_cost_pct=half_spread_bps / 10_000.0,
            slippage_pct=slippage_bps / 10_000.0,
            total_cost_pct=total_cost_pct,
            worst_case_pct=worst_case_pct,
            confidence=confidence,
            market_condition=market_condition,
            breakdown=breakdown,
        )

        logger.debug(
            f"SlippageModel {symbol} {side}: "
            f"spread={half_spread_bps:.1f}bps slip={slippage_bps:.1f}bps "
            f"total={total_cost_pct*100:.3f}% worst={worst_case_pct*100:.3f}% "
            f"cond={market_condition} conf={confidence:.0%}"
        )

        return estimate

    def record_actual_slippage(
        self,
        symbol: str,
        expected_price: float,
        actual_fill_price: float,
        side: str,
    ) -> float:
        """
        Record an observed fill to improve future estimates.

        Args:
            symbol:             Trading pair.
            expected_price:     Mid price or quoted price at signal time.
            actual_fill_price:  Real price received from the exchange.
            side:               ``"buy"`` or ``"sell"``.

        Returns:
            Observed slippage in basis points (positive = adverse).
        """
        if expected_price <= 0 or actual_fill_price <= 0:
            return 0.0

        if side == "buy":
            slip_pct = (actual_fill_price - expected_price) / expected_price
        else:
            slip_pct = (expected_price - actual_fill_price) / expected_price

        slip_bps = slip_pct * 10_000.0

        if symbol not in self._history:
            self._history[symbol] = []
        self._history[symbol].append(slip_bps)

        # Trim to max observations
        if len(self._history[symbol]) > self._max_obs:
            self._history[symbol] = self._history[symbol][-self._max_obs:]

        logger.debug(f"SlippageModel recorded {symbol}: {slip_bps:.2f}bps (n={len(self._history[symbol])})")
        return slip_bps

    def get_historical_stats(self, symbol: str) -> Dict[str, float]:
        """
        Return descriptive statistics for observed slippage on *symbol*.

        Returns:
            Dictionary with ``mean_bps``, ``std_bps``, ``p95_bps``,
            ``n_observations``.  All values are zero if no history exists.
        """
        history = self._history.get(symbol, [])
        if not history:
            return {"mean_bps": 0.0, "std_bps": 0.0, "p95_bps": 0.0, "n_observations": 0}

        mean_v = sum(history) / len(history)
        variance = sum((x - mean_v) ** 2 for x in history) / len(history)
        std_v = math.sqrt(variance)
        sorted_h = sorted(history)
        p95_idx = max(0, int(len(sorted_h) * 0.95) - 1)
        p95_v = sorted_h[p95_idx]

        return {
            "mean_bps": round(mean_v, 2),
            "std_bps": round(std_v, 2),
            "p95_bps": round(p95_v, 2),
            "n_observations": len(history),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _zero_estimate(symbol: str, side: str, size: float, reason: str) -> SlippageEstimate:
        logger.warning(f"SlippageModel: returning zero estimate for {symbol} – {reason}")
        return SlippageEstimate(
            symbol=symbol,
            side=side,
            order_size_usd=size,
            spread_cost_pct=0.0,
            slippage_pct=0.0,
            total_cost_pct=0.0,
            worst_case_pct=0.0,
            confidence=0.0,
            market_condition=MarketCondition.CALM,
            breakdown={},
        )
