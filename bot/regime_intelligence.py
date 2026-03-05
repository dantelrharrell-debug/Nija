"""
NIJA Regime Intelligence Module
==================================

Advanced market regime intelligence that extends the basic RegimeDetector with:
1. Multi-timeframe regime consensus (prevents false signals)
2. Regime transition detection and confidence scoring
3. Historical regime performance lookup
4. Adaptive parameter recommendations per regime
5. Regime shift alerts and logging

Works alongside the existing `market_regime_detector.py` but adds a higher-level
intelligence layer that can be consumed by the trading strategy and risk manager.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import json
import logging
from collections import deque
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.regime_intelligence")

# ---------------------------------------------------------------------------
# Regime definitions
# ---------------------------------------------------------------------------

class Regime(Enum):
    """Comprehensive market regime classification."""
    BULL_TRENDING = "bull_trending"    # Strong uptrend, ADX > 25, price above MAs
    BEAR_TRENDING = "bear_trending"    # Strong downtrend, ADX > 25, price below MAs
    RANGING = "ranging"                # Low ADX, price oscillating in range
    VOLATILE = "volatile"              # High ATR, choppy price action
    BREAKOUT = "breakout"              # Regime transition — handle with care
    UNKNOWN = "unknown"                # Insufficient data


class RegimeConfidence(Enum):
    """Confidence level in the current regime classification."""
    VERY_HIGH = "very_high"   # >= 80%
    HIGH = "high"             # 60-80%
    MEDIUM = "medium"         # 40-60%
    LOW = "low"               # < 40%


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RegimeSnapshot:
    """Point-in-time regime classification."""
    timestamp: datetime
    regime: Regime
    confidence: float           # 0.0 – 1.0
    adx: float
    atr_pct: float              # ATR as % of price
    price_vs_sma20: float       # price / SMA20 ratio
    price_vs_sma50: float       # price / SMA50 ratio
    source: str                 # 'primary' | 'consensus'


@dataclass
class RegimeTransition:
    """Recorded regime transition event."""
    timestamp: datetime
    from_regime: Regime
    to_regime: Regime
    confidence: float
    duration_hours: float       # how long previous regime lasted


@dataclass
class RegimeParameters:
    """Adaptive trading parameters recommended for a regime."""
    regime: str
    min_entry_score: int
    position_size_multiplier: float
    trailing_stop_atr_multiplier: float
    take_profit_multiplier: float
    long_rsi_min: float
    long_rsi_max: float
    short_rsi_min: float
    short_rsi_max: float
    max_open_positions: int
    notes: str


# ---------------------------------------------------------------------------
# Regime Intelligence Engine
# ---------------------------------------------------------------------------

class RegimeIntelligenceEngine:
    """
    Advanced regime intelligence layer.

    Responsibilities:
    1. Classify the current regime with confidence scoring
    2. Track regime history and detect transitions
    3. Surface performance data per regime
    4. Recommend adaptive trading parameters
    5. Alert on significant regime changes
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "regime_intelligence_state.json"
    HISTORY_MAXLEN = 500

    # Regime parameter table — tuned for NIJA's dual-RSI strategy
    REGIME_PARAMS: Dict[str, RegimeParameters] = {
        Regime.BULL_TRENDING.value: RegimeParameters(
            regime=Regime.BULL_TRENDING.value,
            min_entry_score=3,
            position_size_multiplier=1.25,
            trailing_stop_atr_multiplier=1.5,
            take_profit_multiplier=1.5,
            long_rsi_min=50.0,
            long_rsi_max=72.0,
            short_rsi_min=65.0,
            short_rsi_max=80.0,
            max_open_positions=6,
            notes="Strong uptrend — increase exposure, widen targets.",
        ),
        Regime.BEAR_TRENDING.value: RegimeParameters(
            regime=Regime.BEAR_TRENDING.value,
            min_entry_score=4,
            position_size_multiplier=0.75,
            trailing_stop_atr_multiplier=1.2,
            take_profit_multiplier=0.9,
            long_rsi_min=35.0,
            long_rsi_max=55.0,
            short_rsi_min=55.0,
            short_rsi_max=75.0,
            max_open_positions=3,
            notes="Downtrend — reduce longs, tighten risk.",
        ),
        Regime.RANGING.value: RegimeParameters(
            regime=Regime.RANGING.value,
            min_entry_score=4,
            position_size_multiplier=0.80,
            trailing_stop_atr_multiplier=1.0,
            take_profit_multiplier=0.80,
            long_rsi_min=20.0,
            long_rsi_max=38.0,
            short_rsi_min=62.0,
            short_rsi_max=80.0,
            max_open_positions=4,
            notes="Mean-reversion mode — buy oversold, sell overbought.",
        ),
        Regime.VOLATILE.value: RegimeParameters(
            regime=Regime.VOLATILE.value,
            min_entry_score=4,
            position_size_multiplier=0.65,
            trailing_stop_atr_multiplier=2.0,
            take_profit_multiplier=1.0,
            long_rsi_min=60.0,
            long_rsi_max=72.0,
            short_rsi_min=60.0,
            short_rsi_max=72.0,
            max_open_positions=2,
            notes="Choppy — only high-conviction signals, widen stops.",
        ),
        Regime.BREAKOUT.value: RegimeParameters(
            regime=Regime.BREAKOUT.value,
            min_entry_score=5,
            position_size_multiplier=0.50,
            trailing_stop_atr_multiplier=2.5,
            take_profit_multiplier=2.0,
            long_rsi_min=55.0,
            long_rsi_max=75.0,
            short_rsi_min=55.0,
            short_rsi_max=75.0,
            max_open_positions=2,
            notes="Regime transition — ultra-selective, expect whipsaws.",
        ),
        Regime.UNKNOWN.value: RegimeParameters(
            regime=Regime.UNKNOWN.value,
            min_entry_score=5,
            position_size_multiplier=0.50,
            trailing_stop_atr_multiplier=1.5,
            take_profit_multiplier=1.0,
            long_rsi_min=40.0,
            long_rsi_max=65.0,
            short_rsi_min=55.0,
            short_rsi_max=75.0,
            max_open_positions=2,
            notes="Unknown conditions — reduce size, wait for clarity.",
        ),
    }

    def __init__(self):
        self._history: Deque[RegimeSnapshot] = deque(maxlen=self.HISTORY_MAXLEN)
        self._transitions: List[RegimeTransition] = []
        self._regime_trade_stats: Dict[str, Dict[str, float]] = {}  # regime → performance stats
        self._current_regime: Optional[RegimeSnapshot] = None
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()
        logger.info("🌐 Regime Intelligence Engine initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        adx: float,
        atr_pct: float,
        price: float,
        sma20: Optional[float] = None,
        sma50: Optional[float] = None,
    ) -> RegimeSnapshot:
        """
        Classify the current market regime from technical indicators.

        Args:
            adx: ADX (Average Directional Index) value.
            atr_pct: ATR as a fraction of current price (e.g. 0.03 = 3%).
            price: Current asset price.
            sma20: 20-period simple moving average (optional, for trend direction).
            sma50: 50-period simple moving average (optional, for trend direction).

        Returns:
            RegimeSnapshot with regime classification and confidence.
        """
        price_vs_sma20 = (price / sma20) if sma20 and sma20 > 0 else 1.0
        price_vs_sma50 = (price / sma50) if sma50 and sma50 > 0 else 1.0

        regime, confidence = self._classify_regime(adx, atr_pct, price_vs_sma20, price_vs_sma50)

        snapshot = RegimeSnapshot(
            timestamp=datetime.now(),
            regime=regime,
            confidence=confidence,
            adx=round(adx, 2),
            atr_pct=round(atr_pct, 4),
            price_vs_sma20=round(price_vs_sma20, 4),
            price_vs_sma50=round(price_vs_sma50, 4),
            source="primary",
        )

        # Detect transitions
        if self._current_regime and self._current_regime.regime != regime:
            self._record_transition(self._current_regime, snapshot)

        self._current_regime = snapshot
        self._history.append(snapshot)
        self._save_state()

        logger.debug(
            "🌐 Regime: %s (confidence=%.0f%%, ADX=%.1f, ATR%%=%.2f%%)",
            regime.value, confidence * 100, adx, atr_pct * 100,
        )
        return snapshot

    def get_current_regime(self) -> Optional[RegimeSnapshot]:
        """Return the most recently classified regime snapshot."""
        return self._current_regime

    def get_consensus_regime(self, lookback: int = 5) -> Tuple[Regime, float]:
        """
        Get the consensus regime from the last N snapshots (reduces noise).

        Args:
            lookback: Number of recent snapshots to use.

        Returns:
            Tuple of (consensus_regime, average_confidence).
        """
        recent = list(self._history)[-lookback:]
        if not recent:
            return Regime.UNKNOWN, 0.0

        regime_votes: Dict[str, float] = {}
        for snap in recent:
            key = snap.regime.value
            regime_votes[key] = regime_votes.get(key, 0.0) + snap.confidence

        best = max(regime_votes, key=regime_votes.get)  # type: ignore[arg-type]
        avg_confidence = sum(s.confidence for s in recent) / len(recent)

        return Regime(best), round(avg_confidence, 4)

    def get_regime_parameters(self, regime: Optional[Regime] = None) -> RegimeParameters:
        """
        Get adaptive trading parameters for a regime.

        Args:
            regime: Target regime (default: current regime).

        Returns:
            RegimeParameters dataclass.
        """
        if regime is None and self._current_regime:
            regime = self._current_regime.regime
        elif regime is None:
            regime = Regime.UNKNOWN

        return self.REGIME_PARAMS.get(regime.value, self.REGIME_PARAMS[Regime.UNKNOWN.value])

    def get_regime_confidence_level(self, confidence: float) -> RegimeConfidence:
        """Convert a float confidence to a RegimeConfidence enum."""
        if confidence >= 0.80:
            return RegimeConfidence.VERY_HIGH
        elif confidence >= 0.60:
            return RegimeConfidence.HIGH
        elif confidence >= 0.40:
            return RegimeConfidence.MEDIUM
        else:
            return RegimeConfidence.LOW

    def record_trade_outcome(self, regime: str, pnl: float, is_win: bool) -> None:
        """
        Record a trade outcome for a regime to build historical performance stats.

        Args:
            regime: Regime label at time of trade.
            pnl: Net P&L of the trade.
            is_win: True if the trade was profitable.
        """
        if regime not in self._regime_trade_stats:
            self._regime_trade_stats[regime] = {
                "trades": 0,
                "wins": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
            }
        stats = self._regime_trade_stats[regime]
        stats["trades"] += 1
        if is_win:
            stats["wins"] += 1
        stats["total_pnl"] += pnl
        stats["win_rate"] = stats["wins"] / stats["trades"]
        stats["avg_pnl"] = stats["total_pnl"] / stats["trades"]
        self._save_state()

    def get_regime_performance(self) -> Dict[str, Dict[str, float]]:
        """Return historical performance stats keyed by regime."""
        return dict(self._regime_trade_stats)

    def get_recent_transitions(self, n: int = 10) -> List[RegimeTransition]:
        """Return the last N regime transitions."""
        return self._transitions[-n:]

    def generate_report(self) -> str:
        """Generate a human-readable regime intelligence report."""
        current = self._current_regime
        consensus_regime, consensus_conf = self.get_consensus_regime()
        params = self.get_regime_parameters()
        conf_level = self.get_regime_confidence_level(current.confidence if current else 0.0)

        lines = [
            "",
            "=" * 80,
            "🌐  NIJA REGIME INTELLIGENCE REPORT",
            "=" * 80,
        ]

        if current:
            lines.extend([
                f"  Current Regime:     {current.regime.value.upper()}",
                f"  Confidence:         {current.confidence * 100:.1f}% ({conf_level.value})",
                f"  ADX:                {current.adx:.1f}",
                f"  ATR %:              {current.atr_pct * 100:.2f}%",
                f"  Price/SMA20:        {current.price_vs_sma20:.4f}",
                f"  Price/SMA50:        {current.price_vs_sma50:.4f}",
                "",
                f"  Consensus (last 5): {consensus_regime.value.upper()} ({consensus_conf * 100:.1f}%)",
            ])
        else:
            lines.append("  No regime classified yet.")

        lines.extend([
            "",
            "  ADAPTIVE PARAMETERS",
            f"    Min Entry Score:    {params.min_entry_score}",
            f"    Position Mult:      {params.position_size_multiplier:.2f}x",
            f"    Trailing Stop:      {params.trailing_stop_atr_multiplier:.1f}x ATR",
            f"    Take Profit:        {params.take_profit_multiplier:.1f}x base",
            f"    Max Positions:      {params.max_open_positions}",
            f"    Long RSI:           {params.long_rsi_min:.0f}–{params.long_rsi_max:.0f}",
            f"    Short RSI:          {params.short_rsi_min:.0f}–{params.short_rsi_max:.0f}",
            f"    Notes:              {params.notes}",
        ])

        # Performance per regime
        if self._regime_trade_stats:
            lines.extend(["", "  REGIME PERFORMANCE HISTORY"])
            for regime_label, stats in self._regime_trade_stats.items():
                lines.append(
                    f"    {regime_label:<20} trades={int(stats['trades']):<5} "
                    f"win%={stats['win_rate']*100:.1f}%  avg_pnl=${stats['avg_pnl']:.2f}"
                )

        # Recent transitions
        recent_t = self.get_recent_transitions(5)
        if recent_t:
            lines.extend(["", "  RECENT REGIME TRANSITIONS"])
            for t in reversed(recent_t):
                lines.append(
                    f"    {t.timestamp.strftime('%Y-%m-%d %H:%M')}  "
                    f"{t.from_regime.value} → {t.to_regime.value}  "
                    f"(lasted {t.duration_hours:.1f}h, conf={t.confidence:.0%})"
                )

        lines.append("=" * 80)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Classification internals
    # ------------------------------------------------------------------

    def _classify_regime(
        self,
        adx: float,
        atr_pct: float,
        price_vs_sma20: float,
        price_vs_sma50: float,
    ) -> Tuple[Regime, float]:
        """Classify regime and return (Regime, confidence 0.0–1.0)."""

        # --- VOLATILE: high ATR regardless of ADX ---
        if atr_pct > 0.05:  # > 5% ATR
            conf = min(1.0, 0.50 + (atr_pct - 0.05) * 10)
            return Regime.VOLATILE, round(conf, 4)

        # --- TRENDING ---
        if adx >= 25:
            # Direction from moving averages
            bullish = (price_vs_sma20 > 1.0 and price_vs_sma50 > 1.0)
            bearish = (price_vs_sma20 < 1.0 and price_vs_sma50 < 1.0)

            conf = min(1.0, 0.50 + (adx - 25) * 0.02)

            if bullish:
                return Regime.BULL_TRENDING, round(conf, 4)
            elif bearish:
                return Regime.BEAR_TRENDING, round(conf, 4)
            else:
                # ADX trending but direction mixed → breakout
                return Regime.BREAKOUT, round(conf * 0.8, 4)

        # --- RANGING: low ADX, low ATR ---
        if adx < 20 and atr_pct < 0.03:
            conf = min(1.0, 0.40 + (20 - adx) * 0.03)
            return Regime.RANGING, round(conf, 4)

        # --- Intermediate zone → VOLATILE / BREAKOUT ---
        if adx >= 20:
            return Regime.BREAKOUT, 0.45

        return Regime.VOLATILE, 0.40

    def _record_transition(
        self, previous: RegimeSnapshot, current: RegimeSnapshot
    ) -> None:
        """Record a regime transition event."""
        duration_hours = (current.timestamp - previous.timestamp).total_seconds() / 3600.0

        transition = RegimeTransition(
            timestamp=current.timestamp,
            from_regime=previous.regime,
            to_regime=current.regime,
            confidence=current.confidence,
            duration_hours=round(duration_hours, 2),
        )
        self._transitions.append(transition)

        # Keep only last 200 transitions
        if len(self._transitions) > 200:
            self._transitions = self._transitions[-200:]

        logger.info(
            "🔄 Regime transition: %s → %s (conf=%.0f%%, previous lasted %.1fh)",
            previous.regime.value,
            current.regime.value,
            current.confidence * 100,
            duration_hours,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)

            # Load history
            for item in data.get("history", []):
                try:
                    snap = RegimeSnapshot(
                        timestamp=datetime.fromisoformat(item["timestamp"]),
                        regime=Regime(item["regime"]),
                        confidence=item["confidence"],
                        adx=item["adx"],
                        atr_pct=item["atr_pct"],
                        price_vs_sma20=item.get("price_vs_sma20", 1.0),
                        price_vs_sma50=item.get("price_vs_sma50", 1.0),
                        source=item.get("source", "primary"),
                    )
                    self._history.append(snap)
                except (KeyError, ValueError) as exc:
                    logger.warning("Skipping malformed regime snapshot: %s", exc)

            if self._history:
                self._current_regime = list(self._history)[-1]

            # Load transitions
            for item in data.get("transitions", []):
                try:
                    t = RegimeTransition(
                        timestamp=datetime.fromisoformat(item["timestamp"]),
                        from_regime=Regime(item["from_regime"]),
                        to_regime=Regime(item["to_regime"]),
                        confidence=item["confidence"],
                        duration_hours=item["duration_hours"],
                    )
                    self._transitions.append(t)
                except (KeyError, ValueError) as exc:
                    logger.warning("Skipping malformed transition: %s", exc)

            # Load trade stats
            self._regime_trade_stats = data.get("regime_trade_stats", {})

            logger.info("✅ Loaded regime intelligence state — %d snapshots", len(self._history))
        except Exception as exc:
            logger.warning("Could not load regime intelligence state: %s", exc)

    def _save_state(self) -> None:
        try:
            history_list = [
                {
                    "timestamp": s.timestamp.isoformat(),
                    "regime": s.regime.value,
                    "confidence": s.confidence,
                    "adx": s.adx,
                    "atr_pct": s.atr_pct,
                    "price_vs_sma20": s.price_vs_sma20,
                    "price_vs_sma50": s.price_vs_sma50,
                    "source": s.source,
                }
                for s in self._history
            ]
            transition_list = [
                {
                    "timestamp": t.timestamp.isoformat(),
                    "from_regime": t.from_regime.value,
                    "to_regime": t.to_regime.value,
                    "confidence": t.confidence,
                    "duration_hours": t.duration_hours,
                }
                for t in self._transitions
            ]
            payload = {
                "history": history_list,
                "transitions": transition_list,
                "regime_trade_stats": self._regime_trade_stats,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.STATE_FILE, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save regime intelligence state: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: Optional[RegimeIntelligenceEngine] = None


def get_regime_intelligence_engine() -> RegimeIntelligenceEngine:
    """Return the module-level singleton RegimeIntelligenceEngine."""
    global _engine
    if _engine is None:
        _engine = RegimeIntelligenceEngine()
    return _engine


if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    engine = get_regime_intelligence_engine()

    # Simulate regime classifications
    print("Simulating regime classifications...\n")
    scenarios = [
        (30.0, 0.02, 42000, 41500, 41000),   # Bull trending
        (28.0, 0.02, 39000, 40000, 40500),   # Bear trending
        (12.0, 0.01, 40500, 40400, 40200),   # Ranging
        (22.0, 0.06, 41000, 40800, 40000),   # Volatile
    ]

    for adx, atr_pct, price, sma20, sma50 in scenarios:
        snap = engine.classify(adx, atr_pct, price, sma20, sma50)
        params = engine.get_regime_parameters(snap.regime)
        print(f"Regime: {snap.regime.value:<20} conf={snap.confidence:.0%}  min_score={params.min_entry_score}")
        engine.record_trade_outcome(snap.regime.value, pnl=random.gauss(5, 15), is_win=random.random() > 0.45)

    print(engine.generate_report())
