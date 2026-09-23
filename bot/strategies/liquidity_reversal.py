"""
NIJA Liquidity Reversal Strategy
==================================

Systematic liquidity-sweep reversal model.

A tradeable setup requires the full sequence:
1. Wick sweep through a prior swing high/low with a close back inside.
2. Directional displacement within the next 1-3 candles.
3. A fresh three-candle fair-value gap (FVG) created by displacement.
4. The current candle is the first retracement into that FVG.
5. Stop sits beyond the sweep wick and target geometry is at least 2R by default.

RSI, volume, macro liquidity and a CRT-style prior-candle sweep are secondary
confluence only. They cannot substitute for the required price-action sequence.
"""

import logging
from typing import Dict, Optional, Tuple

import pandas as pd

from .base_strategy import BaseStrategy
from ._utils import _last

logger = logging.getLogger("nija.strategy.liquidity_reversal")


class LiquidityReversalStrategy(BaseStrategy):
    """Liquidity-sweep reversal with displacement/FVG/retrace confirmation."""

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)

        self.swing_lookback = int(self.config.get("swing_lookback", 10))
        self.sequence_lookback = int(self.config.get("sequence_lookback", 8))
        self.wick_body_ratio = float(self.config.get("wick_body_ratio", 1.5))
        self.displacement_max_bars = int(self.config.get("displacement_max_bars", 3))
        self.displacement_body_atr = float(self.config.get("displacement_body_atr", 0.50))
        self.fvg_min_atr = float(self.config.get("fvg_min_atr", 0.05))
        self.stop_buffer_atr = float(self.config.get("stop_buffer_atr", 0.05))
        self.min_risk_reward = float(self.config.get("min_risk_reward", 2.0))
        self.macro_lookback = int(self.config.get("macro_lookback", 50))

        self.rsi_reversal_max = float(self.config.get("rsi_reversal_max", 40))
        self.rsi_reversal_min = float(self.config.get("rsi_reversal_min", 60))
        self.volume_spike_multiplier = float(self.config.get("volume_spike_multiplier", 1.5))

        self.position_size_multiplier = float(self.config.get("position_size_multiplier", 0.8))
        self.take_profit_multiplier = float(self.config.get("take_profit_multiplier", 1.2))
        self.trailing_stop_distance = float(self.config.get("trailing_stop_distance", 1.5))

    @property
    def name(self) -> str:
        return "LiquidityReversalStrategy"

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = pd.to_numeric(df["high"], errors="coerce")
        low = pd.to_numeric(df["low"], errors="coerce")
        close = pd.to_numeric(df["close"], errors="coerce")
        tr = pd.concat(
            [
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.rolling(period, min_periods=period).mean()

    @staticmethod
    def _range_overlaps(low: float, high: float, zone_low: float, zone_high: float) -> bool:
        return high >= zone_low and low <= zone_high

    def _prior_day_levels(
        self,
        df: pd.DataFrame,
        idx: int,
    ) -> Tuple[Optional[float], Optional[float]]:
        if not isinstance(df.index, pd.DatetimeIndex) or idx <= 0:
            return None, None
        current_day = df.index[idx].normalize()
        previous = df.iloc[:idx]
        previous = previous[previous.index.normalize() < current_day]
        if previous.empty:
            return None, None
        prior_day = previous.index[-1].normalize()
        prior = previous[previous.index.normalize() == prior_day]
        if prior.empty:
            return None, None
        return float(prior["high"].max()), float(prior["low"].min())

    def _find_sequence(
        self,
        df: pd.DataFrame,
        *,
        direction: str,
        atr: pd.Series,
    ) -> Optional[Dict]:
        entry_idx = len(df) - 1
        oldest_sweep = max(self.swing_lookback, entry_idx - self.sequence_lookback)

        for sweep_idx in range(entry_idx - 2, oldest_sweep - 1, -1):
            pre = df.iloc[sweep_idx - self.swing_lookback:sweep_idx]
            if len(pre) < self.swing_lookback:
                continue

            sweep = df.iloc[sweep_idx]
            sweep_open = float(sweep["open"])
            sweep_close = float(sweep["close"])
            sweep_high = float(sweep["high"])
            sweep_low = float(sweep["low"])
            body = abs(sweep_close - sweep_open)
            body_floor = max(body, 1e-12)
            lower_wick = min(sweep_open, sweep_close) - sweep_low
            upper_wick = sweep_high - max(sweep_open, sweep_close)

            swing_low = float(pre["low"].min())
            swing_high = float(pre["high"].max())

            if direction == "long":
                sweep_ok = (
                    sweep_low < swing_low
                    and sweep_close > swing_low
                    and lower_wick >= body_floor * self.wick_body_ratio
                )
            else:
                sweep_ok = (
                    sweep_high > swing_high
                    and sweep_close < swing_high
                    and upper_wick >= body_floor * self.wick_body_ratio
                )
            if not sweep_ok:
                continue

            # CRT-style confluence: sweep the immediately prior candle and close
            # back inside that candle's range. This is a bonus, not a gate.
            prev = df.iloc[sweep_idx - 1]
            if direction == "long":
                crt_confirmed = (
                    sweep_low < float(prev["low"])
                    and float(prev["low"]) <= sweep_close <= float(prev["high"])
                )
            else:
                crt_confirmed = (
                    sweep_high > float(prev["high"])
                    and float(prev["low"]) <= sweep_close <= float(prev["high"])
                )

            disp_end = min(entry_idx - 1, sweep_idx + self.displacement_max_bars)
            for disp_idx in range(sweep_idx + 1, disp_end + 1):
                if disp_idx < 2:
                    continue
                bar = df.iloc[disp_idx]
                bar_open = float(bar["open"])
                bar_close = float(bar["close"])
                bar_body = abs(bar_close - bar_open)
                atr_now = float(atr.iloc[disp_idx]) if pd.notna(atr.iloc[disp_idx]) else 0.0
                if atr_now <= 0:
                    continue

                if direction == "long":
                    displacement_ok = (
                        bar_close > bar_open
                        and bar_body >= atr_now * self.displacement_body_atr
                        and bar_close > sweep_high
                    )
                    fvg_low = float(df.iloc[disp_idx - 2]["high"])
                    fvg_high = float(bar["low"])
                else:
                    displacement_ok = (
                        bar_close < bar_open
                        and bar_body >= atr_now * self.displacement_body_atr
                        and bar_close < sweep_low
                    )
                    fvg_low = float(bar["high"])
                    fvg_high = float(df.iloc[disp_idx - 2]["low"])

                gap_size = fvg_high - fvg_low
                if (
                    not displacement_ok
                    or gap_size <= 0
                    or gap_size < atr_now * self.fvg_min_atr
                ):
                    continue

                # FVG must remain untouched until the current entry candle.
                fresh = True
                for k in range(disp_idx + 1, entry_idx):
                    mid = df.iloc[k]
                    if self._range_overlaps(
                        float(mid["low"]),
                        float(mid["high"]),
                        fvg_low,
                        fvg_high,
                    ):
                        fresh = False
                        break
                if not fresh:
                    continue

                entry = df.iloc[entry_idx]
                entry_low = float(entry["low"])
                entry_high = float(entry["high"])
                entry_close = float(entry["close"])
                if not self._range_overlaps(entry_low, entry_high, fvg_low, fvg_high):
                    continue

                if direction == "long":
                    retrace_ok = entry_close >= fvg_low
                else:
                    retrace_ok = entry_close <= fvg_high
                if not retrace_ok:
                    continue

                atr_entry = (
                    float(atr.iloc[entry_idx])
                    if pd.notna(atr.iloc[entry_idx])
                    else atr_now
                )
                stop_buffer = max(0.0, atr_entry * self.stop_buffer_atr)

                if direction == "long":
                    stop = sweep_low - stop_buffer
                    risk = entry_close - stop
                    opposing_liquidity = swing_high
                    if risk <= 0:
                        continue
                    min_rr_target = entry_close + self.min_risk_reward * risk
                    if (
                        opposing_liquidity > entry_close
                        and (opposing_liquidity - entry_close) / risk >= self.min_risk_reward
                    ):
                        target = opposing_liquidity
                        target_basis = "opposing_buy_side_liquidity"
                    else:
                        target = min_rr_target
                        target_basis = "minimum_risk_reward"
                else:
                    stop = sweep_high + stop_buffer
                    risk = stop - entry_close
                    opposing_liquidity = swing_low
                    if risk <= 0:
                        continue
                    min_rr_target = entry_close - self.min_risk_reward * risk
                    if (
                        opposing_liquidity < entry_close
                        and (entry_close - opposing_liquidity) / risk >= self.min_risk_reward
                    ):
                        target = opposing_liquidity
                        target_basis = "opposing_sell_side_liquidity"
                    else:
                        target = min_rr_target
                        target_basis = "minimum_risk_reward"

                macro_start = max(0, sweep_idx - self.macro_lookback)
                macro = df.iloc[macro_start:sweep_idx]
                macro_sweep = False
                if not macro.empty:
                    if direction == "long":
                        macro_sweep = sweep_low < float(macro["low"].min())
                    else:
                        macro_sweep = sweep_high > float(macro["high"].max())

                pdh, pdl = self._prior_day_levels(df, sweep_idx)
                prior_day_sweep = (
                    (direction == "long" and pdl is not None and sweep_low < pdl)
                    or (direction == "short" and pdh is not None and sweep_high > pdh)
                )

                return {
                    "direction": direction,
                    "sweep_index": sweep_idx,
                    "displacement_index": disp_idx,
                    "swing_low": swing_low,
                    "swing_high": swing_high,
                    "sweep_low": sweep_low,
                    "sweep_high": sweep_high,
                    "fvg_low": fvg_low,
                    "fvg_high": fvg_high,
                    "fvg_gap_size": gap_size,
                    "entry_price": entry_close,
                    "stop_loss": stop,
                    "take_profit": target,
                    "risk_reward": abs(target - entry_close) / risk,
                    "target_basis": target_basis,
                    "opposing_liquidity": opposing_liquidity,
                    "crt_confirmed": crt_confirmed,
                    "macro_sweep": macro_sweep,
                    "prior_day_sweep": bool(prior_day_sweep),
                }
        return None

    def generate_signal(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        try:
            min_bars = max(20, self.swing_lookback + self.sequence_lookback + 3)
            required = {"open", "high", "low", "close"}
            if len(df) < min_bars or not required.issubset(df.columns):
                return {
                    "signal": "NONE",
                    "confidence": 0.0,
                    "reason": "Insufficient OHLC data for liquidity-sweep sequence",
                }

            atr = self._atr(df)
            if pd.isna(atr.iloc[-1]) or float(atr.iloc[-1]) <= 0:
                return {
                    "signal": "NONE",
                    "confidence": 0.0,
                    "reason": "ATR unavailable for liquidity-sweep validation",
                }

            long_setup = self._find_sequence(df, direction="long", atr=atr)
            short_setup = self._find_sequence(df, direction="short", atr=atr)

            if long_setup is None and short_setup is None:
                return {
                    "signal": "NONE",
                    "confidence": 0.0,
                    "reason": (
                        "LiquidityReversal: no complete "
                        "sweep→displacement→fresh-FVG→retrace sequence"
                    ),
                }

            if long_setup and short_setup:
                setup = (
                    long_setup
                    if long_setup["sweep_index"] >= short_setup["sweep_index"]
                    else short_setup
                )
            else:
                setup = long_setup or short_setup

            direction = setup["direction"]
            rsi = _last(indicators.get("rsi_14", indicators.get("rsi")))

            volume_spike = False
            sweep_idx = int(setup["sweep_index"])
            if "volume" in df.columns and sweep_idx > 0:
                volume = float(df.iloc[sweep_idx]["volume"])
                start = max(0, sweep_idx - 20)
                hist = pd.to_numeric(
                    df["volume"].iloc[start:sweep_idx],
                    errors="coerce",
                )
                avg_volume = float(hist.mean()) if not hist.empty else 0.0
                volume_spike = (
                    avg_volume > 0
                    and volume >= avg_volume * self.volume_spike_multiplier
                )

            if direction == "long":
                rsi_confluence = rsi is not None and rsi <= self.rsi_reversal_max
            else:
                rsi_confluence = rsi is not None and rsi >= self.rsi_reversal_min

            confidence = 0.72
            confidence += 0.06 if volume_spike else 0.0
            confidence += 0.05 if rsi_confluence else 0.0
            confidence += 0.05 if setup["crt_confirmed"] else 0.0
            confidence += (
                0.06
                if setup["macro_sweep"] or setup["prior_day_sweep"]
                else 0.0
            )
            confidence = min(0.94, confidence)

            signal = "BUY" if direction == "long" else "SELL"
            return {
                "signal": signal,
                "confidence": confidence,
                "reason": (
                    f"LiquidityReversal {signal}: sweep confirmed, 1-3 candle "
                    f"displacement, fresh FVG first retrace, stop beyond sweep "
                    f"wick, target={setup['target_basis']} "
                    f"({setup['risk_reward']:.2f}R)"
                ),
                "position_size_multiplier": self.position_size_multiplier,
                "take_profit_multiplier": self.take_profit_multiplier,
                "trailing_stop_distance": self.trailing_stop_distance,
                "stop_loss": setup["stop_loss"],
                "take_profit": setup["take_profit"],
                "risk_reward": setup["risk_reward"],
                "metadata": {
                    **setup,
                    "volume_spike": volume_spike,
                    "rsi_confluence": bool(rsi_confluence),
                    "sequence_required": True,
                    "fvg_fresh": True,
                    "fvg_retrace_confirmed": True,
                    "displacement_max_bars": self.displacement_max_bars,
                    "min_risk_reward": self.min_risk_reward,
                },
            }

        except Exception as exc:
            logger.warning("[%s] Signal generation error: %s", self.name, exc)
            return {
                "signal": "NONE",
                "confidence": 0.0,
                "reason": f"Error: {exc}",
            }

    def get_parameters(self) -> Dict:
        return {
            "swing_lookback": self.swing_lookback,
            "sequence_lookback": self.sequence_lookback,
            "wick_body_ratio": self.wick_body_ratio,
            "displacement_max_bars": self.displacement_max_bars,
            "displacement_body_atr": self.displacement_body_atr,
            "fvg_min_atr": self.fvg_min_atr,
            "stop_buffer_atr": self.stop_buffer_atr,
            "min_risk_reward": self.min_risk_reward,
            "macro_lookback": self.macro_lookback,
            "rsi_reversal_max": self.rsi_reversal_max,
            "rsi_reversal_min": self.rsi_reversal_min,
            "volume_spike_multiplier": self.volume_spike_multiplier,
            "position_size_multiplier": self.position_size_multiplier,
            "take_profit_multiplier": self.take_profit_multiplier,
            "trailing_stop_distance": self.trailing_stop_distance,
        }
