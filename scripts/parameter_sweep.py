"""Parameter sweep runner for NIJA — simple walk-forward smoke test.

This script performs a lightweight parameter sweep using the existing
SimpleWalkForwardOptimizer. It contains a minimal backtest function that
simulates entries based on `ApexTrendStrategy.generate_signal()` and a
fixed holding period exit. If no historical CSVs are found in `./data/`,
the script generates synthetic OHLCV data for a smoke test.

Usage:
  python scripts/parameter_sweep.py

Outputs:
  - Prints recommended params to stdout
  - Writes `parameter_sweep_results.csv` with per-combination metrics
"""
import logging
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from bot.walk_forward_optimizer import SimpleWalkForwardOptimizer
# Local lightweight strategy implementation to avoid importing full package
# during a quick parameter sweep smoke test.
class LocalApexTrendStrategy:
    """Lightweight local reimplementation of ApexTrendStrategy.generate_signal
    to be used by the parameter-sweep smoke test. Only implements the
    signal-scoring logic and respects the main configurable parameters.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.rsi9_long_min = self.config.get("rsi9_long_min", 30)
        self.rsi9_long_max = self.config.get("rsi9_long_max", 62)
        self.rsi14_long_min = self.config.get("rsi14_long_min", 30)
        self.rsi14_long_max = self.config.get("rsi14_long_max", 62)
        self.rsi9_short_min = self.config.get("rsi9_short_min", 45)
        self.rsi9_short_max = self.config.get("rsi9_short_max", 73)
        self.rsi14_short_min = self.config.get("rsi14_short_min", 45)
        self.rsi14_short_max = self.config.get("rsi14_short_max", 73)
        # Lower default confirmations to 2
        self.min_confirmations = self.config.get("min_confirmations", 2)
        self.position_size_multiplier = self.config.get("position_size_multiplier", 1.2)
        self.take_profit_multiplier = self.config.get("take_profit_multiplier", 1.5)
        self.trailing_stop_distance = self.config.get("trailing_stop_distance", 1.5)

    def generate_signal(self, df: pd.DataFrame, indicators: dict) -> dict:
        try:
            rsi9 = float(indicators.get("rsi_9", indicators.get("rsi9", np.nan)))
            rsi14 = float(indicators.get("rsi_14", indicators.get("rsi14", np.nan)))
            ema21 = float(indicators.get("ema_21", np.nan))
            macd_hist = float(indicators.get("macd_hist", 0.0))
            volume = float(df["volume"].iloc[-1]) if "volume" in df.columns else None
            avg_volume = df["volume"].rolling(20).mean().iloc[-1] if "volume" in df.columns else None
            close = float(df["close"].iloc[-1])

            long_score = 0
            if not np.isnan(rsi9) and self.rsi9_long_min <= rsi9 <= self.rsi9_long_max:
                long_score += 1
            if not np.isnan(rsi14) and self.rsi14_long_min <= rsi14 <= self.rsi14_long_max:
                long_score += 1
            if (not np.isnan(ema21)) and close > ema21:
                long_score += 1
            if macd_hist is not None and macd_hist > 0:
                long_score += 1
            if volume is not None and avg_volume is not None and avg_volume > 0 and volume > avg_volume:
                long_score += 1

            short_score = 0
            if not np.isnan(rsi9) and self.rsi9_short_min <= rsi9 <= self.rsi9_short_max:
                short_score += 1
            if not np.isnan(rsi14) and self.rsi14_short_min <= rsi14 <= self.rsi14_short_max:
                short_score += 1
            if (not np.isnan(ema21)) and close < ema21:
                short_score += 1
            if macd_hist is not None and macd_hist < 0:
                short_score += 1
            if volume is not None and avg_volume is not None and avg_volume > 0 and volume > avg_volume:
                short_score += 1

            if long_score >= self.min_confirmations and long_score >= short_score:
                return {
                    "signal": "BUY",
                    "confidence": long_score / 5.0,
                    "reason": f"ApexTrend BUY: {long_score}/5",
                }
            if short_score >= self.min_confirmations and short_score > long_score:
                return {
                    "signal": "SELL",
                    "confidence": short_score / 5.0,
                    "reason": f"ApexTrend SELL: {short_score}/5",
                }
            return {"signal": "NONE", "confidence": 0.0, "reason": "insufficient"}
        except Exception as exc:
            return {"signal": "NONE", "confidence": 0.0, "reason": f"error:{exc}"}


# Use the lightweight local class in this script
ApexTrendStrategy = LocalApexTrendStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parameter_sweep")


def generate_synthetic_data(n=2000, seed=42):
    rng = np.random.default_rng(seed)
    # random walk log returns
    returns = rng.normal(loc=0.0002, scale=0.02, size=n)
    price = 100 * np.exp(np.cumsum(returns))
    df = pd.DataFrame(index=pd.date_range(end=datetime.utcnow(), periods=n, freq="1H"))
    df["open"] = price
    df["high"] = df["open"] * (1 + np.abs(rng.normal(0, 0.002, size=n)))
    df["low"] = df["open"] * (1 - np.abs(rng.normal(0, 0.002, size=n)))
    df["close"] = df["open"] * (1 + rng.normal(0, 0.001, size=n))
    df["volume"] = np.abs(rng.normal(1000, 300, size=n))
    return df


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=period - 1, adjust=False).mean()
    ma_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-12)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd_hist(df: pd.DataFrame):
    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return hist


def prepare_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi_9"] = compute_rsi(df["close"], period=9)
    df["rsi_14"] = compute_rsi(df["close"], period=14)
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["macd_hist"] = compute_macd_hist(df)
    return df


def simple_backtest(params: dict, data: pd.DataFrame) -> dict:
    """Run a simple event-driven backtest using ApexTrendStrategy signals.

    Rules (simplified for sweep):
      - Enter on `BUY` signal at next bar open when flat
      - Exit after fixed holding period (10 bars) or on opposite signal
      - Position returns recorded as pct returns
    """
    strat = ApexTrendStrategy(config=params)
    df = data.copy()
    df = prepare_indicators(df)

    in_pos = False
    entry_price = 0.0
    entry_idx = None
    returns = []
    holding_period = params.get("holding_period", 10)

    for i in range(50, len(df) - 1):
        window = df.iloc[: i + 1]
        indicators = {
            "rsi_9": window["rsi_9"].iloc[-1],
            "rsi_14": window["rsi_14"].iloc[-1],
            "ema_21": window["ema_21"].iloc[-1],
            "macd_hist": window["macd_hist"].iloc[-1],
        }
        sig = strat.generate_signal(window, indicators)
        if not in_pos and sig.get("signal") == "BUY":
            # enter at next open
            entry_price = df["open"].iloc[i + 1]
            entry_idx = i + 1
            in_pos = True
            continue

        if in_pos:
            # exit on opposite signal or after holding period
            if sig.get("signal") == "SELL":
                exit_price = df["open"].iloc[i + 1]
                returns.append((exit_price - entry_price) / entry_price)
                in_pos = False
                entry_price = 0.0
                entry_idx = None
                continue

            if (i + 1) - entry_idx >= holding_period:
                exit_price = df["open"].iloc[i + 1]
                returns.append((exit_price - entry_price) / entry_price)
                in_pos = False
                entry_price = 0.0
                entry_idx = None

    if not returns:
        # No trades: return neutral metrics
        return {
            "sharpe_ratio": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
        }

    arr = np.array(returns)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    profit_factor = wins.sum() / (abs(losses.sum()) + 1e-12) if losses.size > 0 else float("inf")
    win_rate = float(wins.size) / float(arr.size)
    sharpe = float(arr.mean() / (arr.std(ddof=1) + 1e-12))
    # naive max drawdown approximation on equity curve
    eq = np.cumsum(arr)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    max_dd = float(np.max(dd)) if dd.size else 0.0

    return {
        "sharpe_ratio": float(sharpe),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "max_drawdown": float(max_dd),
    }


def main():
    # Load historical data if available, else synthetic
    data_dir = os.path.join(os.getcwd(), "data")
    if os.path.isdir(data_dir):
        files = [f for f in os.listdir(data_dir) if f.lower().endswith(".csv")]
    else:
        files = []

    if files:
        df = pd.read_csv(os.path.join(data_dir, files[0]), parse_dates=[0], index_col=0)
        logger.info("Loaded %s", files[0])
    else:
        logger.info("No CSVs found in ./data — generating synthetic data for smoke test")
        df = generate_synthetic_data()

    # Ensure datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    param_grid = {
        "min_confirmations": [2, 3],
        "min_adx": [15, 18, 20, 25],
        "volume_threshold": [0.4, 0.6, 0.8],
        "rsi9_long_max": [62, 68],
        "holding_period": [5, 10],
    }

    optimizer = SimpleWalkForwardOptimizer(param_grid, config={"train_window_days": 90, "test_window_days": 30, "step_days": 30})

    result = optimizer.run(data=df, backtest_fn=simple_backtest)

    best = result.get_recommended_params()
    logger.info("Recommended params: %s", best)

    # Export aggregate grid results
    try:
        rows = []
        for w in result.windows:
            for combo, metrics in w.grid_results.items():
                row = dict(combo)
                row.update(metrics)
                rows.append(row)
        if rows:
            out = pd.DataFrame(rows)
            out.to_csv("parameter_sweep_results.csv", index=False)
            logger.info("Wrote parameter_sweep_results.csv")
    except Exception as e:
        logger.debug("Could not write per-combo results: %s", e)


if __name__ == "__main__":
    main()
