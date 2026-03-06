"""
NIJA Hedge Fund Multi-Strategy Engine
======================================

Implements five concrete trading strategy classes used by institutional
hedge funds. Each strategy generates BUY / SELL / HOLD signals, position
sizes, and confidence scores from a pandas OHLCV DataFrame plus a dict of
pre-computed indicators.

Strategy Roster
---------------
| Class                       | Market type      | Style          |
|-----------------------------|------------------|----------------|
| TrendFollowingStrategy      | Trending markets | Momentum/trend |
| MeanReversionStrategy       | Ranging markets  | Counter-trend  |
| StatisticalArbitrageStrategy| Pair correlation | Market-neutral |
| MomentumStrategy            | Breakouts        | Momentum       |
| MacroStrategy               | Risk-on/off      | Macro/multi    |

Usage
-----
    from bot.hedge_fund_strategies import (
        TrendFollowingStrategy,
        MeanReversionStrategy,
        StatisticalArbitrageStrategy,
        MomentumStrategy,
        MacroStrategy,
        HedgeFundStrategyRouter,
    )

    router = HedgeFundStrategyRouter()
    signal = router.get_consensus_signal(df, indicators, regime="TRENDING")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.hedge_fund_strategies")


# ---------------------------------------------------------------------------
# Common data structures
# ---------------------------------------------------------------------------

@dataclass
class StrategySignal:
    """Normalised output from any strategy."""
    strategy_name: str
    symbol: str
    action: str                     # "BUY" | "SELL" | "HOLD"
    confidence: float               # 0.0 – 1.0
    suggested_size_pct: float       # fraction of allocated capital
    stop_loss_pct: float            # e.g. 0.03 → 3 %
    take_profit_pct: float          # e.g. 0.06 → 6 %
    reason: str = ""
    metadata: Dict = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        return {
            "strategy": self.strategy_name,
            "symbol": self.symbol,
            "action": self.action,
            "confidence": round(self.confidence, 4),
            "suggested_size_pct": round(self.suggested_size_pct, 4),
            "stop_loss_pct": round(self.stop_loss_pct, 4),
            "take_profit_pct": round(self.take_profit_pct, 4),
            "reason": self.reason,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ---------------------------------------------------------------------------
# 1. Trend-Following Strategy
# ---------------------------------------------------------------------------

class TrendFollowingStrategy:
    """
    Classic dual-EMA trend-following strategy augmented with ADX filter.

    Entry Logic:
        BUY  when fast EMA crosses above slow EMA AND ADX > threshold
        SELL when fast EMA crosses below slow EMA AND ADX > threshold

    This mimics CTA (Commodity Trading Advisor) fund logic used to capture
    sustained directional moves across multiple asset classes.
    """

    NAME = "TREND_FOLLOWING"
    PREFERRED_REGIMES = {"BULL_TRENDING", "BEAR_TRENDING", "TRENDING_UP", "TRENDING_DOWN"}

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        stop_atr_multiplier: float = 2.0,
        rr_ratio: float = 2.5,
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.stop_atr_multiplier = stop_atr_multiplier
        self.rr_ratio = rr_ratio

    # ------------------------------------------------------------------
    def _adx(self, df: pd.DataFrame) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        atr = _atr(df, self.adx_period)
        plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(self.adx_period).mean() / atr
        minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(self.adx_period).mean() / atr
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
        return dx.rolling(self.adx_period).mean()

    def generate_signal(self, df: pd.DataFrame, symbol: str, indicators: Optional[Dict] = None) -> StrategySignal:
        if len(df) < self.slow_period + 5:
            return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, 0.03, 0.06, "Insufficient data")

        close = df["close"]
        fast_ema = _ema(close, self.fast_period)
        slow_ema = _ema(close, self.slow_period)
        adx_series = self._adx(df)
        atr_series = _atr(df)

        fast_now, fast_prev = fast_ema.iloc[-1], fast_ema.iloc[-2]
        slow_now, slow_prev = slow_ema.iloc[-1], slow_ema.iloc[-2]
        adx_now = adx_series.iloc[-1]
        atr_now = atr_series.iloc[-1]
        price_now = close.iloc[-1]

        if pd.isna(adx_now) or pd.isna(atr_now):
            return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, 0.03, 0.06, "NaN indicators")

        trend_strength = min(adx_now / 50.0, 1.0)
        stop_pct = (atr_now * self.stop_atr_multiplier) / price_now
        tp_pct = stop_pct * self.rr_ratio

        crossed_up = (fast_prev < slow_prev) and (fast_now >= slow_now)
        crossed_down = (fast_prev > slow_prev) and (fast_now <= slow_now)
        adx_ok = adx_now >= self.adx_threshold

        if crossed_up and adx_ok:
            confidence = 0.5 + 0.5 * trend_strength
            return StrategySignal(
                self.NAME, symbol, "BUY", confidence, min(0.25, confidence * 0.3),
                stop_pct, tp_pct,
                f"EMA crossover UP, ADX={adx_now:.1f}",
                {"fast_ema": round(fast_now, 4), "slow_ema": round(slow_now, 4), "adx": round(adx_now, 2)},
            )
        if crossed_down and adx_ok:
            confidence = 0.5 + 0.5 * trend_strength
            return StrategySignal(
                self.NAME, symbol, "SELL", confidence, min(0.25, confidence * 0.3),
                stop_pct, tp_pct,
                f"EMA crossover DOWN, ADX={adx_now:.1f}",
                {"fast_ema": round(fast_now, 4), "slow_ema": round(slow_now, 4), "adx": round(adx_now, 2)},
            )

        return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, stop_pct, tp_pct, "No crossover")


# ---------------------------------------------------------------------------
# 2. Mean-Reversion Strategy
# ---------------------------------------------------------------------------

class MeanReversionStrategy:
    """
    Bollinger Band mean-reversion strategy with RSI confirmation.

    Entry Logic:
        BUY  when price < lower band AND RSI < oversold threshold
        SELL when price > upper band AND RSI > overbought threshold

    Suitable for ranging/sideways markets (SPY pairs, crypto stablecoins).
    """

    NAME = "MEAN_REVERSION"
    PREFERRED_REGIMES = {"RANGING", "LOW_VOLATILITY"}

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        stop_atr_multiplier: float = 1.5,
        rr_ratio: float = 2.0,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.stop_atr_multiplier = stop_atr_multiplier
        self.rr_ratio = rr_ratio

    def generate_signal(self, df: pd.DataFrame, symbol: str, indicators: Optional[Dict] = None) -> StrategySignal:
        if len(df) < self.bb_period + self.rsi_period:
            return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, 0.02, 0.04, "Insufficient data")

        close = df["close"]
        mid = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        upper = mid + self.bb_std * std
        lower = mid - self.bb_std * std
        rsi_series = _rsi(close, self.rsi_period)
        atr_series = _atr(df)

        price = close.iloc[-1]
        rsi_val = rsi_series.iloc[-1]
        upper_val = upper.iloc[-1]
        lower_val = lower.iloc[-1]
        mid_val = mid.iloc[-1]
        atr_val = atr_series.iloc[-1]

        if any(pd.isna(v) for v in [rsi_val, upper_val, lower_val, atr_val]):
            return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, 0.02, 0.04, "NaN indicators")

        stop_pct = (atr_val * self.stop_atr_multiplier) / price
        tp_pct = stop_pct * self.rr_ratio

        bb_width = (upper_val - lower_val) / mid_val
        range_quality = max(0.0, 1.0 - bb_width * 10)

        if price < lower_val and rsi_val < self.rsi_oversold:
            deviation = (lower_val - price) / lower_val
            confidence = min(1.0, 0.5 + deviation * 5 + (self.rsi_oversold - rsi_val) / 100)
            confidence *= 0.6 + 0.4 * range_quality
            return StrategySignal(
                self.NAME, symbol, "BUY", confidence, min(0.2, confidence * 0.25),
                stop_pct, tp_pct,
                f"Price below lower BB, RSI={rsi_val:.1f}",
                {"bb_upper": round(upper_val, 4), "bb_lower": round(lower_val, 4), "rsi": round(rsi_val, 2)},
            )
        if price > upper_val and rsi_val > self.rsi_overbought:
            deviation = (price - upper_val) / upper_val
            confidence = min(1.0, 0.5 + deviation * 5 + (rsi_val - self.rsi_overbought) / 100)
            confidence *= 0.6 + 0.4 * range_quality
            return StrategySignal(
                self.NAME, symbol, "SELL", confidence, min(0.2, confidence * 0.25),
                stop_pct, tp_pct,
                f"Price above upper BB, RSI={rsi_val:.1f}",
                {"bb_upper": round(upper_val, 4), "bb_lower": round(lower_val, 4), "rsi": round(rsi_val, 2)},
            )

        return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, stop_pct, tp_pct, "No reversion signal")


# ---------------------------------------------------------------------------
# 3. Statistical Arbitrage Strategy
# ---------------------------------------------------------------------------

class StatisticalArbitrageStrategy:
    """
    Cointegration-based pairs-trading (statistical arbitrage) strategy.

    Calculates the spread between two correlated assets, fits a rolling
    z-score to the spread, and trades mean-reversion of the spread.

    Entry Logic:
        z-score > threshold  → short the spread (sell asset_a, buy asset_b)
        z-score < -threshold → long the spread (buy asset_a, sell asset_b)

    The returned signal is for asset_a. The hedge is implicit via metadata.
    """

    NAME = "STATISTICAL_ARBITRAGE"
    PREFERRED_REGIMES = {"RANGING", "HIGH_VOLATILITY"}

    def __init__(
        self,
        lookback: int = 60,
        z_entry: float = 2.0,
        z_exit: float = 0.5,
        stop_z: float = 3.5,
        max_corr_age_bars: int = 120,
    ):
        self.lookback = lookback
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.stop_z = stop_z
        self.max_corr_age_bars = max_corr_age_bars

    def _hedge_ratio(self, a: pd.Series, b: pd.Series) -> float:
        """OLS hedge ratio β: a ≈ β·b + ε"""
        if len(a) < 10 or len(b) < 10:
            return 1.0
        b_vals = b.values.reshape(-1, 1)
        a_vals = a.values
        beta = float(np.linalg.lstsq(np.hstack([b_vals, np.ones_like(b_vals)]), a_vals, rcond=None)[0][0])
        return beta

    def generate_signal(
        self,
        df_a: pd.DataFrame,
        df_b: pd.DataFrame,
        symbol_a: str,
        symbol_b: str,
    ) -> StrategySignal:
        """
        Generate a signal for symbol_a given its paired series symbol_b.
        """
        if len(df_a) < self.lookback or len(df_b) < self.lookback:
            return StrategySignal(self.NAME, symbol_a, "HOLD", 0.0, 0.0, 0.02, 0.04,
                                  "Insufficient data for StatArb")

        close_a = df_a["close"].iloc[-self.lookback:]
        close_b = df_b["close"].iloc[-self.lookback:]

        # Align by index where possible
        common = close_a.index.intersection(close_b.index)
        if len(common) < self.lookback // 2:
            return StrategySignal(self.NAME, symbol_a, "HOLD", 0.0, 0.0, 0.02, 0.04,
                                  "No common timestamps for StatArb pair")

        a = close_a.reindex(common)
        b = close_b.reindex(common)

        beta = self._hedge_ratio(a, b)
        spread = a - beta * b
        spread_mean = spread.mean()
        spread_std = spread.std()
        if spread_std < 1e-9:
            return StrategySignal(self.NAME, symbol_a, "HOLD", 0.0, 0.0, 0.02, 0.04,
                                  "Zero spread std — assets too similar")

        z = (spread.iloc[-1] - spread_mean) / spread_std
        corr = float(a.corr(b))
        confidence = min(1.0, abs(corr) * (abs(z) / self.z_entry) * 0.7)

        stop_z_pct = abs(self.stop_z - self.z_entry) * (spread_std / a.iloc[-1])
        tp_pct = abs(z - self.z_exit) * (spread_std / a.iloc[-1])

        if z > self.z_entry:
            return StrategySignal(
                self.NAME, symbol_a, "SELL", confidence, min(0.15, confidence * 0.2),
                stop_z_pct, tp_pct,
                f"Spread z-score={z:.2f} (SELL {symbol_a}, BUY {symbol_b})",
                {"z_score": round(z, 4), "beta": round(beta, 4), "corr": round(corr, 4),
                 "hedge_symbol": symbol_b},
            )
        if z < -self.z_entry:
            return StrategySignal(
                self.NAME, symbol_a, "BUY", confidence, min(0.15, confidence * 0.2),
                stop_z_pct, tp_pct,
                f"Spread z-score={z:.2f} (BUY {symbol_a}, SELL {symbol_b})",
                {"z_score": round(z, 4), "beta": round(beta, 4), "corr": round(corr, 4),
                 "hedge_symbol": symbol_b},
            )

        return StrategySignal(self.NAME, symbol_a, "HOLD", 0.0, 0.0, stop_z_pct, tp_pct,
                              f"Spread z={z:.2f} within bounds")


# ---------------------------------------------------------------------------
# 4. Momentum Strategy
# ---------------------------------------------------------------------------

class MomentumStrategy:
    """
    Cross-sectional and time-series momentum strategy.

    Uses rate-of-change (ROC) across multiple look-back windows combined
    with volume confirmation and RSI to detect sustained breakouts.

    Entry Logic:
        BUY  when composite momentum score > threshold AND volume spike
        SELL when composite momentum score < -threshold AND volume spike

    Suitable for breakout markets and altcoin season rotations.
    """

    NAME = "MOMENTUM"
    PREFERRED_REGIMES = {"BULL_TRENDING", "HIGH_VOLATILITY", "VOLATILE"}

    def __init__(
        self,
        roc_periods: Tuple[int, ...] = (5, 10, 20),
        roc_weights: Tuple[float, ...] = (0.5, 0.3, 0.2),
        volume_ma_period: int = 20,
        volume_spike_factor: float = 1.5,
        rsi_period: int = 14,
        rsi_min: float = 50.0,
        rsi_max: float = 80.0,
        momentum_threshold: float = 0.03,
        stop_atr_multiplier: float = 2.0,
        rr_ratio: float = 3.0,
    ):
        self.roc_periods = roc_periods
        self.roc_weights = roc_weights
        self.volume_ma_period = volume_ma_period
        self.volume_spike_factor = volume_spike_factor
        self.rsi_period = rsi_period
        self.rsi_min = rsi_min
        self.rsi_max = rsi_max
        self.momentum_threshold = momentum_threshold
        self.stop_atr_multiplier = stop_atr_multiplier
        self.rr_ratio = rr_ratio

    def generate_signal(self, df: pd.DataFrame, symbol: str, indicators: Optional[Dict] = None) -> StrategySignal:
        required = max(self.roc_periods) + self.rsi_period
        if len(df) < required:
            return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, 0.03, 0.09, "Insufficient data")

        close = df["close"]
        volume = df.get("volume", pd.Series(np.ones(len(df)), index=df.index))
        rsi_series = _rsi(close, self.rsi_period)
        atr_series = _atr(df)

        # Composite ROC
        roc_score = 0.0
        for period, weight in zip(self.roc_periods, self.roc_weights):
            roc = (close.iloc[-1] - close.iloc[-period - 1]) / close.iloc[-period - 1]
            roc_score += roc * weight

        # Volume confirmation
        vol_ma = volume.rolling(self.volume_ma_period).mean().iloc[-1]
        vol_now = volume.iloc[-1]
        volume_ok = (vol_now >= self.volume_spike_factor * vol_ma) if vol_ma > 0 else True

        rsi_val = rsi_series.iloc[-1]
        atr_val = atr_series.iloc[-1]
        price = close.iloc[-1]

        if pd.isna(rsi_val) or pd.isna(atr_val):
            return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, 0.03, 0.09, "NaN indicators")

        stop_pct = (atr_val * self.stop_atr_multiplier) / price
        tp_pct = stop_pct * self.rr_ratio

        score_abs = abs(roc_score)
        confidence = min(1.0, score_abs / (self.momentum_threshold * 2))

        if roc_score > self.momentum_threshold and volume_ok and self.rsi_min <= rsi_val <= self.rsi_max:
            return StrategySignal(
                self.NAME, symbol, "BUY", confidence, min(0.3, confidence * 0.35),
                stop_pct, tp_pct,
                f"Momentum score={roc_score:.3f}, RSI={rsi_val:.1f}, vol_spike={volume_ok}",
                {"roc_score": round(roc_score, 4), "rsi": round(rsi_val, 2), "volume_spike": volume_ok},
            )
        if roc_score < -self.momentum_threshold and volume_ok and (100 - rsi_val) >= self.rsi_min:
            return StrategySignal(
                self.NAME, symbol, "SELL", confidence, min(0.3, confidence * 0.35),
                stop_pct, tp_pct,
                f"Negative momentum={roc_score:.3f}, RSI={rsi_val:.1f}",
                {"roc_score": round(roc_score, 4), "rsi": round(rsi_val, 2), "volume_spike": volume_ok},
            )

        return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, stop_pct, tp_pct,
                              f"Momentum score {roc_score:.3f} below threshold")


# ---------------------------------------------------------------------------
# 5. Macro Strategy
# ---------------------------------------------------------------------------

class MacroStrategy:
    """
    Macro / risk-on vs risk-off strategy.

    Uses a risk sentiment score derived from:
    - BTC dominance proxy (crypto risk appetite)
    - VIX proxy (30-day realised volatility of reference asset)
    - Trend of the reference asset vs 200-period EMA

    When risk-on: favour long positions in growth assets.
    When risk-off: favour cash or short positions / defensive assets.

    In practice the indicators dict should supply 'btc_dominance',
    'vix_proxy', and '200_ema'. If absent, proxies are computed from df.
    """

    NAME = "MACRO"
    PREFERRED_REGIMES = {"BULL_TRENDING", "BEAR_TRENDING", "VOLATILE", "CRISIS"}

    def __init__(
        self,
        ema_period: int = 200,
        vol_lookback: int = 30,
        vol_threshold_high: float = 0.05,
        vol_threshold_extreme: float = 0.10,
        stop_atr_multiplier: float = 2.5,
        rr_ratio: float = 3.0,
    ):
        self.ema_period = ema_period
        self.vol_lookback = vol_lookback
        self.vol_threshold_high = vol_threshold_high
        self.vol_threshold_extreme = vol_threshold_extreme
        self.stop_atr_multiplier = stop_atr_multiplier
        self.rr_ratio = rr_ratio

    def _risk_score(self, df: pd.DataFrame, indicators: Dict) -> float:
        """
        Compute risk-on/off score in [-1, +1].
        Positive → risk-on, negative → risk-off.
        """
        close = df["close"]
        score = 0.0
        weight_total = 0.0

        # 1. 200-EMA trend
        if len(close) >= self.ema_period:
            ema_200 = _ema(close, self.ema_period).iloc[-1]
            price = close.iloc[-1]
            trend_component = (price / ema_200 - 1.0) * 5  # scale to ~[-1, 1]
            score += np.clip(trend_component, -1.0, 1.0) * 0.5
            weight_total += 0.5

        # 2. Realised volatility proxy
        if len(close) >= self.vol_lookback:
            returns = close.pct_change().iloc[-self.vol_lookback:]
            realised_vol = returns.std() * math.sqrt(252)
            if realised_vol >= self.vol_threshold_extreme:
                vol_component = -1.0
            elif realised_vol >= self.vol_threshold_high:
                vol_component = -0.5
            else:
                vol_component = 0.5
            score += vol_component * 0.3
            weight_total += 0.3

        # 3. External indicators (if provided)
        if "btc_dominance" in indicators:
            dom = indicators["btc_dominance"]
            dom_component = 0.5 if dom < 0.45 else -0.3 if dom > 0.60 else 0.0
            score += dom_component * 0.1
            weight_total += 0.1

        if "vix_proxy" in indicators:
            vix = indicators["vix_proxy"]
            vix_component = -1.0 if vix > 30 else -0.3 if vix > 20 else 0.5
            score += vix_component * 0.1
            weight_total += 0.1

        return float(np.clip(score, -1.0, 1.0)) if weight_total > 0 else 0.0

    def generate_signal(self, df: pd.DataFrame, symbol: str, indicators: Optional[Dict] = None) -> StrategySignal:
        if indicators is None:
            indicators = {}
        if len(df) < self.vol_lookback + 5:
            return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, 0.04, 0.12, "Insufficient data")

        atr_series = _atr(df)
        atr_val = atr_series.iloc[-1]
        price = df["close"].iloc[-1]
        if pd.isna(atr_val):
            return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, 0.04, 0.12, "NaN ATR")

        stop_pct = (atr_val * self.stop_atr_multiplier) / price
        tp_pct = stop_pct * self.rr_ratio

        risk = self._risk_score(df, indicators)
        confidence = abs(risk)

        if risk > 0.4:
            return StrategySignal(
                self.NAME, symbol, "BUY", confidence, min(0.25, confidence * 0.3),
                stop_pct, tp_pct,
                f"Macro risk-on score={risk:.2f}",
                {"risk_score": round(risk, 4), "regime": "RISK_ON"},
            )
        if risk < -0.4:
            return StrategySignal(
                self.NAME, symbol, "SELL", confidence, min(0.25, confidence * 0.3),
                stop_pct, tp_pct,
                f"Macro risk-off score={risk:.2f}",
                {"risk_score": round(risk, 4), "regime": "RISK_OFF"},
            )

        return StrategySignal(self.NAME, symbol, "HOLD", 0.0, 0.0, stop_pct, tp_pct,
                              f"Macro neutral score={risk:.2f}")


# ---------------------------------------------------------------------------
# Consensus Router
# ---------------------------------------------------------------------------

class HedgeFundStrategyRouter:
    """
    Combines all five strategies into a consensus signal for a single symbol.

    Each strategy votes with its confidence score. The final action is the
    one with the highest aggregate confidence. A minimum *quorum* of active
    votes is required before placing a trade (default: 2).

    Usage::

        router = HedgeFundStrategyRouter()
        signal = router.get_consensus_signal(df, indicators={}, regime="TRENDING")
    """

    REGIME_WEIGHTS: Dict[str, Dict[str, float]] = {
        "BULL_TRENDING":  {"TREND_FOLLOWING": 0.35, "MOMENTUM": 0.30, "MACRO": 0.20, "MEAN_REVERSION": 0.10, "STATISTICAL_ARBITRAGE": 0.05},
        "BEAR_TRENDING":  {"TREND_FOLLOWING": 0.30, "MACRO": 0.30, "MEAN_REVERSION": 0.20, "MOMENTUM": 0.15, "STATISTICAL_ARBITRAGE": 0.05},
        "RANGING":        {"MEAN_REVERSION": 0.40, "STATISTICAL_ARBITRAGE": 0.30, "MOMENTUM": 0.15, "TREND_FOLLOWING": 0.10, "MACRO": 0.05},
        "HIGH_VOLATILITY":{"MOMENTUM": 0.30, "MEAN_REVERSION": 0.25, "STATISTICAL_ARBITRAGE": 0.20, "MACRO": 0.15, "TREND_FOLLOWING": 0.10},
        "CRISIS":         {"MACRO": 0.50, "MEAN_REVERSION": 0.25, "STATISTICAL_ARBITRAGE": 0.15, "TREND_FOLLOWING": 0.05, "MOMENTUM": 0.05},
        "DEFAULT":        {"TREND_FOLLOWING": 0.25, "MEAN_REVERSION": 0.25, "MOMENTUM": 0.20, "MACRO": 0.20, "STATISTICAL_ARBITRAGE": 0.10},
    }

    def __init__(
        self,
        min_quorum: int = 2,
        min_confidence: float = 0.45,
        trend_params: Optional[Dict] = None,
        mean_rev_params: Optional[Dict] = None,
        momentum_params: Optional[Dict] = None,
        macro_params: Optional[Dict] = None,
    ):
        self.min_quorum = min_quorum
        self.min_confidence = min_confidence
        self.trend = TrendFollowingStrategy(**(trend_params or {}))
        self.mean_rev = MeanReversionStrategy(**(mean_rev_params or {}))
        self.momentum = MomentumStrategy(**(momentum_params or {}))
        self.macro = MacroStrategy(**(macro_params or {}))
        # StatArb requires two DataFrames — handled separately
        self.stat_arb = StatisticalArbitrageStrategy()

    # ------------------------------------------------------------------
    def get_consensus_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        indicators: Optional[Dict] = None,
        regime: str = "DEFAULT",
        df_pair: Optional[pd.DataFrame] = None,
        pair_symbol: Optional[str] = None,
    ) -> Dict:
        """
        Aggregate signals from all applicable strategies for one symbol.

        Args:
            df: OHLCV DataFrame for the primary symbol.
            symbol: Ticker / product ID.
            indicators: Pre-computed indicator dict (optional).
            regime: Market regime string.
            df_pair: Optional second DataFrame for StatArb.
            pair_symbol: Ticker for the paired asset.

        Returns:
            Dict with keys: action, confidence, strategy_votes, weights, signal_detail
        """
        if indicators is None:
            indicators = {}

        weights = self.REGIME_WEIGHTS.get(regime.upper(), self.REGIME_WEIGHTS["DEFAULT"])

        signals: List[StrategySignal] = [
            self.trend.generate_signal(df, symbol, indicators),
            self.mean_rev.generate_signal(df, symbol, indicators),
            self.momentum.generate_signal(df, symbol, indicators),
            self.macro.generate_signal(df, symbol, indicators),
        ]

        if df_pair is not None and pair_symbol:
            signals.append(self.stat_arb.generate_signal(df, df_pair, symbol, pair_symbol))

        # Weighted vote
        buy_score = 0.0
        sell_score = 0.0
        buy_votes = 0
        sell_votes = 0
        vote_details = []

        for sig in signals:
            w = weights.get(sig.strategy_name, 0.1)
            weighted_conf = sig.confidence * w
            vote_details.append({
                "strategy": sig.strategy_name,
                "action": sig.action,
                "confidence": round(sig.confidence, 4),
                "weight": round(w, 4),
                "weighted": round(weighted_conf, 4),
                "reason": sig.reason,
            })
            if sig.action == "BUY":
                buy_score += weighted_conf
                buy_votes += 1
            elif sig.action == "SELL":
                sell_score += weighted_conf
                sell_votes += 1

        # Determine consensus
        consensus_action = "HOLD"
        consensus_confidence = 0.0

        if buy_score > sell_score and buy_votes >= self.min_quorum:
            consensus_action = "BUY"
            consensus_confidence = buy_score
        elif sell_score > buy_score and sell_votes >= self.min_quorum:
            consensus_action = "SELL"
            consensus_confidence = sell_score

        if consensus_confidence < self.min_confidence:
            consensus_action = "HOLD"
            consensus_confidence = 0.0

        # Use first non-HOLD signal for stop/tp params
        ref_signal = next((s for s in signals if s.action != "HOLD"), signals[0])

        return {
            "action": consensus_action,
            "confidence": round(consensus_confidence, 4),
            "symbol": symbol,
            "regime": regime,
            "buy_score": round(buy_score, 4),
            "sell_score": round(sell_score, 4),
            "buy_votes": buy_votes,
            "sell_votes": sell_votes,
            "suggested_size_pct": ref_signal.suggested_size_pct if consensus_action != "HOLD" else 0.0,
            "stop_loss_pct": ref_signal.stop_loss_pct,
            "take_profit_pct": ref_signal.take_profit_pct,
            "strategy_votes": vote_details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Multi-Asset Wrapper
# ---------------------------------------------------------------------------

ASSET_CLASS_STRATEGIES: Dict[str, List[str]] = {
    "CRYPTO":      ["TREND_FOLLOWING", "MOMENTUM", "MEAN_REVERSION", "STATISTICAL_ARBITRAGE", "MACRO"],
    "EQUITY":      ["TREND_FOLLOWING", "MEAN_REVERSION", "MOMENTUM", "MACRO"],
    "FX":          ["MEAN_REVERSION", "MACRO", "TREND_FOLLOWING"],
    "FUTURES":     ["TREND_FOLLOWING", "MOMENTUM", "MACRO"],
    "OPTIONS":     ["MEAN_REVERSION", "MACRO"],
}


def get_strategy_router(
    regime: str = "DEFAULT",
    min_quorum: int = 2,
    min_confidence: float = 0.45,
) -> HedgeFundStrategyRouter:
    """
    Factory that returns a configured HedgeFundStrategyRouter.

    Args:
        regime: Detected market regime.
        min_quorum: Minimum voting strategies required for action.
        min_confidence: Minimum aggregate confidence to act.

    Returns:
        Configured HedgeFundStrategyRouter instance.
    """
    return HedgeFundStrategyRouter(
        min_quorum=min_quorum,
        min_confidence=min_confidence,
    )
