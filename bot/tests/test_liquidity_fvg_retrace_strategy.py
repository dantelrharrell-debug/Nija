from __future__ import annotations

import unittest

import pandas as pd

from bot.control.strategy_detectors import DetectorContext, LiquidityFvgRetraceDetector
from bot.control.trading_context import TradingContext


def _context() -> DetectorContext:
    trading = TradingContext(
        user_id="lfr-user",
        trading_account_id="lfr-account",
        broker="paper",
        broker_account_id="paper-account",
        strategy_instance_id="LIQUIDITY_FVG_RETRACE",
        portfolio_id="lfr-portfolio",
        request_id="lfr-request",
        correlation_id="lfr-correlation",
        environment="backtest",
        mode="backtest",
    )
    return DetectorContext(
        symbol="BTC-USD",
        broker="paper",
        market_regime="trending",
        trading_context=trading,
    )


def _day_rows(start: str, *, open_: float, high: float, low: float, close: float) -> list[dict]:
    index = pd.date_range(start, periods=24, freq="1h", tz="UTC")
    rows = []
    for i, ts in enumerate(index):
        rows.append(
            {
                "timestamp": ts,
                "open": open_ if i == 0 else close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100.0,
            }
        )
    return rows


def _base_days(direction: str) -> list[dict]:
    if direction == "long":
        specs = [
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 105.0, 100.0, 104.0),
            (103.0, 106.0, 102.0, 105.0),
            (104.0, 108.0, 103.0, 107.0),
            (106.0, 110.0, 103.5, 108.0),
        ]
    else:
        specs = [
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 100.0, 95.0, 96.0),
            (97.0, 98.0, 94.0, 95.0),
            (96.0, 97.0, 92.0, 93.0),
            (94.0, 97.5, 90.0, 92.0),
        ]

    rows: list[dict] = []
    for day, (open_, high, low, close) in enumerate(specs):
        rows.extend(
            _day_rows(
                f"2026-09-{10 + day:02d}",
                open_=open_,
                high=high,
                low=low,
                close=close,
            )
        )
    return rows


def _frame(direction: str, *, include_sweep: bool = True, include_daily_fvg: bool = True) -> pd.DataFrame:
    rows = _base_days(direction)

    # Optional negative control: close the Daily imbalance before the setup day.
    if not include_daily_fvg:
        if direction == "long":
            for row in rows[-48:-24]:
                row["low"] = min(float(row["low"]), 101.5)
        else:
            for row in rows[-48:-24]:
                row["high"] = max(float(row["high"]), 98.5)

    current = pd.date_range("2026-09-17", periods=24, freq="1h", tz="UTC")
    if direction == "long":
        current_rows = [
            {
                "timestamp": ts,
                "open": 102.5,
                "high": 103.0,
                "low": 102.2,
                "close": 102.5,
                "volume": 100.0,
            }
            for ts in current
        ]
        current_rows[-4] = {
            "timestamp": current[-4],
            "open": 102.4,
            "high": 102.7,
            "low": 101.5 if include_sweep else 102.15,
            "close": 102.3,
            "volume": 140.0,
        }
        current_rows[-3] = {
            "timestamp": current[-3],
            "open": 102.3,
            "high": 104.8,
            "low": 102.2,
            "close": 104.5,
            "volume": 180.0,
        }
        current_rows[-2] = {
            "timestamp": current[-2],
            "open": 104.1,
            "high": 104.6,
            "low": 103.0,
            "close": 104.2,
            "volume": 130.0,
        }
        current_rows[-1] = {
            "timestamp": current[-1],
            "open": 103.3,
            "high": 103.5,
            "low": 102.95,
            "close": 103.1,
            "volume": 120.0,
        }
    else:
        current_rows = [
            {
                "timestamp": ts,
                "open": 97.5,
                "high": 97.8,
                "low": 97.2,
                "close": 97.5,
                "volume": 100.0,
            }
            for ts in current
        ]
        current_rows[-4] = {
            "timestamp": current[-4],
            "open": 97.6,
            "high": 98.5 if include_sweep else 97.85,
            "low": 97.3,
            "close": 97.7,
            "volume": 140.0,
        }
        current_rows[-3] = {
            "timestamp": current[-3],
            "open": 97.7,
            "high": 97.8,
            "low": 95.2,
            "close": 95.5,
            "volume": 180.0,
        }
        current_rows[-2] = {
            "timestamp": current[-2],
            "open": 95.9,
            "high": 97.0,
            "low": 95.4,
            "close": 95.8,
            "volume": 130.0,
        }
        current_rows[-1] = {
            "timestamp": current[-1],
            "open": 96.8,
            "high": 97.05,
            "low": 96.5,
            "close": 96.9,
            "volume": 120.0,
        }

    rows.extend(current_rows)
    frame = pd.DataFrame(rows).set_index("timestamp")
    return frame


class TestLiquidityFvgRetraceDetector(unittest.TestCase):
    def test_long_sequence_emits_exact_limit_stop_and_daily_target(self):
        signal = LiquidityFvgRetraceDetector().detect(_frame("long"), _context())

        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.metadata["liquidity_type"], "sell_side")
        self.assertEqual(signal.metadata["order_type"], "limit")
        self.assertEqual(signal.metadata["time_in_force"], "gtc")
        self.assertAlmostEqual(signal.metadata["limit_price"], 103.0)
        self.assertAlmostEqual(signal.entry_zone["high"], 103.0)
        self.assertLess(signal.suggested_stop, 101.5)
        self.assertAlmostEqual(signal.target_candidates[0], 110.0)
        self.assertEqual(signal.metadata["target_basis"], "previous_daily_high")
        self.assertIn("1h_fvg_retracement", signal.supporting_evidence)

    def test_short_sequence_emits_exact_limit_stop_and_daily_target(self):
        signal = LiquidityFvgRetraceDetector().detect(_frame("short"), _context())

        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "short")
        self.assertEqual(signal.metadata["liquidity_type"], "buy_side")
        self.assertEqual(signal.metadata["order_type"], "limit")
        self.assertAlmostEqual(signal.metadata["limit_price"], 97.0)
        self.assertAlmostEqual(signal.entry_zone["low"], 97.0)
        self.assertGreater(signal.suggested_stop, 98.5)
        self.assertAlmostEqual(signal.target_candidates[0], 90.0)
        self.assertEqual(signal.metadata["target_basis"], "previous_daily_low")
        self.assertIn("1h_fvg_retracement", signal.supporting_evidence)

    def test_missing_liquidity_sweep_fails_closed(self):
        self.assertIsNone(
            LiquidityFvgRetraceDetector().detect(
                _frame("long", include_sweep=False),
                _context(),
            )
        )

    def test_daily_fvg_must_remain_unmitigated_before_setup(self):
        self.assertIsNone(
            LiquidityFvgRetraceDetector().detect(
                _frame("long", include_daily_fvg=False),
                _context(),
            )
        )

    def test_timestamp_context_is_required(self):
        frame = _frame("long").reset_index(drop=True)
        self.assertIsNone(LiquidityFvgRetraceDetector().detect(frame, _context()))


if __name__ == "__main__":
    unittest.main()
