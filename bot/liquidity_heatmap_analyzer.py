"""
NIJA Liquidity Heatmap Analyzer
=================================

Builds a price-level liquidity map from order-book data (or volume-profile
proxies) and produces actionable metrics:

* **Liquidity Heatmap** — cumulative bid/ask depth in configurable price
  buckets around the current mid price.
* **Support / Resistance Zones** — price levels with the heaviest order-book
  concentration, likely to act as S/R.
* **Entry Quality Score** (0–100) — how favourable the liquidity landscape is
  for immediate order execution.
* **Market-Impact Estimate** — estimated slippage percentage for a given
  order size based on available depth.
* **Bid/Ask Imbalance** — order-flow pressure (positive = buy-side heavy).

Usage
-----
::

    from bot.liquidity_heatmap_analyzer import get_liquidity_heatmap_analyzer

    analyzer = get_liquidity_heatmap_analyzer()

    # With a live order book
    order_book = {
        "bids": [[29900.0, 1.5], [29850.0, 3.2], ...],  # [price, size]
        "asks": [[30000.0, 0.8], [30050.0, 2.1], ...],
    }
    result = analyzer.analyze(
        symbol="BTC-USD",
        bid=29900.0,
        ask=30000.0,
        order_book=order_book,
        trade_size_usd=5000.0,
    )

    # Without an order book (volume-profile proxy via OHLCV df)
    result = analyzer.analyze(
        symbol="ETH-USD",
        bid=1800.0,
        ask=1801.0,
        df=df,
        trade_size_usd=2000.0,
    )

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.liquidity_heatmap")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BUCKET_COUNT: int = 20          # price buckets in the heatmap
DEFAULT_DEPTH_BAND_PCT: float = 0.02    # ±2 % around mid price
MIN_DEPTH_USD: float = 10_000.0         # minimum acceptable total depth
MAX_SPREAD_PCT: float = 0.005           # 0.5 % — above this is "wide"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class LiquidityBucket:
    """One price bucket in the heatmap."""
    price_low: float
    price_high: float
    bid_depth_usd: float = 0.0
    ask_depth_usd: float = 0.0

    @property
    def mid_price(self) -> float:
        return (self.price_low + self.price_high) / 2.0

    @property
    def total_depth_usd(self) -> float:
        return self.bid_depth_usd + self.ask_depth_usd

    @property
    def imbalance(self) -> float:
        """Positive → more bids; negative → more asks."""
        total = self.bid_depth_usd + self.ask_depth_usd
        if total <= 0:
            return 0.0
        return (self.bid_depth_usd - self.ask_depth_usd) / total

    def to_dict(self) -> Dict:
        return {
            "price_low": round(self.price_low, 6),
            "price_high": round(self.price_high, 6),
            "mid_price": round(self.mid_price, 6),
            "bid_depth_usd": round(self.bid_depth_usd, 2),
            "ask_depth_usd": round(self.ask_depth_usd, 2),
            "total_depth_usd": round(self.total_depth_usd, 2),
            "imbalance": round(self.imbalance, 4),
        }


@dataclass
class SupportResistanceZone:
    """A price level identified as a key S/R zone."""
    price: float
    side: str                       # "support" or "resistance"
    depth_usd: float                # USD depth at this level
    strength: float                 # 0–1 relative to max depth bucket

    def to_dict(self) -> Dict:
        return {
            "price": round(self.price, 6),
            "side": self.side,
            "depth_usd": round(self.depth_usd, 2),
            "strength": round(self.strength, 4),
        }


@dataclass
class LiquidityHeatmapResult:
    """Full analysis result from the heatmap analyzer."""
    symbol: str
    bid: float
    ask: float
    spread_pct: float
    mid_price: float

    # Heatmap
    buckets: List[LiquidityBucket] = field(default_factory=list)

    # Aggregates
    total_bid_depth_usd: float = 0.0
    total_ask_depth_usd: float = 0.0
    imbalance: float = 0.0          # +1 = all bids, -1 = all asks

    # S/R zones (top 3 support, top 3 resistance)
    support_zones: List[SupportResistanceZone] = field(default_factory=list)
    resistance_zones: List[SupportResistanceZone] = field(default_factory=list)

    # Scores
    entry_quality_score: float = 0.0   # 0–100
    liquidity_rating: str = "unknown"  # excellent / good / fair / poor

    # Market impact
    estimated_slippage_pct: float = 0.0
    max_safe_order_usd: float = 0.0

    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "bid": round(self.bid, 6),
            "ask": round(self.ask, 6),
            "mid_price": round(self.mid_price, 6),
            "spread_pct": round(self.spread_pct, 6),
            "heatmap": [b.to_dict() for b in self.buckets],
            "aggregates": {
                "total_bid_depth_usd": round(self.total_bid_depth_usd, 2),
                "total_ask_depth_usd": round(self.total_ask_depth_usd, 2),
                "imbalance": round(self.imbalance, 4),
            },
            "support_zones": [z.to_dict() for z in self.support_zones],
            "resistance_zones": [z.to_dict() for z in self.resistance_zones],
            "entry_quality_score": round(self.entry_quality_score, 2),
            "liquidity_rating": self.liquidity_rating,
            "market_impact": {
                "estimated_slippage_pct": round(self.estimated_slippage_pct, 6),
                "max_safe_order_usd": round(self.max_safe_order_usd, 2),
            },
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class LiquidityHeatmapAnalyzer:
    """
    Builds a price-level liquidity heatmap and scores execution quality.

    Parameters
    ----------
    depth_band_pct:
        Half-width of the price band to analyse, as a fraction of mid price
        (default: 0.02 = ±2 %).
    bucket_count:
        Number of price buckets to divide the band into (default: 20).
    min_depth_usd:
        Minimum acceptable total depth in USD (default: 10 000).
    max_impact_pct:
        Maximum safe market-impact fraction (default: 0.10 = 10 % of depth).
    """

    def __init__(
        self,
        depth_band_pct: float = DEFAULT_DEPTH_BAND_PCT,
        bucket_count: int = DEFAULT_BUCKET_COUNT,
        min_depth_usd: float = MIN_DEPTH_USD,
        max_impact_pct: float = 0.10,
    ):
        self.depth_band_pct = depth_band_pct
        self.bucket_count = bucket_count
        self.min_depth_usd = min_depth_usd
        self.max_impact_pct = max_impact_pct
        logger.info(
            f"LiquidityHeatmapAnalyzer ready "
            f"(band=±{depth_band_pct*100:.1f}%, buckets={bucket_count})"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        symbol: str,
        bid: float,
        ask: float,
        order_book: Optional[Dict] = None,
        df: Optional[pd.DataFrame] = None,
        trade_size_usd: float = 0.0,
        volume_24h_usd: float = 0.0,
    ) -> Dict:
        """
        Run the full liquidity analysis.

        Parameters
        ----------
        symbol:
            Trading pair label (e.g. ``"BTC-USD"``).
        bid:
            Best bid price.
        ask:
            Best ask price.
        order_book:
            Optional dict with ``"bids"`` and ``"asks"`` lists of
            ``[price, size]`` pairs.
        df:
            Optional OHLCV DataFrame used as a volume-profile proxy when no
            order book is available.
        trade_size_usd:
            Proposed order size in USD.  Used for slippage estimation.
        volume_24h_usd:
            24-hour traded volume in USD.  Used for context scoring.

        Returns
        -------
        dict  (see ``LiquidityHeatmapResult.to_dict()``)
        """
        mid = (bid + ask) / 2.0
        spread_pct = ((ask - bid) / mid) if mid > 0 else 0.0

        result = LiquidityHeatmapResult(
            symbol=symbol,
            bid=bid,
            ask=ask,
            mid_price=mid,
            spread_pct=spread_pct,
        )

        # Build heatmap buckets
        price_lo = mid * (1.0 - self.depth_band_pct)
        price_hi = mid * (1.0 + self.depth_band_pct)
        bucket_size = (price_hi - price_lo) / self.bucket_count

        buckets: List[LiquidityBucket] = [
            LiquidityBucket(
                price_low=price_lo + i * bucket_size,
                price_high=price_lo + (i + 1) * bucket_size,
            )
            for i in range(self.bucket_count)
        ]

        if order_book:
            self._fill_from_order_book(buckets, order_book, mid)
        elif df is not None and not df.empty:
            self._fill_from_volume_profile(buckets, df, mid)
        else:
            # No data — return minimal result
            result.liquidity_rating = "unknown"
            result.entry_quality_score = 50.0
            return result.to_dict()

        result.buckets = buckets
        result.total_bid_depth_usd = sum(b.bid_depth_usd for b in buckets)
        result.total_ask_depth_usd = sum(b.ask_depth_usd for b in buckets)
        total_depth = result.total_bid_depth_usd + result.total_ask_depth_usd
        if total_depth > 0:
            result.imbalance = (
                (result.total_bid_depth_usd - result.total_ask_depth_usd) / total_depth
            )

        # S/R zones
        result.support_zones, result.resistance_zones = self._find_sr_zones(
            buckets, mid, n=3
        )

        # Scores
        result.entry_quality_score = self._score_entry_quality(
            result, trade_size_usd, volume_24h_usd
        )
        result.liquidity_rating = self._classify_quality(result.entry_quality_score)

        # Market impact
        result.estimated_slippage_pct = self._estimate_slippage(
            buckets, trade_size_usd, mid
        )
        result.max_safe_order_usd = min(
            result.total_bid_depth_usd, result.total_ask_depth_usd
        ) * self.max_impact_pct

        logger.debug(
            f"[Heatmap] {symbol} | score={result.entry_quality_score:.1f} "
            f"| rating={result.liquidity_rating} "
            f"| slippage≈{result.estimated_slippage_pct*100:.3f}%"
        )
        return result.to_dict()

    # ------------------------------------------------------------------
    # Heatmap population
    # ------------------------------------------------------------------

    def _fill_from_order_book(
        self,
        buckets: List[LiquidityBucket],
        order_book: Dict,
        mid: float,
    ) -> None:
        """Map order-book levels into price buckets."""
        for level in order_book.get("bids", []):
            price, size = self._parse_level(level)
            usd_value = price * size
            bucket = self._find_bucket(buckets, price)
            if bucket is not None:
                bucket.bid_depth_usd += usd_value

        for level in order_book.get("asks", []):
            price, size = self._parse_level(level)
            usd_value = price * size
            bucket = self._find_bucket(buckets, price)
            if bucket is not None:
                bucket.ask_depth_usd += usd_value

    def _fill_from_volume_profile(
        self,
        buckets: List[LiquidityBucket],
        df: pd.DataFrame,
        mid: float,
    ) -> None:
        """
        Build a synthetic depth proxy from OHLCV data.

        Each bar's volume is assigned proportionally to the price range it
        covers, split 50/50 between bid and ask buckets at the bar's close.
        """
        if "volume" not in df.columns or "close" not in df.columns:
            return

        for _, row in df.tail(100).iterrows():
            close_px = float(row.get("close", mid))
            vol = float(row.get("volume", 0))
            if vol <= 0 or close_px <= 0:
                continue
            usd_val = close_px * vol / 100.0   # normalise to avoid inflated values
            bucket = self._find_bucket(buckets, close_px)
            if bucket is not None:
                bucket.bid_depth_usd += usd_val * 0.5
                bucket.ask_depth_usd += usd_val * 0.5

    # ------------------------------------------------------------------
    # Support / Resistance identification
    # ------------------------------------------------------------------

    def _find_sr_zones(
        self,
        buckets: List[LiquidityBucket],
        mid: float,
        n: int = 3,
    ) -> Tuple[List[SupportResistanceZone], List[SupportResistanceZone]]:
        """Return the top-n support and resistance zones."""
        max_depth = max((b.total_depth_usd for b in buckets), default=1.0) or 1.0

        # Buckets below mid → potential support; above → resistance
        below = sorted(
            [b for b in buckets if b.mid_price < mid],
            key=lambda b: b.bid_depth_usd,
            reverse=True,
        )
        above = sorted(
            [b for b in buckets if b.mid_price >= mid],
            key=lambda b: b.ask_depth_usd,
            reverse=True,
        )

        support_zones = [
            SupportResistanceZone(
                price=b.mid_price,
                side="support",
                depth_usd=b.bid_depth_usd,
                strength=b.bid_depth_usd / max_depth,
            )
            for b in below[:n]
        ]

        resistance_zones = [
            SupportResistanceZone(
                price=b.mid_price,
                side="resistance",
                depth_usd=b.ask_depth_usd,
                strength=b.ask_depth_usd / max_depth,
            )
            for b in above[:n]
        ]

        return support_zones, resistance_zones

    # ------------------------------------------------------------------
    # Entry quality scoring (0–100)
    # ------------------------------------------------------------------

    def _score_entry_quality(
        self,
        result: LiquidityHeatmapResult,
        trade_size_usd: float,
        volume_24h_usd: float,
    ) -> float:
        score = 0.0
        total_depth = result.total_bid_depth_usd + result.total_ask_depth_usd

        # 1. Depth adequacy (0–40 pts)
        depth_ratio = total_depth / self.min_depth_usd
        depth_pts = min(depth_ratio * 20.0, 40.0)
        score += depth_pts

        # 2. Spread quality (0–25 pts)
        if result.spread_pct <= 0.0005:          # ≤0.05 % — very tight
            score += 25.0
        elif result.spread_pct <= 0.001:
            score += 20.0
        elif result.spread_pct <= 0.002:
            score += 15.0
        elif result.spread_pct <= MAX_SPREAD_PCT:
            score += 8.0
        # else: wide spread → 0 pts

        # 3. Order-flow imbalance (0–15 pts) — mild imbalance is fine
        abs_imb = abs(result.imbalance)
        if abs_imb < 0.1:
            score += 15.0                        # balanced book
        elif abs_imb < 0.25:
            score += 10.0
        elif abs_imb < 0.5:
            score += 5.0
        # extreme imbalance → 0 pts

        # 4. Trade-size impact (0–20 pts)
        if trade_size_usd > 0 and total_depth > 0:
            impact_pct = trade_size_usd / total_depth
            if impact_pct <= 0.01:              # < 1 % of depth
                score += 20.0
            elif impact_pct <= 0.03:
                score += 15.0
            elif impact_pct <= 0.06:
                score += 8.0
            elif impact_pct <= 0.10:
                score += 3.0
            # else > 10 % of depth → 0 pts
        else:
            score += 10.0                       # neutral when size unknown

        return round(min(score, 100.0), 2)

    # ------------------------------------------------------------------
    # Market-impact estimation
    # ------------------------------------------------------------------

    def _estimate_slippage(
        self,
        buckets: List[LiquidityBucket],
        trade_size_usd: float,
        mid: float,
    ) -> float:
        """
        Walk the simulated order book to estimate average fill price and
        return slippage as a fraction of mid price.
        """
        if trade_size_usd <= 0 or mid <= 0:
            return 0.0

        # Use ask-side buckets (worst-case for a buy)
        ask_buckets = sorted(
            [b for b in buckets if b.mid_price >= mid and b.ask_depth_usd > 0],
            key=lambda b: b.mid_price,
        )

        remaining = trade_size_usd
        weighted_price_sum = 0.0
        filled = 0.0

        for b in ask_buckets:
            available = b.ask_depth_usd
            take = min(remaining, available)
            weighted_price_sum += b.mid_price * take
            filled += take
            remaining -= take
            if remaining <= 0:
                break

        if filled <= 0:
            return 0.0

        avg_fill_price = weighted_price_sum / filled
        slippage = abs(avg_fill_price - mid) / mid
        return round(slippage, 6)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_level(level) -> Tuple[float, float]:
        """Parse ``[price, size]`` or ``(price, size)`` into two floats."""
        try:
            price = float(level[0])
            size = float(level[1])
            return price, size
        except (TypeError, IndexError, ValueError):
            return 0.0, 0.0

    @staticmethod
    def _find_bucket(
        buckets: List[LiquidityBucket], price: float
    ) -> Optional[LiquidityBucket]:
        for b in buckets:
            if b.price_low <= price < b.price_high:
                return b
        return None

    @staticmethod
    def _classify_quality(score: float) -> str:
        if score >= 80:
            return "excellent"
        if score >= 60:
            return "good"
        if score >= 40:
            return "fair"
        return "poor"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_heatmap_analyzer: Optional[LiquidityHeatmapAnalyzer] = None


def get_liquidity_heatmap_analyzer(
    depth_band_pct: float = DEFAULT_DEPTH_BAND_PCT,
    bucket_count: int = DEFAULT_BUCKET_COUNT,
) -> LiquidityHeatmapAnalyzer:
    """
    Return (or create) the module-level ``LiquidityHeatmapAnalyzer`` singleton.

    Parameters
    ----------
    depth_band_pct / bucket_count:
        Passed only on the *first* call.
    """
    global _heatmap_analyzer
    if _heatmap_analyzer is None:
        _heatmap_analyzer = LiquidityHeatmapAnalyzer(
            depth_band_pct=depth_band_pct,
            bucket_count=bucket_count,
        )
    return _heatmap_analyzer
