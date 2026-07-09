import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from bot import no_trade_watchdog_runtime_patch as ntw_patch
from bot.nija_core_loop import CycleSnapshot, NijaCoreLoop


def _sample_df(rows: int = 120) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "close": [100.0] * rows,
            "volume": [1000.0] * rows,
        }
    )


class TestTpeMinNotionalResolution(unittest.TestCase):
    def test_okx_tpe_allocated_capital_lifts_min_notional_and_executes(self) -> None:
        from bot import nija_core_loop as ncl

        df = _sample_df()

        class Broker:
            connected = True

            def get_candles(self, symbol, limit=200):
                return df

        class Apex:
            current_regime = "normal"
            broker_client = Broker()

            def calculate_indicators(self, frame):
                return {"adx": pd.Series([5.0] * len(frame)), "score_breakdown": {}}

            def check_market_filter(self, frame, indicators):
                return True, "uptrend", "ok"

            def _get_entry_type_for_regime(self, regime):
                return "swing"

            def _get_broker_name(self):
                return "okx"

            def analyze_market(self, frame, symbol, balance):
                return {
                    "action": "hold",
                    "reason": "BROKER_MIN_NOTIONAL_BLOCK broker=okx required=$10.00 computed_min_size=$7.35",
                    "position_size": 7.35,
                    "order_notional": 7.35,
                    "min_notional": 10.0,
                }

            def execute_action(self, analysis, symbol):
                self.last_execution = (analysis, symbol)
                return True

        class PassingAI:
            speed_ctrl = SimpleNamespace(interval=150)

            def evaluate_symbol(self, **kwargs):
                sym = kwargs["symbol"]
                return SimpleNamespace(
                    symbol=sym,
                    side="long",
                    composite_score=80.0,
                    threshold_used=10.0,
                    metadata={},
                    position_multiplier=1.0,
                )

            def _compute_composite(self, *args, **kwargs):
                return 80.0, {"composite_score": 80.0, "score_breakdown": {}}

            def rank_and_select(self, candidates, slots, regime):
                return list(candidates[:slots])

        with patch.object(ncl, "_TPE_AVAILABLE", True), patch.object(ncl, "_PMC_AVAILABLE", False):
            ntw_patch._STATE["execute_attempts"] = 0
            ntw_patch._STATE["execute_successes"] = 0
            ntw_patch._wrap_execute_action(Apex)

            apex = Apex()
            loop = NijaCoreLoop(apex, max_positions=1)
            loop._ai_engine = PassingAI()

            entries, blocked, scored, _gates = loop._phase3_scan_and_enter(
                broker=apex.broker_client,
                snapshot=CycleSnapshot(
                    balance=367.6,
                    current_regime="normal",
                    daily_pnl_usd=0.0,
                    open_positions=0,
                ),
                symbols=["AAVE-USD"],
                available_slots=1,
                zero_signal_streak=0,
            )

            self.assertEqual(scored, 1)
            self.assertEqual(blocked, 0)
            self.assertEqual(entries, 1)
            self.assertGreaterEqual(ntw_patch._STATE["execute_attempts"], 1)
            analysis, symbol = apex.last_execution
            self.assertEqual(symbol, "AAVE-USD")
            self.assertGreaterEqual(float(analysis["position_size"]), 10.0)
            self.assertGreaterEqual(float(analysis["order_notional"]), 10.0)
            self.assertGreaterEqual(float(analysis["capital_allocated"]), 18.38 - 1e-6)


if __name__ == "__main__":
    unittest.main()
