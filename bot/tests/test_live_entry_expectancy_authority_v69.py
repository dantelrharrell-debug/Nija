from __future__ import annotations

import importlib
import os
import types
import unittest
from unittest.mock import patch

import pandas as pd


class _Validator:
    def __init__(self, r_ok=True, confirm_ok=True, r=2.0) -> None:
        self.r_ok = r_ok
        self.confirm_ok = confirm_ok
        self.r = r

    def validate_r_multiple(self, entry, stop, target):
        return self.r_ok, "r-check", self.r

    def check_first_move_confirmation(self, df):
        return self.confirm_ok, "volume expansion" if self.confirm_ok else "no expansion"


class _Broker:
    broker_type = "futurebroker"
    taker_fee = 0.001


class _Strategy:
    broker_client = _Broker()

    def _get_broker_name(self):
        return "futurebroker"


class LiveEntryExpectancyAuthorityV69Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.live_entry_expectancy_authority_v69_patch")
        self.df = pd.DataFrame(
            {
                "open": [99.0] * 25,
                "high": [101.0] * 25,
                "low": [98.0] * 25,
                "close": [100.0] * 25,
                "volume": [100.0] * 24 + [160.0],
            }
        )
        self.result = {
            "action": "enter_long",
            "entry_price": 100.0,
            "stop_loss": 99.0,
            "take_profit": [102.0],
        }

    def test_non_entry_is_unchanged(self) -> None:
        ok, reason, details = self.mod._validate_live_entry(
            _Strategy(), self.df, "BTC-USD", {"action": "hold"}
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "not_entry")
        self.assertEqual(details, {})

    def test_r_multiple_failure_blocks_entry(self) -> None:
        with patch.object(self.mod, "_validator", return_value=_Validator(r_ok=False, r=1.0)):
            ok, reason, _details = self.mod._validate_live_entry(
                _Strategy(), self.df, "BTC-USD", self.result
            )
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("expectancy_r_multiple"))

    def test_first_move_confirmation_failure_blocks_entry(self) -> None:
        with patch.object(self.mod, "_validator", return_value=_Validator(confirm_ok=False)):
            ok, reason, _details = self.mod._validate_live_entry(
                _Strategy(), self.df, "BTC-USD", self.result
            )
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("first_move_confirmation"))

    def test_net_edge_after_fees_must_clear_minimum(self) -> None:
        expensive = types.SimpleNamespace(
            broker_type="expensive",
            taker_fee=0.009,
        )
        strategy = _Strategy()
        strategy.broker_client = expensive
        strategy._get_broker_name = lambda: "expensive"
        with patch.object(self.mod, "_validator", return_value=_Validator()):
            with patch.dict(
                os.environ,
                {
                    "NIJA_ENTRY_SPREAD_RESERVE_PCT": "0",
                    "NIJA_ENTRY_SLIPPAGE_RESERVE_PCT": "0.001",
                    "NIJA_MINIMUM_NET_PROFIT_PCT": "0.004",
                },
                clear=False,
            ):
                ok, reason, details = self.mod._validate_live_entry(
                    strategy, self.df, "BTC-USD", self.result
                )
        self.assertFalse(ok)
        self.assertEqual(reason, "net_edge_below_fee_slippage_floor")
        self.assertLess(details["net_reward_pct"], details["minimum_net_pct"])

    def test_good_geometry_confirmation_and_net_edge_pass(self) -> None:
        with patch.object(self.mod, "_validator", return_value=_Validator(r_ok=True, confirm_ok=True, r=2.0)):
            with patch.dict(
                os.environ,
                {
                    "NIJA_ENTRY_SPREAD_RESERVE_PCT": "0",
                    "NIJA_ENTRY_SLIPPAGE_RESERVE_PCT": "0.001",
                    "NIJA_MINIMUM_NET_PROFIT_PCT": "0.004",
                },
                clear=False,
            ):
                ok, reason, details = self.mod._validate_live_entry(
                    _Strategy(), self.df, "BTC-USD", self.result
                )
        self.assertTrue(ok)
        self.assertEqual(reason, "expectancy_authority_pass")
        self.assertGreaterEqual(details["net_reward_pct"], details["minimum_net_pct"])

    def test_live_mode_does_not_use_drought_relaxation_or_debug_bypass(self) -> None:
        fake = types.ModuleType("apex_v69_fake")
        fake._DISABLE_MARKET_FILTER = True
        fake._BYPASS_SMART_FILTER = True
        fake.ENTRY_GATE_MIN_SCORE = 2

        class Apex:
            broker_client = _Broker()

            def _get_broker_name(self):
                return "futurebroker"

            def analyze_market(self, df, symbol, account_balance):
                return {"action": "hold"}

            def _get_entry_gate_thresholds(self, drought):
                return (0.01, 0.1, 0.0001) if drought is not None else (0.06, 1.5, 0.002)

            def _get_entry_gate_min_score(self, drought):
                return 1 if drought is not None else 2

        fake.NIJAApexStrategyV71 = Apex
        self.mod._patch_strategy(fake)
        instance = Apex()
        with patch.dict(
            os.environ,
            {"LIVE_CAPITAL_VERIFIED": "true", "DRY_RUN_MODE": "false", "PAPER_MODE": "false"},
            clear=False,
        ):
            self.assertEqual(instance._get_entry_gate_thresholds(object()), (0.06, 1.5, 0.002))
            self.assertEqual(instance._get_entry_gate_min_score(object()), 2)
            instance.analyze_market(self.df, "BTC-USD", 100.0)
        self.assertFalse(fake._DISABLE_MARKET_FILTER)
        self.assertFalse(fake._BYPASS_SMART_FILTER)


if __name__ == "__main__":
    unittest.main()
