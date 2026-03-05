"""
NIJA APEX Trend Strategy
=========================

Optimised for **TRENDING** markets (ADX > 25).

Logic:
- Uses dual RSI (RSI-9 + RSI-14) to identify momentum pullbacks within a trend.
- Entry confirmation via EMA alignment, MACD direction, and volume.
- Wider take-profit targets and a larger position-size multiplier to ride trends.
"""

import logging
from typing import Dict, Optional

import pandas as pd

from .base_strategy import BaseStrategy
from ._utils import _last

logger = logging.getLogger("nija.strategy.apex_trend")


class ApexTrendStrategy(BaseStrategy):
    """
    APEX Trend-Following Strategy – best suited for TRENDING market regimes.

    Entry conditions (long):
        1. RSI-9  between ``rsi9_long_min``  and ``rsi9_long_max``
        2. RSI-14 between ``rsi14_long_min`` and ``rsi14_long_max``
        3. Close price above EMA-21 (trend filter)
        4. MACD histogram > 0 (momentum alignment)
        5. Volume above rolling average

    At least ``min_confirmations`` out of 5 conditions must be met for a signal.
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)

        # RSI window thresholds
        self.rsi9_long_min = self.config.get("rsi9_long_min", 30)
        self.rsi9_long_max = self.config.get("rsi9_long_max", 55)
        self.rsi14_long_min = self.config.get("rsi14_long_min", 30)
        self.rsi14_long_max = self.config.get("rsi14_long_max", 55)

        self.rsi9_short_min = self.config.get("rsi9_short_min", 45)
        self.rsi9_short_max = self.config.get("rsi9_short_max", 70)
        self.rsi14_short_min = self.config.get("rsi14_short_min", 45)
        self.rsi14_short_max = self.config.get("rsi14_short_max", 70)

        # General thresholds
        self.min_confirmations = self.config.get("min_confirmations", 3)
        self.position_size_multiplier = self.config.get("position_size_multiplier", 1.2)
        self.take_profit_multiplier = self.config.get("take_profit_multiplier", 1.5)
        self.trailing_stop_distance = self.config.get("trailing_stop_distance", 1.5)

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "ApexTrendStrategy"

    def generate_signal(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """Generate trend-following signal based on dual RSI + EMA + MACD."""
        try:
            rsi9 = _last(indicators.get("rsi_9", indicators.get("rsi9")))
            rsi14 = _last(indicators.get("rsi_14", indicators.get("rsi14", indicators.get("rsi"))))
            ema21 = _last(indicators.get("ema_21", indicators.get("ema21")))
            macd_hist = _last(indicators.get("macd_hist", indicators.get("macd_histogram")))
            volume = _last(df["volume"]) if "volume" in df.columns else None
            avg_volume = df["volume"].rolling(20).mean().iloc[-1] if "volume" in df.columns else None
            close = _last(df["close"])

            # Score long conditions
            long_score = 0
            if rsi9 is not None and self.rsi9_long_min <= rsi9 <= self.rsi9_long_max:
                long_score += 1
            if rsi14 is not None and self.rsi14_long_min <= rsi14 <= self.rsi14_long_max:
                long_score += 1
            if ema21 is not None and close is not None and close > ema21:
                long_score += 1
            if macd_hist is not None and macd_hist > 0:
                long_score += 1
            if volume is not None and avg_volume is not None and avg_volume > 0 and volume > avg_volume:
                long_score += 1

            # Score short conditions
            short_score = 0
            if rsi9 is not None and self.rsi9_short_min <= rsi9 <= self.rsi9_short_max:
                short_score += 1
            if rsi14 is not None and self.rsi14_short_min <= rsi14 <= self.rsi14_short_max:
                short_score += 1
            if ema21 is not None and close is not None and close < ema21:
                short_score += 1
            if macd_hist is not None and macd_hist < 0:
                short_score += 1
            if volume is not None and avg_volume is not None and avg_volume > 0 and volume > avg_volume:
                short_score += 1

            if long_score >= self.min_confirmations and long_score >= short_score:
                return {
                    "signal": "BUY",
                    "confidence": long_score / 5.0,
                    "reason": f"ApexTrend BUY: {long_score}/5 conditions met",
                    "position_size_multiplier": self.position_size_multiplier,
                    "take_profit_multiplier": self.take_profit_multiplier,
                    "trailing_stop_distance": self.trailing_stop_distance,
                }

            if short_score >= self.min_confirmations and short_score > long_score:
                return {
                    "signal": "SELL",
                    "confidence": short_score / 5.0,
                    "reason": f"ApexTrend SELL: {short_score}/5 conditions met",
                    "position_size_multiplier": self.position_size_multiplier,
                    "take_profit_multiplier": self.take_profit_multiplier,
                    "trailing_stop_distance": self.trailing_stop_distance,
                }

            return {"signal": "NONE", "confidence": 0.0, "reason": "ApexTrend: insufficient confirmations"}

        except Exception as exc:
            logger.warning(f"[{self.name}] Signal generation error: {exc}")
            return {"signal": "NONE", "confidence": 0.0, "reason": f"Error: {exc}"}

    def get_parameters(self) -> Dict:
        return {
            "rsi9_long_min": self.rsi9_long_min,
            "rsi9_long_max": self.rsi9_long_max,
            "rsi14_long_min": self.rsi14_long_min,
            "rsi14_long_max": self.rsi14_long_max,
            "rsi9_short_min": self.rsi9_short_min,
            "rsi9_short_max": self.rsi9_short_max,
            "rsi14_short_min": self.rsi14_short_min,
            "rsi14_short_max": self.rsi14_short_max,
            "min_confirmations": self.min_confirmations,
            "position_size_multiplier": self.position_size_multiplier,
            "take_profit_multiplier": self.take_profit_multiplier,
            "trailing_stop_distance": self.trailing_stop_distance,
        }

