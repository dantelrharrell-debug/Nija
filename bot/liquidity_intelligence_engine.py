"""
Liquidity Intelligence Engine
==============================
Scores and gates trades based on real-time market liquidity:

  * Bid-ask spread monitoring (raw + EMA-smoothed)
  * Volume profile analysis (relative-volume vs. rolling baseline)
  * Order-book depth estimation via recent trade data
  * Thin-market detection with configurable thresholds
  * Per-symbol liquidity score (0-100) with GOOD/FAIR/POOR/AVOID grades
  * Portfolio-level aggregate for regime gating

Public API
----------
  engine = get_liquidity_intelligence_engine()
  result = engine.score_symbol(symbol, current_spread_pct, volume_usd, df)
  ok     = engine.approve_entry(symbol, min_grade="FAIR")
  report = engine.get_portfolio_liquidity()
"""

from __future__ import annotations

import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PANDAS_AVAILABLE = False
    pd = None  # type: ignore

logger = logging.getLogger("nija.liquidity_intelligence")

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------

# Spread thresholds (as a fraction of price, e.g. 0.001 = 0.1%)
SPREAD_GOOD = 0.0010      # ≤ 0.10% → excellent
SPREAD_FAIR = 0.0030      # ≤ 0.30% → acceptable
SPREAD_POOR = 0.0060      # ≤ 0.60% → marginal
# > SPREAD_POOR → AVOID

# Relative-volume thresholds (ratio vs. rolling 24-period baseline)
RVOL_STRONG  = 1.5   # ≥ 150% of baseline → strong liquidity
RVOL_NORMAL  = 0.75  # ≥ 75% → normal
RVOL_THIN    = 0.35  # ≥ 35% → thin (liquidity-poor)
# < RVOL_THIN → AVOID

# Minimum absolute volume (USD) to consider a market tradable
MIN_VOLUME_USD = 25_000.0

# Rolling window (bars) for volume baseline
VOLUME_BASELINE_WINDOW = 24

# Liquidity score weights
WEIGHT_SPREAD = 0.45

# EMA alpha for smoothing spread observations
SPREAD_EMA_ALPHA = 0.20
WEIGHT_RVOL   = 0.35
WEIGHT_DEPTH  = 0.20

GRADE_THRESHOLDS: List[Tuple[float, str]] = [
    (75.0, "GOOD"),
    (50.0, "FAIR"),
    (25.0, "POOR"),
    (0.0,  "AVOID"),
]


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class LiquiditySnapshot:
    """Point-in-time liquidity assessment for a single symbol."""
    symbol: str
    score: float                  # 0-100 composite
    grade: str                    # GOOD | FAIR | POOR | AVOID
    spread_pct: float             # current spread as fraction of price
    spread_ema: float             # EMA-smoothed spread
    relative_volume: float        # vs. rolling baseline (ratio)
    volume_usd: float             # absolute volume in USD
    depth_score: float            # 0-100 estimated depth score
    approved: bool
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": round(self.score, 2),
            "grade": self.grade,
            "spread_pct": round(self.spread_pct * 100, 4),
            "spread_ema_pct": round(self.spread_ema * 100, 4),
            "relative_volume": round(self.relative_volume, 3),
            "volume_usd": round(self.volume_usd, 2),
            "depth_score": round(self.depth_score, 2),
            "approved": self.approved,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


@dataclass
class PortfolioLiquidityReport:
    """Aggregate liquidity health across all tracked symbols."""
    avg_score: float
    avg_spread_pct: float
    pct_good: float
    pct_fair: float
    pct_poor: float
    pct_avoid: float
    thin_markets: List[str]
    symbol_count: int
    portfolio_grade: str
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "avg_score": round(self.avg_score, 2),
            "avg_spread_pct": round(self.avg_spread_pct * 100, 4),
            "pct_good": round(self.pct_good, 2),
            "pct_fair": round(self.pct_fair, 2),
            "pct_poor": round(self.pct_poor, 2),
            "pct_avoid": round(self.pct_avoid, 2),
            "thin_markets": self.thin_markets,
            "symbol_count": self.symbol_count,
            "portfolio_grade": self.portfolio_grade,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------

class LiquidityIntelligenceEngine:
    """
    Per-symbol liquidity scorer with rolling volume baseline and EMA-spread
    tracking.  All public methods are thread-safe.
    """

    def __init__(
        self,
        min_volume_usd: float = MIN_VOLUME_USD,
        volume_baseline_window: int = VOLUME_BASELINE_WINDOW,
        spread_ema_alpha: float = SPREAD_EMA_ALPHA,
    ) -> None:
        self._min_volume_usd = max(1.0, min_volume_usd)
        self._volume_window   = max(2, volume_baseline_window)
        self._ema_alpha       = max(0.01, min(0.99, spread_ema_alpha))

        self._lock = threading.RLock()

        # Per-symbol rolling volume history
        self._volume_history: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=self._volume_window)
        )
        # Per-symbol EMA-smoothed spread
        self._spread_ema: Dict[str, float] = {}
        # Latest snapshot per symbol
        self._snapshots: Dict[str, LiquiditySnapshot] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_symbol(
        self,
        symbol: str,
        spread_pct: float,
        volume_usd: float,
        df: Optional[Any] = None,  # Optional OHLCV DataFrame for depth estimation
    ) -> LiquiditySnapshot:
        """
        Compute a composite liquidity score for *symbol*.

        Parameters
        ----------
        symbol      : Trading pair identifier (e.g. "BTC-USD")
        spread_pct  : Current bid-ask spread as a fraction of mid-price
                      (e.g. 0.001 for 0.10%).
        volume_usd  : Most-recent bar's traded volume in USD.
        df          : Optional OHLCV DataFrame used for depth estimation.

        Returns
        -------
        LiquiditySnapshot
        """
        with self._lock:
            spread_pct = max(0.0, spread_pct)
            volume_usd = max(0.0, volume_usd)

            # --- Update EMA-smoothed spread ---
            prev_ema = self._spread_ema.get(symbol, spread_pct)
            spread_ema = prev_ema + self._ema_alpha * (spread_pct - prev_ema)
            self._spread_ema[symbol] = spread_ema

            # --- Update volume history & compute relative volume ---
            hist = self._volume_history[symbol]
            hist.append(volume_usd)
            baseline = float(np.mean(hist)) if len(hist) > 1 else volume_usd
            relative_volume = volume_usd / baseline if baseline > 0 else 1.0

            # --- Spread score (0-100) ---
            spread_score = self._spread_to_score(spread_ema)

            # --- Relative-volume score (0-100) ---
            rvol_score = self._rvol_to_score(relative_volume, volume_usd)

            # --- Depth score from DataFrame (0-100) ---
            depth_score = self._estimate_depth_score(df, volume_usd)

            # --- Composite score ---
            composite = (
                WEIGHT_SPREAD * spread_score
                + WEIGHT_RVOL  * rvol_score
                + WEIGHT_DEPTH * depth_score
            )
            composite = max(0.0, min(100.0, composite))

            grade = self._score_to_grade(composite)
            approved = grade in ("GOOD", "FAIR")
            reason = self._build_reason(
                grade, spread_ema, relative_volume, volume_usd, composite
            )

            snapshot = LiquiditySnapshot(
                symbol=symbol,
                score=composite,
                grade=grade,
                spread_pct=spread_pct,
                spread_ema=spread_ema,
                relative_volume=relative_volume,
                volume_usd=volume_usd,
                depth_score=depth_score,
                approved=approved,
                reason=reason,
            )
            self._snapshots[symbol] = snapshot
            return snapshot

    def approve_entry(
        self,
        symbol: str,
        min_grade: str = "FAIR",
    ) -> bool:
        """
        Return True if the most-recent liquidity snapshot for *symbol* is at or
        above *min_grade*.  Returns True if the symbol has never been scored
        (no data to block on).
        """
        with self._lock:
            snap = self._snapshots.get(symbol)
            if snap is None:
                return True  # benefit of the doubt
            grade_order = {"GOOD": 3, "FAIR": 2, "POOR": 1, "AVOID": 0}
            return grade_order.get(snap.grade, 0) >= grade_order.get(min_grade, 0)

    def get_snapshot(self, symbol: str) -> Optional[LiquiditySnapshot]:
        """Return the latest cached snapshot for *symbol*, or None."""
        with self._lock:
            return self._snapshots.get(symbol)

    def get_portfolio_liquidity(self) -> PortfolioLiquidityReport:
        """Aggregate liquidity health across all tracked symbols."""
        with self._lock:
            snaps = list(self._snapshots.values())

        if not snaps:
            return PortfolioLiquidityReport(
                avg_score=100.0,
                avg_spread_pct=0.0,
                pct_good=100.0,
                pct_fair=0.0,
                pct_poor=0.0,
                pct_avoid=0.0,
                thin_markets=[],
                symbol_count=0,
                portfolio_grade="GOOD",
            )

        n = len(snaps)
        grade_counts: Dict[str, int] = defaultdict(int)
        for s in snaps:
            grade_counts[s.grade] += 1

        avg_score     = float(np.mean([s.score       for s in snaps]))
        avg_spread    = float(np.mean([s.spread_ema  for s in snaps]))
        thin_markets  = [s.symbol for s in snaps if s.grade in ("POOR", "AVOID")]

        portfolio_grade = self._score_to_grade(avg_score)

        return PortfolioLiquidityReport(
            avg_score=avg_score,
            avg_spread_pct=avg_spread,
            pct_good=100.0  * grade_counts["GOOD"]  / n,
            pct_fair=100.0  * grade_counts["FAIR"]  / n,
            pct_poor=100.0  * grade_counts["POOR"]  / n,
            pct_avoid=100.0 * grade_counts["AVOID"] / n,
            thin_markets=thin_markets,
            symbol_count=n,
            portfolio_grade=portfolio_grade,
        )

    def reset_symbol(self, symbol: str) -> None:
        """Clear all cached data for *symbol* (useful for testing)."""
        with self._lock:
            self._volume_history.pop(symbol, None)
            self._spread_ema.pop(symbol, None)
            self._snapshots.pop(symbol, None)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _spread_to_score(spread: float) -> float:
        """Convert spread fraction → 0-100 score (higher spread = lower score)."""
        if spread <= SPREAD_GOOD:
            return 100.0
        if spread <= SPREAD_FAIR:
            # Linear interpolation between GOOD and FAIR
            t = (spread - SPREAD_GOOD) / (SPREAD_FAIR - SPREAD_GOOD)
            return 100.0 - t * 25.0   # 100 → 75
        if spread <= SPREAD_POOR:
            t = (spread - SPREAD_FAIR) / (SPREAD_POOR - SPREAD_FAIR)
            return 75.0 - t * 25.0    # 75 → 50
        # > SPREAD_POOR: exponential decay toward 0
        excess = (spread - SPREAD_POOR) / SPREAD_POOR
        return max(0.0, 50.0 * math.exp(-2.0 * excess))

    @staticmethod
    def _rvol_to_score(relative_volume: float, volume_usd: float) -> float:
        """Convert relative-volume + absolute volume → 0-100 score."""
        if volume_usd < MIN_VOLUME_USD * 0.1:
            return 0.0  # virtually no volume

        # Relative-volume component (0-100)
        if relative_volume >= RVOL_STRONG:
            rv_score = 100.0
        elif relative_volume >= RVOL_NORMAL:
            t = (relative_volume - RVOL_NORMAL) / (RVOL_STRONG - RVOL_NORMAL)
            rv_score = 75.0 + t * 25.0
        elif relative_volume >= RVOL_THIN:
            t = (relative_volume - RVOL_THIN) / (RVOL_NORMAL - RVOL_THIN)
            rv_score = 25.0 + t * 50.0
        else:
            rv_score = max(0.0, 25.0 * relative_volume / RVOL_THIN)

        # Absolute-volume penalty when below minimum threshold
        if volume_usd < MIN_VOLUME_USD:
            penalty = volume_usd / MIN_VOLUME_USD
            rv_score *= penalty

        return rv_score

    @staticmethod
    def _estimate_depth_score(df: Optional[Any], volume_usd: float) -> float:
        """
        Estimate order-book depth from OHLCV data.
        Uses the ratio of close-to-close range vs. high-low range as a
        proxy for intra-bar liquidity.
        Falls back to volume-based heuristic when DataFrame unavailable.
        """
        if df is None or not _PANDAS_AVAILABLE:
            # Simple heuristic: log-scale of volume_usd mapped to 0-100
            if volume_usd <= 0:
                return 0.0
            score = min(100.0, 20.0 * math.log10(max(1.0, volume_usd / 1_000.0)))
            return max(0.0, score)

        try:
            required = {"high", "low", "close", "volume"}
            cols = {c.lower() for c in df.columns}
            if not required.issubset(cols):
                raise ValueError("Missing OHLCV columns")

            df_tail = df.tail(DEPTH_ESTIMATION_WINDOW)
            hl_range  = (df_tail["high"] - df_tail["low"]).replace(0, float("nan"))
            body      = (df_tail["close"] - df_tail["close"].shift(1)).abs()
            ratio     = (body / hl_range).clip(0, 1)
            # High ratio → price moves fill most of the bar → thinner book
            avg_ratio = float(ratio.mean())
            depth_from_candles = max(0.0, 100.0 * (1.0 - avg_ratio))

            # Blend with volume heuristic
            vol_score = min(100.0, 20.0 * math.log10(max(1.0, volume_usd / 1_000.0)))
            return 0.6 * depth_from_candles + 0.4 * vol_score

        except Exception as exc:
            logger.debug("[LiquidityEngine] Depth estimation failed: %s", exc)
            return 50.0  # neutral fallback

    @staticmethod
    def _score_to_grade(score: float) -> str:
        for threshold, grade in GRADE_THRESHOLDS:
            if score >= threshold:
                return grade
        return "AVOID"

    @staticmethod
    def _build_reason(
        grade: str,
        spread_ema: float,
        relative_volume: float,
        volume_usd: float,
        score: float,
    ) -> str:
        parts = [f"score={score:.1f} grade={grade}"]
        parts.append(f"spread_ema={spread_ema * 100:.3f}%")
        parts.append(f"rvol={relative_volume:.2f}x")
        if volume_usd < MIN_VOLUME_USD:
            parts.append(f"⚠️ vol=${volume_usd:,.0f}<min(${MIN_VOLUME_USD:,.0f})")
        if grade == "AVOID":
            parts.append("🚫 entry blocked")
        elif grade == "POOR":
            parts.append("⚠️ entry marginal")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[LiquidityIntelligenceEngine] = None
_engine_lock = threading.Lock()


def get_liquidity_intelligence_engine(
    min_volume_usd: float = MIN_VOLUME_USD,
    volume_baseline_window: int = VOLUME_BASELINE_WINDOW,
    spread_ema_alpha: float = SPREAD_EMA_ALPHA,
) -> LiquidityIntelligenceEngine:
    """
    Return the process-wide LiquidityIntelligenceEngine singleton.

    Constructor arguments are applied only on first creation.
    """
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = LiquidityIntelligenceEngine(
                min_volume_usd=min_volume_usd,
                volume_baseline_window=volume_baseline_window,
                spread_ema_alpha=spread_ema_alpha,
            )
            logger.info(
                "✅ LiquidityIntelligenceEngine initialised "
                "(min_vol=$%s, window=%d, ema_α=%.2f)",
                f"{min_volume_usd:,.0f}",
                volume_baseline_window,
                spread_ema_alpha,
            )
    return _engine_instance
