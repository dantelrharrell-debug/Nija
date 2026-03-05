"""
NIJA Liquidity Reversal Strategy
==================================

Targets price levels where institutional liquidity pools are likely to be
hunted (stop-runs), then fades the move back toward fair value.

Applicable across multiple regimes but particularly useful during
**VOLATILE** markets and around key support/resistance levels.

Logic:
- Identifies potential liquidity sweeps via a spike through a recent swing
  high/low followed by a fast reversal (pin-bar / wick pattern).
- Confirms with RSI divergence signal (price makes new extreme but RSI does not).
- Volume spike adds confidence.
"""

import logging
from typing import Dict, Optional

import pandas as pd

from .base_strategy import BaseStrategy
from ._utils import _last

logger = logging.getLogger("nija.strategy.liquidity_reversal")


class LiquidityReversalStrategy(BaseStrategy):
    """
    Liquidity Reversal Strategy – targets stop-hunt / liquidity-grab reversals.

    Entry conditions (long – bullish reversal after stop-hunt below swing low):
        1. Most recent candle low pierced the ``swing_lookback``-candle swing low
           but closed back above it (wick through the level).
        2. Lower wick is at least ``wick_body_ratio`` times the candle body.
        3. RSI is below ``rsi_reversal_max`` (oversold zone at the sweep).
        4. Volume spike: current volume > ``volume_spike_multiplier`` × average.

    At least ``min_confirmations`` out of 4 must be met.
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)

        # Swing high/low detection lookback
        self.swing_lookback = self.config.get("swing_lookback", 10)

        # Wick size relative to body (wick must be meaningfully longer)
        self.wick_body_ratio = self.config.get("wick_body_ratio", 1.5)

        # RSI at liquidity zone
        self.rsi_reversal_max = self.config.get("rsi_reversal_max", 40)   # oversold for longs
        self.rsi_reversal_min = self.config.get("rsi_reversal_min", 60)   # overbought for shorts

        # Volume spike
        self.volume_spike_multiplier = self.config.get("volume_spike_multiplier", 1.5)

        # Signal quality
        self.min_confirmations = self.config.get("min_confirmations", 2)
        self.position_size_multiplier = self.config.get("position_size_multiplier", 0.8)
        self.take_profit_multiplier = self.config.get("take_profit_multiplier", 1.2)
        self.trailing_stop_distance = self.config.get("trailing_stop_distance", 1.5)

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "LiquidityReversalStrategy"

    def generate_signal(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """
        Generate liquidity-reversal signal.

        Checks for a wick-through-and-close-back pattern at swing extremes,
        then confirms with RSI and volume.
        """
        try:
            if len(df) < self.swing_lookback + 2:
                return {"signal": "NONE", "confidence": 0.0, "reason": "Insufficient data for swing detection"}

            rsi = _last(indicators.get("rsi_14", indicators.get("rsi")))

            # Current candle values
            curr = df.iloc[-1]
            curr_open = float(curr["open"])
            curr_close = float(curr["close"])
            curr_high = float(curr["high"])
            curr_low = float(curr["low"])

            # Swing levels over the lookback window (excluding current candle)
            lookback_df = df.iloc[-(self.swing_lookback + 1):-1]
            swing_low = float(lookback_df["low"].min())
            swing_high = float(lookback_df["high"].max())

            # Candle body size
            body = abs(curr_close - curr_open)
            lower_wick = min(curr_open, curr_close) - curr_low
            upper_wick = curr_high - max(curr_open, curr_close)

            # Volume
            volume = float(curr["volume"]) if "volume" in df.columns else None
            avg_volume = df["volume"].rolling(20).mean().iloc[-1] if "volume" in df.columns else None
            volume_spike = (
                volume is not None and avg_volume is not None
                and avg_volume > 0
                and volume > avg_volume * self.volume_spike_multiplier
            )

            # ── Bullish liquidity reversal ─────────────────────────────
            # Candle wicked below swing low but closed back above it
            long_score = 0
            swept_low = curr_low < swing_low and curr_close > swing_low
            if swept_low:
                long_score += 1
            wick_confirms_long = body > 0 and lower_wick >= body * self.wick_body_ratio
            if wick_confirms_long:
                long_score += 1
            if rsi is not None and rsi <= self.rsi_reversal_max:
                long_score += 1
            if volume_spike:
                long_score += 1

            # ── Bearish liquidity reversal ─────────────────────────────
            # Candle wicked above swing high but closed back below it
            short_score = 0
            swept_high = curr_high > swing_high and curr_close < swing_high
            if swept_high:
                short_score += 1
            wick_confirms_short = body > 0 and upper_wick >= body * self.wick_body_ratio
            if wick_confirms_short:
                short_score += 1
            if rsi is not None and rsi >= self.rsi_reversal_min:
                short_score += 1
            if volume_spike:
                short_score += 1

            if long_score >= self.min_confirmations and long_score >= short_score:
                return {
                    "signal": "BUY",
                    "confidence": long_score / 4.0,
                    "reason": f"LiquidityReversal BUY: {long_score}/4 conditions (swept_low={swept_low}, wick_ok={wick_confirms_long})",
                    "position_size_multiplier": self.position_size_multiplier,
                    "take_profit_multiplier": self.take_profit_multiplier,
                    "trailing_stop_distance": self.trailing_stop_distance,
                }

            if short_score >= self.min_confirmations and short_score > long_score:
                return {
                    "signal": "SELL",
                    "confidence": short_score / 4.0,
                    "reason": f"LiquidityReversal SELL: {short_score}/4 conditions (swept_high={swept_high}, wick_ok={wick_confirms_short})",
                    "position_size_multiplier": self.position_size_multiplier,
                    "take_profit_multiplier": self.take_profit_multiplier,
                    "trailing_stop_distance": self.trailing_stop_distance,
                }

            return {"signal": "NONE", "confidence": 0.0, "reason": "LiquidityReversal: no sweep detected"}

        except Exception as exc:
            logger.warning(f"[{self.name}] Signal generation error: {exc}")
            return {"signal": "NONE", "confidence": 0.0, "reason": f"Error: {exc}"}

    def get_parameters(self) -> Dict:
        return {
            "swing_lookback": self.swing_lookback,
            "wick_body_ratio": self.wick_body_ratio,
            "rsi_reversal_max": self.rsi_reversal_max,
            "rsi_reversal_min": self.rsi_reversal_min,
            "volume_spike_multiplier": self.volume_spike_multiplier,
            "min_confirmations": self.min_confirmations,
            "position_size_multiplier": self.position_size_multiplier,
            "take_profit_multiplier": self.take_profit_multiplier,
            "trailing_stop_distance": self.trailing_stop_distance,
        }

