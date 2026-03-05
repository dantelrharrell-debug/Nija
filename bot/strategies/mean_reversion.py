"""
NIJA Mean Reversion Strategy
==============================

Optimised for **RANGING** markets (ADX < 20, low volatility).

Logic:
- Buys at extreme oversold levels and sells at extreme overbought levels.
- Uses Bollinger Band touches + RSI extremes + volume confirmation.
- Smaller position size with tighter stops; profits taken faster.
"""

import logging
from typing import Dict, Optional

import pandas as pd

from .base_strategy import BaseStrategy
from ._utils import _last

logger = logging.getLogger("nija.strategy.mean_reversion")


class MeanReversionStrategy(BaseStrategy):
    """
    Mean Reversion Strategy – best suited for RANGING market regimes.

    Entry conditions (long – buy oversold dip):
        1. RSI below ``rsi_oversold`` (extreme oversold)
        2. Close at or below lower Bollinger Band
        3. Volume above minimum threshold (enough liquidity)

    Entry conditions (short – sell overbought peak):
        1. RSI above ``rsi_overbought`` (extreme overbought)
        2. Close at or above upper Bollinger Band
        3. Volume above minimum threshold

    At least ``min_confirmations`` out of 3 must be met.
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)

        # RSI extreme thresholds
        self.rsi_oversold = self.config.get("rsi_oversold", 35)
        self.rsi_overbought = self.config.get("rsi_overbought", 65)

        # Signal quality
        self.min_confirmations = self.config.get("min_confirmations", 2)
        self.position_size_multiplier = self.config.get("position_size_multiplier", 0.8)
        self.take_profit_multiplier = self.config.get("take_profit_multiplier", 0.8)
        self.trailing_stop_distance = self.config.get("trailing_stop_distance", 1.0)

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "MeanReversionStrategy"

    def generate_signal(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """Generate mean-reversion signal using RSI extremes and Bollinger Bands."""
        try:
            rsi = _last(indicators.get("rsi_14", indicators.get("rsi")))
            bb_upper = _last(indicators.get("bb_upper", indicators.get("bollinger_upper")))
            bb_lower = _last(indicators.get("bb_lower", indicators.get("bollinger_lower")))
            close = _last(df["close"])

            volume = _last(df["volume"]) if "volume" in df.columns else None
            avg_volume = df["volume"].rolling(20).mean().iloc[-1] if "volume" in df.columns else None
            has_volume = (
                volume is not None and avg_volume is not None
                and avg_volume > 0 and volume > avg_volume * 0.5
            )

            # ── Long: buy the oversold dip ─────────────────────────────
            long_score = 0
            if rsi is not None and rsi < self.rsi_oversold:
                long_score += 1
            if bb_lower is not None and close is not None and close <= bb_lower:
                long_score += 1
            if has_volume:
                long_score += 1

            # ── Short: sell the overbought peak ───────────────────────
            short_score = 0
            if rsi is not None and rsi > self.rsi_overbought:
                short_score += 1
            if bb_upper is not None and close is not None and close >= bb_upper:
                short_score += 1
            if has_volume:
                short_score += 1

            if long_score >= self.min_confirmations and long_score >= short_score:
                return {
                    "signal": "BUY",
                    "confidence": long_score / 3.0,
                    "reason": f"MeanReversion BUY: {long_score}/3 conditions met (RSI={rsi:.1f})" if rsi else f"MeanReversion BUY: {long_score}/3 conditions met",
                    "position_size_multiplier": self.position_size_multiplier,
                    "take_profit_multiplier": self.take_profit_multiplier,
                    "trailing_stop_distance": self.trailing_stop_distance,
                }

            if short_score >= self.min_confirmations and short_score > long_score:
                return {
                    "signal": "SELL",
                    "confidence": short_score / 3.0,
                    "reason": f"MeanReversion SELL: {short_score}/3 conditions met (RSI={rsi:.1f})" if rsi else f"MeanReversion SELL: {short_score}/3 conditions met",
                    "position_size_multiplier": self.position_size_multiplier,
                    "take_profit_multiplier": self.take_profit_multiplier,
                    "trailing_stop_distance": self.trailing_stop_distance,
                }

            return {"signal": "NONE", "confidence": 0.0, "reason": "MeanReversion: conditions not met"}

        except Exception as exc:
            logger.warning(f"[{self.name}] Signal generation error: {exc}")
            return {"signal": "NONE", "confidence": 0.0, "reason": f"Error: {exc}"}

    def get_parameters(self) -> Dict:
        return {
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "min_confirmations": self.min_confirmations,
            "position_size_multiplier": self.position_size_multiplier,
            "take_profit_multiplier": self.take_profit_multiplier,
            "trailing_stop_distance": self.trailing_stop_distance,
        }

