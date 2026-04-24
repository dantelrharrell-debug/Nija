"""
NIJA Liquidity Depth Filter
============================

Avoids trading coins with insufficient order-book depth.

Shallow order books lead to:
- High slippage on entry *and* exit
- Price impact that moves the market against the bot
- Inability to exit positions cleanly in volatile conditions

This filter checks three complementary dimensions of liquidity:
1. **Order-book depth** – total USD value sitting in the book within a
   configurable price band of the mid price.
2. **Bid-ask spread** – wide spreads signal illiquid or stressed markets.
3. **Volume** – minimum 24-hour turnover ensures there is *ongoing* interest
   in the market (not just stale resting orders).

Usage::

    from bot.liquidity_depth_filter import LiquidityDepthFilter

    filt = LiquidityDepthFilter(min_depth_usd=50_000)

    # Minimal usage (top-of-book only)
    result = filt.check("ETH-USD", bid=3_000, ask=3_002, bid_depth_usd=40_000, ask_depth_usd=35_000)
    if not result.passed:
        print(result.reason)

    # With full order-book levels
    book = {
        'bids': [[2_999, 5.0], [2_998, 10.0], ...],
        'asks': [[3_001, 4.5], [3_002,  8.0], ...],
    }
    result = filt.check("ETH-USD", bid=3_000, ask=3_002, order_book=book)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("nija.liquidity_depth_filter")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class DepthQuality(Enum):
    """Qualitative classification of order-book depth."""
    EXCELLENT = "excellent"   # > 5× minimum – very liquid
    GOOD = "good"             # 2–5× minimum – normal liquid
    FAIR = "fair"             # 1–2× minimum – acceptable
    POOR = "poor"             # < minimum – avoid trading
    CRITICAL = "critical"     # Near zero – never trade


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DepthFilterResult:
    """Result returned by :meth:`LiquidityDepthFilter.check`."""
    passed: bool
    reason: str
    symbol: str = ""
    depth_quality: DepthQuality = DepthQuality.FAIR
    total_depth_usd: float = 0.0
    spread_bps: float = 0.0
    volume_24h_usd: float = 0.0
    details: Dict = field(default_factory=dict)

    def __str__(self) -> str:
        status = "✅ PASSED" if self.passed else "❌ BLOCKED"
        return (
            f"{status} [{self.symbol}] depth=${self.total_depth_usd:,.0f} "
            f"spread={self.spread_bps:.1f}bps quality={self.depth_quality.value} "
            f"| {self.reason}"
        )


# ---------------------------------------------------------------------------
# Main filter class
# ---------------------------------------------------------------------------

class LiquidityDepthFilter:
    """
    Pre-trade order-book depth filter.

    Blocks entry into markets where the combined bid+ask depth within
    ``depth_band_pct`` of the mid price is below ``min_depth_usd``.

    Args:
        min_depth_usd: Minimum acceptable total order-book depth in USD
            (sum of bid side + ask side within the price band).
            Default 25,000 USD – suitable for STARTER/SAVER tier accounts.
            Larger accounts should raise this proportionally.
        max_spread_bps: Maximum acceptable bid-ask spread in basis points.
            A spread above this threshold blocks the trade regardless of depth.
        min_volume_24h_usd: Optional minimum 24-hour volume gate.  Set to 0
            to disable the volume check.
        depth_band_pct: Price band (as a fraction of mid price) used when
            aggregating full order-book levels.  Default 0.5 % (50 bps).
        max_position_depth_ratio: Maximum allowed ratio of the proposed position
            size to the total available depth.  Positions above this fraction
            consume too much book liquidity and risk significant market impact
            (default 0.25 = 25 %).
    """

    # Fraction of max_spread_bps that triggers a "near limit" warning.
    _SPREAD_WARNING_THRESHOLD = 0.8

    def __init__(
        self,
        min_depth_usd: float = 25_000.0,
        max_spread_bps: float = 50.0,
        min_volume_24h_usd: float = 500_000.0,
        depth_band_pct: float = 0.005,
        max_position_depth_ratio: float = 0.25,
    ):
        self.min_depth_usd = min_depth_usd
        self.max_spread_bps = max_spread_bps
        self.min_volume_24h_usd = min_volume_24h_usd
        self.depth_band_pct = depth_band_pct
        self.max_position_depth_ratio = max_position_depth_ratio

        logger.info(
            "💧 LiquidityDepthFilter initialised – "
            f"min_depth=${min_depth_usd:,.0f}, "
            f"max_spread={max_spread_bps:.0f}bps, "
            f"min_vol=${min_volume_24h_usd:,.0f}, "
            f"max_pos_ratio={max_position_depth_ratio:.0%}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        symbol: str,
        bid: float,
        ask: float,
        bid_depth_usd: float = 0.0,
        ask_depth_usd: float = 0.0,
        order_book: Optional[Dict[str, List]] = None,
        volume_24h_usd: float = 0.0,
        position_size_usd: float = 0.0,
    ) -> DepthFilterResult:
        """
        Evaluate whether *symbol* has sufficient order-book depth to trade.

        Args:
            symbol: Trading pair, e.g. ``"BTC-USD"``.
            bid: Best bid price.
            ask: Best ask price.
            bid_depth_usd: USD value of liquidity at the best bid.  Used when
                a full order book is not available.
            ask_depth_usd: USD value of liquidity at the best ask.
            order_book: Optional full order-book dictionary with keys
                ``"bids"`` and ``"asks"``.  Each value is a list of
                ``[price, size]`` pairs sorted best-first.  When provided,
                depth is aggregated across all levels within the price band.
            volume_24h_usd: 24-hour trading volume in USD.
            position_size_usd: Proposed position size.  Used to check that the
                order does not consume an outsized fraction of available depth.

        Returns:
            :class:`DepthFilterResult` – inspect ``.passed`` to decide.
        """
        if bid <= 0 or ask <= 0:
            return DepthFilterResult(
                passed=False,
                reason="Invalid bid/ask prices",
                symbol=symbol,
            )

        mid_price = (bid + ask) / 2.0
        spread = ask - bid
        spread_bps = (spread / mid_price) * 10_000.0

        # ------------------------------------------------------------------
        # 1. Compute total depth
        # ------------------------------------------------------------------
        if order_book is not None:
            total_depth_usd = self._aggregate_book_depth(order_book, mid_price)
        elif bid_depth_usd > 0 or ask_depth_usd > 0:
            total_depth_usd = bid_depth_usd + ask_depth_usd
        else:
            total_depth_usd = 0.0

        # ------------------------------------------------------------------
        # 2. Classify depth quality
        # ------------------------------------------------------------------
        depth_quality = self._classify_depth(total_depth_usd)

        # ------------------------------------------------------------------
        # 3. Build violation list
        # ------------------------------------------------------------------
        violations: List[str] = []
        warnings: List[str] = []

        # Spread check
        if spread_bps > self.max_spread_bps:
            violations.append(
                f"Spread {spread_bps:.1f}bps > max {self.max_spread_bps:.0f}bps"
            )
        elif spread_bps > self.max_spread_bps * self._SPREAD_WARNING_THRESHOLD:
            warnings.append(f"Spread {spread_bps:.1f}bps approaching limit")

        # Depth check
        if total_depth_usd > 0:
            if total_depth_usd < self.min_depth_usd:
                violations.append(
                    f"Depth ${total_depth_usd:,.0f} < min ${self.min_depth_usd:,.0f}"
                )
            elif total_depth_usd < self.min_depth_usd * 1.5:
                warnings.append(f"Depth ${total_depth_usd:,.0f} only marginally above minimum")
        # If no depth data supplied, skip the depth gate (warning only).
        else:
            warnings.append("No order-book depth data available – depth gate skipped")

        # Volume check
        if self.min_volume_24h_usd > 0 and volume_24h_usd > 0:
            if volume_24h_usd < self.min_volume_24h_usd:
                violations.append(
                    f"Volume ${volume_24h_usd:,.0f} < min ${self.min_volume_24h_usd:,.0f}"
                )

        # Position-size vs depth check
        if position_size_usd > 0 and total_depth_usd > 0:
            pos_ratio = position_size_usd / total_depth_usd
            if pos_ratio > self.max_position_depth_ratio:
                violations.append(
                    f"Position {pos_ratio:.0%} of available depth "
                    f"(>{self.max_position_depth_ratio:.0%} – too large)"
                )
            elif pos_ratio > self.max_position_depth_ratio * 0.4:
                warnings.append(f"Position consumes {pos_ratio:.0%} of available depth")

        # ------------------------------------------------------------------
        # 4. Build result
        # ------------------------------------------------------------------
        passed = len(violations) == 0
        if violations:
            reason = "; ".join(violations)
        elif warnings:
            reason = "OK (warnings: " + "; ".join(warnings) + ")"
        else:
            reason = "OK"

        result = DepthFilterResult(
            passed=passed,
            reason=reason,
            symbol=symbol,
            depth_quality=depth_quality,
            total_depth_usd=total_depth_usd,
            spread_bps=spread_bps,
            volume_24h_usd=volume_24h_usd,
            details={
                "bid": bid,
                "ask": ask,
                "spread_bps": round(spread_bps, 2),
                "total_depth_usd": round(total_depth_usd, 2),
                "min_depth_usd": self.min_depth_usd,
                "depth_quality": depth_quality.value,
                "volume_24h_usd": volume_24h_usd,
                "warnings": warnings,
            },
        )

        if not passed:
            logger.info(f"   🚫 LiquidityDepthFilter BLOCKED {symbol}: {reason}")
        else:
            logger.debug(f"   ✅ LiquidityDepthFilter OK {symbol}: {reason}")

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _aggregate_book_depth(
        self,
        order_book: Dict[str, List],
        mid_price: float,
    ) -> float:
        """
        Sum the USD value of all order-book levels within ``depth_band_pct``
        of *mid_price* on both sides.
        """
        max_distance = mid_price * self.depth_band_pct
        total = 0.0

        for level in order_book.get("bids", []):
            price, size = self._parse_level(level)
            if price > 0 and abs(price - mid_price) <= max_distance:
                total += price * size

        for level in order_book.get("asks", []):
            price, size = self._parse_level(level)
            if price > 0 and abs(price - mid_price) <= max_distance:
                total += price * size

        return total

    @staticmethod
    def _parse_level(level) -> tuple:
        """Parse a single order-book level into (price, size) floats."""
        try:
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                return float(level[0]), float(level[1])
            if isinstance(level, dict):
                return float(level.get("price", 0)), float(level.get("size", 0))
        except (TypeError, ValueError):
            pass
        return 0.0, 0.0

    def _classify_depth(self, depth_usd: float) -> DepthQuality:
        """Classify total depth into a :class:`DepthQuality` category."""
        if depth_usd <= 0:
            return DepthQuality.CRITICAL
        if depth_usd >= self.min_depth_usd * 5:
            return DepthQuality.EXCELLENT
        if depth_usd >= self.min_depth_usd * 2:
            return DepthQuality.GOOD
        if depth_usd >= self.min_depth_usd:
            return DepthQuality.FAIR
        if depth_usd >= self.min_depth_usd * 0.5:
            return DepthQuality.POOR
        return DepthQuality.CRITICAL
