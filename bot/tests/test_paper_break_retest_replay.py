"""Detector replay timing and conservative fill tests with synthetic bars."""

from __future__ import annotations

import unittest
import json
from datetime import datetime

import pandas as pd

from bot.paper_break_retest_replay import replay_break_retest, replay_break_retest_holdout
from bot.unified_backtest_engine import UnifiedBacktestEngine


def _break_retest_bars(*, both_levels_touched: bool = False) -> pd.DataFrame:
    rows = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0}
        for _ in range(40)
    ]
    rows[-4] = {"open": 99.8, "high": 100.2, "low": 99.4, "close": 100.0, "volume": 100.0}
    rows[-2] = {"open": 100.5, "high": 103.0, "low": 100.4, "close": 102.0, "volume": 150.0}
    rows[-1] = {"open": 101.0, "high": 102.2, "low": 100.8, "close": 101.7, "volume": 120.0}
    rows.append({"open": 101.8, "high": 106.0, "low": 99.0 if both_levels_touched else 101.4,
                 "close": 105.0, "volume": 100.0})
    rows.append({"open": 105.0, "high": 106.0, "low": 104.0, "close": 105.0, "volume": 100.0})
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(rows), freq="h"))


class ReplayTests(unittest.TestCase):
    """Verify next-open entry, conservative ambiguity, and honest accounting."""

    def test_signal_enters_after_confirmation_bar(self) -> None:
        bars = _break_retest_bars()
        result = replay_break_retest(bars, symbol="BTC-USD")
        self.assertEqual(result["analysis"]["kind"], "detector_replay_only")
        self.assertFalse(result["analysis"]["live_readiness_granted"])
        self.assertEqual(result["analysis"]["signals"], 1)
        self.assertEqual(result["summary"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["entry_time"], bars.index[40].isoformat())
        self.assertEqual(result["trades"][0]["exit_reason"], "take_profit")
        self.assertIsNone(result["summary"]["profit_factor"])
        self.assertIsNone(result["summary"]["sharpe_ratio"])
        self.assertIsNone(result["monthly_returns"]["2026-01-31T00:00:00"])
        json.dumps(result, allow_nan=False)

    def test_stop_wins_when_bar_touches_both_levels(self) -> None:
        result = replay_break_retest(_break_retest_bars(both_levels_touched=True), symbol="BTC-USD")
        self.assertEqual(result["trades"][0]["exit_reason"], "stop_loss")
        self.assertLess(result["summary"]["total_pnl"], 0)

    def test_invalid_and_duplicate_bars_fail_before_simulation(self) -> None:
        bars = _break_retest_bars()
        bars.index = [bars.index[0]] * len(bars)
        with self.assertRaisesRegex(ValueError, "unique"):
            replay_break_retest(bars, symbol="BTC-USD")
        bars = _break_retest_bars()
        bars.iloc[0, bars.columns.get_loc("high")] = 98.0
        with self.assertRaisesRegex(ValueError, "inconsistent OHLC"):
            replay_break_retest(bars, symbol="BTC-USD")

    def test_open_position_keeps_allocated_capital_in_equity(self) -> None:
        engine = UnifiedBacktestEngine(initial_balance=1000.0, commission_pct=0.001, slippage_pct=0)
        when = datetime(2026, 1, 1)
        position_id = engine.open_position("BTC-USD", "long", 100.0, 1.0, 90.0, 120.0, when)
        self.assertIsNotNone(position_id)
        engine.update_equity_curve(when, {"BTC-USD": 110.0})
        self.assertAlmostEqual(engine.equity_curve[-1]["total_equity"], 1009.9)
        engine.close_position(position_id, 110.0, when)
        self.assertAlmostEqual(engine.current_balance, 1009.79)

    def test_holdout_uses_training_bars_only_as_warmup(self) -> None:
        signal_bars = _break_retest_bars()
        prefix = pd.DataFrame([signal_bars.iloc[0].to_dict()] * 60)
        bars = pd.concat([prefix, signal_bars.reset_index(drop=True)], ignore_index=True)
        bars.index = pd.date_range("2026-01-01", periods=len(bars), freq="h")
        result = replay_break_retest_holdout(bars, symbol="BTC-USD", holdout_fraction=0.30)
        self.assertEqual(result["analysis"]["kind"], "chronological_holdout_detector_replay_only")
        self.assertFalse(result["analysis"]["live_readiness_granted"])
        self.assertEqual(result["training"]["summary"]["total_trades"], 0)
        self.assertEqual(result["holdout"]["summary"]["total_trades"], 1)
        self.assertGreaterEqual(result["holdout"]["trades"][0]["entry_time"],
                                result["analysis"]["split_timestamp"])
        self.assertEqual(result["analysis"]["evidence_status"], "limited_sample")
        altered = bars.copy()
        split = result["analysis"]["training_bars"]
        altered.iloc[split:, altered.columns.get_loc("volume")] *= 10
        changed = replay_break_retest_holdout(altered, symbol="BTC-USD", holdout_fraction=0.30)
        self.assertEqual(result["training"], changed["training"])
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
