"""
NIJA Market Regime Detector
============================

Detects market regimes to optimize trading strategy parameters.

Legacy class ``RegimeDetector`` (3 regimes — TRENDING/RANGING/VOLATILE)
is preserved for backward compatibility.

New ``MarketRegimeDetectionEngine`` provides full 7-regime detection:
1. STRONG_TREND       — ADX > 30, clear directional momentum
2. WEAK_TREND         — ADX 20-30, developing trend
3. RANGING            — ADX < 20, sideways consolidation
4. EXPANSION          — Volatility breakout, volume surge
5. MEAN_REVERSION     — Pullback/reversal setup
6. VOLATILITY_EXPLOSION — Crisis / panic mode
7. CONSOLIDATION      — Low-volatility compression

Features
--------
- Multi-dimensional classification: ADX, RSI, ATR, Bollinger Bands, volume
- Regime persistence to prevent rapid flipping
- Confidence scoring (0–1)
- Strategy recommendations per regime
- Module-level singleton via ``get_market_regime_detector()``

Author: NIJA Trading Systems
Version: 2.0
Date: March 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
import logging

logger = logging.getLogger("nija.regime")


class MarketRegime(Enum):
    """Market regime types"""
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"


class RegimeDetector:
    """
    Detect market regime based on technical indicators

    Regime Classification:
    - TRENDING: ADX > 25, clear directional movement
    - RANGING: ADX < 20, price oscillating in range
    - VOLATILE: ADX 20-25, high ATR/price ratio (>3%)
    """

    def __init__(self, config: Dict = None):
        """
        Initialize regime detector

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

        # Regime thresholds
        self.trending_adx_min = self.config.get('trending_adx_min', 25)
        self.ranging_adx_max = self.config.get('ranging_adx_max', 20)
        self.volatile_atr_threshold = self.config.get('volatile_atr_threshold', 0.03)  # 3% ATR/price

        # Regime-specific parameters
        self.regime_params = {
            MarketRegime.TRENDING: {
                'min_entry_score': 3,  # Require 3/5 conditions
                'position_size_multiplier': 1.2,  # Increase position size by 20%
                'trailing_stop_distance': 1.5,  # Wider trailing stop (1.5x ATR)
                'take_profit_multiplier': 1.5,  # Higher profit targets
                # ADAPTIVE RSI RANGES (MOMENTUM-OPTIMIZED FOR TRENDING MARKETS)
                # Trending markets require RSI > 50 to confirm bullish momentum before entry
                # This ensures entries are made only when trend momentum is clearly established
                'long_rsi_min': 50,   # RSI > 50 required: confirms bullish trend momentum
                'long_rsi_max': 70,   # Upper bound to avoid extreme overbought entries
                'short_rsi_min': 45,  # Short entries when RSI is approaching neutral zone from above
                'short_rsi_max': 70,  # Allow slightly lower entries for momentum
            },
            MarketRegime.RANGING: {
                'min_entry_score': 4,  # Require 4/5 conditions (more selective)
                'position_size_multiplier': 0.8,  # Reduce position size by 20%
                'trailing_stop_distance': 1.0,  # Tighter trailing stop (1.0x ATR)
                'take_profit_multiplier': 0.8,  # Lower profit targets (take profits faster)
                # ADAPTIVE RSI RANGES (MEAN-REVERSION OPTIMIZED FOR RANGING MARKETS)
                # In ranging markets, true "buy low, sell high" mean reversion works best
                # Buy extreme oversold, sell extreme overbought
                'long_rsi_min': 20,   # Buy at extreme oversold levels
                'long_rsi_max': 35,   # NARROWED: Only buy very low (was 50)
                'short_rsi_min': 65,  # NARROWED: Only sell very high (was 50)
                'short_rsi_max': 80,  # Sell at extreme overbought levels
            },
            MarketRegime.VOLATILE: {
                'min_entry_score': 4,  # Require 4/5 conditions (more selective)
                'position_size_multiplier': 0.7,  # Reduce position size by 30%
                'trailing_stop_distance': 2.0,  # Wider trailing stop (2.0x ATR)
                'take_profit_multiplier': 1.0,  # Normal profit targets
                # ADAPTIVE RSI RANGES (MAX ALPHA UPGRADE)
                # Volatile markets require RSI > 60 for higher conviction before entry
                # In choppy/volatile markets, only strong momentum signals (RSI > 60) are reliable
                'long_rsi_min': 60,   # RSI > 60 required: high conviction momentum in volatile markets
                'long_rsi_max': 70,   # Conservative upper bound to avoid extreme overbought entries
                'short_rsi_min': 60,  # Narrow range for quality entries
                'short_rsi_max': 70,  # Conservative to avoid whipsaws
            }
        }

        logger.info("MarketRegimeDetector initialized")

    def detect_regime(self, df: pd.DataFrame, indicators: Dict) -> Tuple[MarketRegime, Dict]:
        """
        Detect current market regime

        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators

        Returns:
            Tuple of (regime, metrics)
        """
        # Get current indicator values
        adx = float(indicators.get('adx', pd.Series([0])).iloc[-1])
        atr = float(indicators.get('atr', pd.Series([0])).iloc[-1])
        current_price = float(df['close'].iloc[-1])

        # Calculate ATR as percentage of price
        atr_pct = (atr / current_price) if current_price > 0 else 0

        # Calculate price volatility (std dev of last 20 closes)
        price_volatility = df['close'].iloc[-20:].std() / df['close'].iloc[-20:].mean() if len(df) >= 20 else 0

        # Detect regime
        regime = self._classify_regime(adx, atr_pct, price_volatility)

        # Calculate additional metrics
        metrics = {
            'adx': adx,
            'atr': atr,
            'atr_pct': atr_pct,
            'price_volatility': price_volatility,
            'regime': regime.value,
            'confidence': self._calculate_regime_confidence(adx, atr_pct, regime)
        }

        logger.debug(f"Regime detected: {regime.value} (ADX={adx:.1f}, ATR%={atr_pct*100:.2f}%, Volatility={price_volatility*100:.2f}%)")

        return regime, metrics

    def _classify_regime(self, adx: float, atr_pct: float, price_volatility: float) -> MarketRegime:
        """
        Classify market regime based on indicators

        Args:
            adx: ADX value
            atr_pct: ATR as percentage of price
            price_volatility: Price volatility (std/mean)

        Returns:
            MarketRegime enum
        """
        # TRENDING: Strong directional movement
        if adx >= self.trending_adx_min:
            return MarketRegime.TRENDING

        # RANGING: Low ADX, consolidating
        elif adx < self.ranging_adx_max and atr_pct < self.volatile_atr_threshold:
            return MarketRegime.RANGING

        # VOLATILE: Medium ADX with high volatility
        else:
            return MarketRegime.VOLATILE

    def _calculate_regime_confidence(self, adx: float, atr_pct: float, regime: MarketRegime) -> float:
        """
        Calculate confidence in regime classification (0.0 to 1.0)

        Args:
            adx: ADX value
            atr_pct: ATR as percentage of price
            regime: Detected regime

        Returns:
            Confidence score 0.0-1.0
        """
        if regime == MarketRegime.TRENDING:
            # Confidence increases with ADX above threshold
            if adx >= 40:
                return 1.0
            elif adx >= 30:
                return 0.8
            elif adx >= 25:
                return 0.6
            else:
                return 0.4

        elif regime == MarketRegime.RANGING:
            # Confidence increases as ADX decreases
            if adx <= 10:
                return 1.0
            elif adx <= 15:
                return 0.8
            elif adx <= 20:
                return 0.6
            else:
                return 0.4

        else:  # VOLATILE
            # Confidence based on how far we are from clear regimes
            trending_distance = abs(adx - self.trending_adx_min)
            ranging_distance = abs(adx - self.ranging_adx_max)
            min_distance = min(trending_distance, ranging_distance)

            # Higher confidence when we're clearly between regimes
            if min_distance >= 5:
                return 0.8
            elif min_distance >= 3:
                return 0.6
            else:
                return 0.4

    def get_regime_parameters(self, regime: MarketRegime) -> Dict:
        """
        Get trading parameters for a given regime

        Args:
            regime: Market regime

        Returns:
            Dictionary of regime-specific parameters
        """
        return self.regime_params.get(regime, self.regime_params[MarketRegime.VOLATILE])

    def adjust_entry_score_threshold(self, regime: MarketRegime, base_score: int) -> Tuple[bool, int]:
        """
        Adjust entry score threshold based on regime

        Args:
            regime: Current market regime
            base_score: Calculated entry score (0-5)

        Returns:
            Tuple of (should_enter, min_required_score)
        """
        params = self.get_regime_parameters(regime)
        min_score = params['min_entry_score']

        should_enter = base_score >= min_score

        return should_enter, min_score

    def adjust_position_size(self, regime: MarketRegime, base_position_size: float) -> float:
        """
        Adjust position size based on regime

        Args:
            regime: Current market regime
            base_position_size: Base position size in USD

        Returns:
            Adjusted position size
        """
        params = self.get_regime_parameters(regime)
        multiplier = params['position_size_multiplier']

        adjusted_size = base_position_size * multiplier

        logger.debug(f"Position size adjusted for {regime.value}: ${base_position_size:.2f} -> ${adjusted_size:.2f} ({multiplier}x)")

        return adjusted_size

    def get_trailing_stop_distance(self, regime: MarketRegime, atr: float) -> float:
        """
        Get trailing stop distance based on regime

        Args:
            regime: Current market regime
            atr: Average True Range

        Returns:
            Trailing stop distance
        """
        params = self.get_regime_parameters(regime)
        multiplier = params['trailing_stop_distance']

        return atr * multiplier

    def adjust_take_profit_levels(self, regime: MarketRegime, base_tp_levels: Dict) -> Dict:
        """
        Adjust take profit levels based on regime

        Args:
            regime: Current market regime
            base_tp_levels: Base take profit levels dictionary

        Returns:
            Adjusted take profit levels
        """
        params = self.get_regime_parameters(regime)
        multiplier = params['take_profit_multiplier']

        adjusted_tp = {}
        for level, price in base_tp_levels.items():
            if isinstance(price, (int, float)):
                # Adjust numeric TP levels
                adjusted_tp[level] = price * (1 + (multiplier - 1))
            else:
                adjusted_tp[level] = price

        return adjusted_tp

    def get_adaptive_rsi_ranges(self, regime: MarketRegime, adx: float = None) -> Dict[str, float]:
        """
        Get adaptive RSI ranges based on market regime and trend strength (MAX ALPHA UPGRADE)

        This method dynamically adjusts RSI entry ranges based on market conditions:
        - TRENDING: RSI > 50 required for longs (50-70 range) to confirm bullish momentum
        - RANGING: Wider ranges (20-50 long, 50-80 short) for more opportunities
        - VOLATILE: RSI > 60 required for longs (60-70 range) for high conviction in choppy markets

        Optional ADX fine-tuning:
        - Strong trend (ADX > 30): Use slightly tighter ranges for even higher conviction
        - Weak trend (ADX < 20): Use slightly wider ranges for more opportunities

        Args:
            regime: Current market regime
            adx: Optional ADX value for fine-tuning (if provided)

        Returns:
            Dictionary with keys: 'long_min', 'long_max', 'short_min', 'short_max'

        Example:
            >>> ranges = detector.get_adaptive_rsi_ranges(MarketRegime.TRENDING, adx=35)
            >>> # Returns: {'long_min': 25, 'long_max': 43, 'short_min': 57, 'short_max': 75}
            >>> # Slightly tighter than base (45->43, 55->57) due to strong ADX
        """
        params = self.get_regime_parameters(regime)

        # Base ranges from regime configuration
        long_min = params['long_rsi_min']
        long_max = params['long_rsi_max']
        short_min = params['short_rsi_min']
        short_max = params['short_rsi_max']

        # Optional ADX fine-tuning for TRENDING regime
        if adx is not None and regime == MarketRegime.TRENDING:
            if adx >= 35:
                # Very strong trend: Tighten ranges by 2 points for ultra-high conviction
                # This captures only the best entries in powerful trends
                long_max = max(long_min + 5, long_max - 2)  # Don't go too narrow
                short_min = min(short_max - 5, short_min + 2)  # Don't go too narrow
                logger.debug(f"ADX {adx:.1f} - Very strong trend: Tightened RSI ranges for max conviction")
            elif adx >= 30:
                # Strong trend: Tighten ranges by 1 point for higher conviction
                long_max = max(long_min + 5, long_max - 1)
                short_min = min(short_max - 5, short_min + 1)
                logger.debug(f"ADX {adx:.1f} - Strong trend: Slightly tightened RSI ranges")

        # Validation: Ensure ranges don't overlap and maintain minimum width
        min_gap = 5  # Minimum gap between long_max and short_min (neutral zone)
        min_width = 10  # Minimum range width for each direction

        # Ensure long range has minimum width
        if long_max - long_min < min_width:
            long_max = long_min + min_width

        # Ensure short range has minimum width
        if short_max - short_min < min_width:
            short_min = short_max - min_width

        # Ensure minimum gap (neutral zone) between ranges
        if short_min - long_max < min_gap:
            # Adjust to create neutral zone
            midpoint = (long_max + short_min) / 2
            long_max = midpoint - min_gap / 2
            short_min = midpoint + min_gap / 2
            logger.warning(f"RSI ranges adjusted to maintain {min_gap}-point neutral zone")

        ranges = {
            'long_min': long_min,
            'long_max': long_max,
            'short_min': short_min,
            'short_max': short_max
        }

        logger.debug(
            f"Adaptive RSI ranges ({regime.value}): "
            f"Long [{long_min:.0f}-{long_max:.0f}], "
            f"Short [{short_min:.0f}-{short_max:.0f}], "
            f"Neutral [{long_max:.0f}-{short_min:.0f}]"
        )

        return ranges


# Global instance (legacy)
regime_detector = RegimeDetector()


# ---------------------------------------------------------------------------
# Enhanced 7-regime Detection Engine
# ---------------------------------------------------------------------------

class RegimeType(Enum):
    """Full 7-class market regime taxonomy."""
    STRONG_TREND = "strong_trend"
    WEAK_TREND = "weak_trend"
    RANGING = "ranging"
    EXPANSION = "expansion"
    MEAN_REVERSION = "mean_reversion"
    VOLATILITY_EXPLOSION = "volatility_explosion"
    CONSOLIDATION = "consolidation"


class RegimeStrategy(Enum):
    """Recommended strategy per regime."""
    TREND_FOLLOWING = "trend_following"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    SCALPING = "scalping"
    DEFENSIVE = "defensive"
    MOMENTUM = "momentum"


@dataclass
class RegimeSnapshot:
    """Point-in-time regime classification."""
    regime: RegimeType
    confidence: float                          # 0.0 – 1.0
    probabilities: Dict[str, float]            # regime.value → probability
    features: Dict[str, float]                 # raw indicator values used
    recommended_strategy: RegimeStrategy = RegimeStrategy.TREND_FOLLOWING
    strategy_confidence: float = 0.5
    trend_strength: float = 0.0               # 0–1 normalised ADX
    volatility_level: float = 0.0             # 0–1 normalised ATR percentile
    momentum_score: float = 0.0               # absolute MACD histogram
    volume_profile: str = "normal"            # low / normal / high / extreme
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "regime": self.regime.value,
            "confidence": round(self.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
            "features": {k: round(v, 4) for k, v in self.features.items()},
            "recommended_strategy": self.recommended_strategy.value,
            "strategy_confidence": round(self.strategy_confidence, 4),
            "metrics": {
                "trend_strength": round(self.trend_strength, 4),
                "volatility_level": round(self.volatility_level, 4),
                "momentum_score": round(self.momentum_score, 4),
                "volume_profile": self.volume_profile,
            },
            "timestamp": self.timestamp.isoformat(),
        }


# Regime → recommended strategy mapping
_REGIME_STRATEGY_MAP: Dict[RegimeType, RegimeStrategy] = {
    RegimeType.STRONG_TREND: RegimeStrategy.TREND_FOLLOWING,
    RegimeType.WEAK_TREND: RegimeStrategy.MOMENTUM,
    RegimeType.RANGING: RegimeStrategy.MEAN_REVERSION,
    RegimeType.EXPANSION: RegimeStrategy.BREAKOUT,
    RegimeType.MEAN_REVERSION: RegimeStrategy.MEAN_REVERSION,
    RegimeType.VOLATILITY_EXPLOSION: RegimeStrategy.DEFENSIVE,
    RegimeType.CONSOLIDATION: RegimeStrategy.SCALPING,
}

# Position-size multipliers per regime
_REGIME_SIZE_MULTIPLIER: Dict[RegimeType, float] = {
    RegimeType.STRONG_TREND: 1.25,
    RegimeType.WEAK_TREND: 1.0,
    RegimeType.RANGING: 0.80,
    RegimeType.EXPANSION: 1.10,
    RegimeType.MEAN_REVERSION: 0.90,
    RegimeType.VOLATILITY_EXPLOSION: 0.35,
    RegimeType.CONSOLIDATION: 0.70,
}


class MarketRegimeDetectionEngine:
    """
    Multi-dimensional 7-regime market detector.

    Uses ADX, RSI, ATR (Bollinger-band-like expansion), volume ratio, and
    MACD histogram to score each of the 7 regime buckets and pick the
    highest-scoring one.

    Regime persistence (``persistence_bars``) prevents rapid regime flipping
    by requiring a higher confidence margin to switch away from the
    currently-active regime.

    Example
    -------
    ::

        from bot.market_regime_detector import get_market_regime_detector

        detector = get_market_regime_detector()
        snapshot = detector.detect(df, indicators)
        print(snapshot.regime.value, snapshot.confidence)
    """

    def __init__(self, config: Optional[Dict] = None):
        cfg = config or {}
        self.persistence_bars: int = cfg.get("persistence_bars", 5)
        self.min_confidence: float = cfg.get("min_confidence", 0.55)
        self.switch_margin: float = cfg.get("switch_margin", 0.10)
        self.history_size: int = cfg.get("history_size", 200)

        self._current: Optional[RegimeSnapshot] = None
        self._history: deque = deque(maxlen=self.history_size)
        self._bars_in_regime: int = 0

        logger.info("MarketRegimeDetectionEngine v2.0 initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, df: pd.DataFrame, indicators: Dict) -> RegimeSnapshot:
        """
        Classify the current market regime.

        Parameters
        ----------
        df:
            OHLCV DataFrame.  Must contain ``close``, ``high``, ``low``,
            ``volume`` columns.  At least 30 rows recommended.
        indicators:
            Pre-computed indicator dict.  Recognised keys: ``adx``, ``rsi_9``,
            ``rsi_14``, ``rsi``, ``atr``, ``macd_histogram``, ``macd_hist``,
            ``ema_9``, ``ema_21``, ``ema_50``.

        Returns
        -------
        RegimeSnapshot
        """
        features = self._extract_features(df, indicators)
        scores = self._score_regimes(features)

        # Normalise scores to probabilities
        total = sum(scores.values()) or 1.0
        probs = {k.value: v / total for k, v in scores.items()}

        # Best regime candidate
        best_regime = max(scores, key=scores.get)
        best_conf = scores[best_regime] / total

        # Persistence: only switch if margin is sufficient
        if self._current is not None and best_regime != self._current.regime:
            current_score = scores.get(self._current.regime, 0.0) / total
            if best_conf - current_score < self.switch_margin:
                best_regime = self._current.regime
                best_conf = current_score
                self._bars_in_regime += 1
            else:
                self._bars_in_regime = 0
        else:
            self._bars_in_regime += 1

        strategy = _REGIME_STRATEGY_MAP.get(best_regime, RegimeStrategy.TREND_FOLLOWING)

        snapshot = RegimeSnapshot(
            regime=best_regime,
            confidence=round(best_conf, 4),
            probabilities=probs,
            features=features,
            recommended_strategy=strategy,
            strategy_confidence=self._strategy_confidence(best_conf),
            trend_strength=min(features.get("adx", 0) / 50.0, 1.0),
            volatility_level=features.get("atr_pct", 0),
            momentum_score=abs(features.get("macd_hist", 0)),
            volume_profile=self._volume_label(features.get("volume_ratio", 1.0)),
        )
        self._current = snapshot
        self._history.append(snapshot)
        return snapshot

    def get_size_multiplier(self, regime: Optional[RegimeType] = None) -> float:
        """Return position-size multiplier for *regime* (defaults to current)."""
        r = regime or (self._current.regime if self._current else RegimeType.RANGING)
        return _REGIME_SIZE_MULTIPLIER.get(r, 1.0)

    def get_current(self) -> Optional[RegimeSnapshot]:
        """Return the most-recent regime snapshot, or None if never called."""
        return self._current

    def get_history(self, n: int = 10) -> List[RegimeSnapshot]:
        """Return the last *n* snapshots (most-recent last)."""
        return list(self._history)[-n:]

    def regime_summary(self) -> Dict:
        """Compact dict summary of current state (safe for JSON serialisation)."""
        if self._current is None:
            return {"regime": "unknown", "confidence": 0.0, "bars_in_regime": 0}
        return {
            **self._current.to_dict(),
            "bars_in_regime": self._bars_in_regime,
            "size_multiplier": self.get_size_multiplier(),
        }

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    def _extract_features(self, df: pd.DataFrame, indicators: Dict) -> Dict[str, float]:
        close = df["close"].iloc[-1] if len(df) else 1.0

        def _last(key, alt_key=None, default=0.0) -> float:
            v = indicators.get(key)
            if v is None and alt_key:
                v = indicators.get(alt_key)
            if v is None:
                return default
            if hasattr(v, "iloc"):
                return float(v.iloc[-1])
            return float(v)

        adx = _last("adx", default=15.0)
        rsi = _last("rsi_14", "rsi", default=50.0)
        rsi_9 = _last("rsi_9", default=rsi)
        atr = _last("atr", default=0.0)
        macd_hist = _last("macd_histogram", "macd_hist", default=0.0)

        atr_pct = (atr / close) if close > 0 else 0.0

        # ATR expansion: ratio vs 14-bar rolling mean of ATR
        atr_series = indicators.get("atr")
        if atr_series is not None and hasattr(atr_series, "rolling") and len(atr_series) >= 14:
            atr_mean = float(atr_series.rolling(14).mean().iloc[-1])
            atr_expansion = (atr / atr_mean) if atr_mean > 0 else 1.0
        else:
            atr_expansion = 1.0

        # Volume ratio (current vs 20-bar mean)
        if "volume" in df.columns and len(df) >= 20:
            vol = float(df["volume"].iloc[-1])
            vol_mean = float(df["volume"].iloc[-20:].mean())
            volume_ratio = (vol / vol_mean) if vol_mean > 0 else 1.0
        else:
            volume_ratio = 1.0

        # Price volatility (std/mean over last 20 closes)
        if len(df) >= 20:
            closes = df["close"].iloc[-20:]
            price_vol = float(closes.std() / closes.mean()) if closes.mean() > 0 else 0.0
        else:
            price_vol = 0.0

        # EMA alignment
        ema_9 = _last("ema_9", default=close)
        ema_21 = _last("ema_21", default=close)
        ema_50 = _last("ema_50", default=close)
        ema_aligned_bull = ema_9 > ema_21 > ema_50
        ema_aligned_bear = ema_9 < ema_21 < ema_50

        return {
            "adx": adx,
            "rsi": rsi,
            "rsi_9": rsi_9,
            "atr": atr,
            "atr_pct": atr_pct,
            "atr_expansion": atr_expansion,
            "macd_hist": macd_hist,
            "volume_ratio": volume_ratio,
            "price_volatility": price_vol,
            "ema_aligned_bull": 1.0 if ema_aligned_bull else 0.0,
            "ema_aligned_bear": 1.0 if ema_aligned_bear else 0.0,
        }

    # ------------------------------------------------------------------
    # Regime scoring (rule-based)
    # ------------------------------------------------------------------

    def _score_regimes(self, f: Dict[str, float]) -> Dict[RegimeType, float]:
        scores: Dict[RegimeType, float] = {r: 0.0 for r in RegimeType}
        adx = f["adx"]
        rsi = f["rsi"]
        rsi_9 = f["rsi_9"]
        atr_exp = f["atr_expansion"]
        vol_ratio = f["volume_ratio"]
        macd = f["macd_hist"]
        price_vol = f["price_volatility"]

        # --- STRONG_TREND ---
        if adx >= 30:
            scores[RegimeType.STRONG_TREND] += 1.0
        if adx >= 40:
            scores[RegimeType.STRONG_TREND] += 0.5
        if f["ema_aligned_bull"] or f["ema_aligned_bear"]:
            scores[RegimeType.STRONG_TREND] += 0.4

        # --- WEAK_TREND ---
        if 20 <= adx < 30:
            scores[RegimeType.WEAK_TREND] += 1.0
        if abs(macd) > 0:
            scores[RegimeType.WEAK_TREND] += 0.3

        # --- RANGING ---
        if adx < 20:
            scores[RegimeType.RANGING] += 1.0
        if adx < 15:
            scores[RegimeType.RANGING] += 0.5
        if 40 <= rsi <= 60:
            scores[RegimeType.RANGING] += 0.3

        # --- EXPANSION (breakout) ---
        if atr_exp > 1.5 and vol_ratio > 1.3:
            scores[RegimeType.EXPANSION] += 1.0
        elif atr_exp > 1.2:
            scores[RegimeType.EXPANSION] += 0.5
        if vol_ratio > 2.0:
            scores[RegimeType.EXPANSION] += 0.4

        # --- MEAN_REVERSION (pullback setup) ---
        if rsi_9 < 35 or rsi_9 > 65:
            scores[RegimeType.MEAN_REVERSION] += 0.7
        if adx < 25 and (rsi < 40 or rsi > 60):
            scores[RegimeType.MEAN_REVERSION] += 0.5
        if atr_exp < 0.9 and (rsi < 35 or rsi > 65):
            scores[RegimeType.MEAN_REVERSION] += 0.3

        # --- VOLATILITY_EXPLOSION (crisis) ---
        if atr_exp > 2.5:
            scores[RegimeType.VOLATILITY_EXPLOSION] += 1.0
        if atr_exp > 2.0 and vol_ratio > 2.0:
            scores[RegimeType.VOLATILITY_EXPLOSION] += 0.8
        if price_vol > 0.05:
            scores[RegimeType.VOLATILITY_EXPLOSION] += 0.5

        # --- CONSOLIDATION (low-vol compression) ---
        if atr_exp < 0.7 and adx < 20:
            scores[RegimeType.CONSOLIDATION] += 1.0
        if price_vol < 0.01:
            scores[RegimeType.CONSOLIDATION] += 0.5
        if vol_ratio < 0.6:
            scores[RegimeType.CONSOLIDATION] += 0.3

        return scores

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strategy_confidence(regime_confidence: float) -> float:
        if regime_confidence >= 0.8:
            return 0.9
        if regime_confidence >= 0.65:
            return 0.7
        if regime_confidence >= 0.5:
            return 0.5
        return 0.3

    @staticmethod
    def _volume_label(ratio: float) -> str:
        if ratio >= 3.0:
            return "extreme"
        if ratio >= 1.5:
            return "high"
        if ratio >= 0.7:
            return "normal"
        return "low"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_detection_engine: Optional[MarketRegimeDetectionEngine] = None


def get_market_regime_detector(config: Optional[Dict] = None) -> MarketRegimeDetectionEngine:
    """
    Return (or create) the module-level ``MarketRegimeDetectionEngine`` singleton.

    Parameters
    ----------
    config:
        Optional configuration dict passed only on the *first* call.
    """
    global _detection_engine
    if _detection_engine is None:
        _detection_engine = MarketRegimeDetectionEngine(config)
    return _detection_engine
