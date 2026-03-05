"""
NIJA Momentum Breakout Strategy
=================================

Optimised for **VOLATILE / BREAKOUT** markets.

Logic:
- Identifies consolidation breakouts using Bollinger Band width expansion.
- Uses RSI momentum and volume surge for confirmation.
- Reduced position size with wider stops to manage whipsaw risk.
"""

import logging
from typing import Dict, Optional

import pandas as pd

from .base_strategy import BaseStrategy
from ._utils import _last

logger = logging.getLogger("nija.strategy.momentum_breakout")


class MomentumBreakoutStrategy(BaseStrategy):
    """
    Momentum Breakout Strategy – best suited for VOLATILE market regimes.

    Entry conditions (long breakout):
        1. Close breaks above upper Bollinger Band (or above recent high)
        2. RSI between ``rsi_momentum_min`` and ``rsi_momentum_max``
        3. Volume surge: current volume > ``volume_surge_multiplier`` × average
        4. ATR expansion: current ATR > ``atr_expansion_multiplier`` × rolling average

    At least ``min_confirmations`` out of 4 conditions must be met.
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)

        # RSI thresholds – momentum entries (not extreme levels)
        self.rsi_long_min = self.config.get("rsi_long_min", 50)
        self.rsi_long_max = self.config.get("rsi_long_max", 70)
        self.rsi_short_min = self.config.get("rsi_short_min", 30)
        self.rsi_short_max = self.config.get("rsi_short_max", 50)

        # Volume and ATR expansion thresholds
        self.volume_surge_multiplier = self.config.get("volume_surge_multiplier", 1.5)
        self.atr_expansion_multiplier = self.config.get("atr_expansion_multiplier", 1.2)

        # Signal quality
        self.min_confirmations = self.config.get("min_confirmations", 3)
        self.position_size_multiplier = self.config.get("position_size_multiplier", 0.7)
        self.take_profit_multiplier = self.config.get("take_profit_multiplier", 1.0)
        self.trailing_stop_distance = self.config.get("trailing_stop_distance", 2.0)

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "MomentumBreakoutStrategy"

    def generate_signal(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """Generate breakout signal using BB width, RSI, volume, and ATR."""
        try:
            rsi = _last(indicators.get("rsi_14", indicators.get("rsi")))
            bb_upper = _last(indicators.get("bb_upper", indicators.get("bollinger_upper")))
            bb_lower = _last(indicators.get("bb_lower", indicators.get("bollinger_lower")))
            atr = _last(indicators.get("atr"))
            close = _last(df["close"])

            volume = _last(df["volume"]) if "volume" in df.columns else None
            avg_volume = df["volume"].rolling(20).mean().iloc[-1] if "volume" in df.columns else None
            avg_atr = None
            if "atr" in indicators and hasattr(indicators["atr"], "rolling"):
                avg_atr_series = indicators["atr"].rolling(14).mean()
                avg_atr = _last(avg_atr_series)

            # ── Long breakout ──────────────────────────────────────────
            long_score = 0
            if bb_upper is not None and close is not None and close > bb_upper:
                long_score += 1
            if rsi is not None and self.rsi_long_min <= rsi <= self.rsi_long_max:
                long_score += 1
            if (volume is not None and avg_volume is not None and avg_volume > 0
                    and volume > avg_volume * self.volume_surge_multiplier):
                long_score += 1
            if (atr is not None and avg_atr is not None and avg_atr > 0
                    and atr > avg_atr * self.atr_expansion_multiplier):
                long_score += 1

            # ── Short breakout ─────────────────────────────────────────
            short_score = 0
            if bb_lower is not None and close is not None and close < bb_lower:
                short_score += 1
            if rsi is not None and self.rsi_short_min <= rsi <= self.rsi_short_max:
                short_score += 1
            if (volume is not None and avg_volume is not None and avg_volume > 0
                    and volume > avg_volume * self.volume_surge_multiplier):
                short_score += 1
            if (atr is not None and avg_atr is not None and avg_atr > 0
                    and atr > avg_atr * self.atr_expansion_multiplier):
                short_score += 1

            if long_score >= self.min_confirmations and long_score >= short_score:
                return {
                    "signal": "BUY",
                    "confidence": long_score / 4.0,
                    "reason": f"MomentumBreakout BUY: {long_score}/4 conditions met",
                    "position_size_multiplier": self.position_size_multiplier,
                    "take_profit_multiplier": self.take_profit_multiplier,
                    "trailing_stop_distance": self.trailing_stop_distance,
                }

            if short_score >= self.min_confirmations and short_score > long_score:
                return {
                    "signal": "SELL",
                    "confidence": short_score / 4.0,
                    "reason": f"MomentumBreakout SELL: {short_score}/4 conditions met",
                    "position_size_multiplier": self.position_size_multiplier,
                    "take_profit_multiplier": self.take_profit_multiplier,
                    "trailing_stop_distance": self.trailing_stop_distance,
                }

            return {"signal": "NONE", "confidence": 0.0, "reason": "MomentumBreakout: insufficient confirmations"}

        except Exception as exc:
            logger.warning(f"[{self.name}] Signal generation error: {exc}")
            return {"signal": "NONE", "confidence": 0.0, "reason": f"Error: {exc}"}

    def get_parameters(self) -> Dict:
        return {
            "rsi_long_min": self.rsi_long_min,
            "rsi_long_max": self.rsi_long_max,
            "rsi_short_min": self.rsi_short_min,
            "rsi_short_max": self.rsi_short_max,
            "volume_surge_multiplier": self.volume_surge_multiplier,
            "atr_expansion_multiplier": self.atr_expansion_multiplier,
            "min_confirmations": self.min_confirmations,
            "position_size_multiplier": self.position_size_multiplier,
            "take_profit_multiplier": self.take_profit_multiplier,
            "trailing_stop_distance": self.trailing_stop_distance,
        }

