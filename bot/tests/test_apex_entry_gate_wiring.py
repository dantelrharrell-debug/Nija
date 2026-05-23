import unittest
from unittest.mock import MagicMock
from types import SimpleNamespace


class TestApexEntryGateWiring(unittest.TestCase):
    def test_get_bid_ask_prices_reads_pricebook(self):
        try:
            from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
        except Exception as exc:
            self.skipTest(f"NIJAApexStrategyV71 unavailable: {exc}")
        strategy = object.__new__(NIJAApexStrategyV71)
        strategy.broker_client = MagicMock()
        strategy.broker_client.get_best_bid_ask.return_value = {
            "pricebooks": [
                {
                    "bids": [{"price": "100.0"}],
                    "asks": [{"price": "101.0"}],
                }
            ]
        }

        bid, ask = strategy._get_bid_ask_prices("BTC-USD")

        self.assertEqual(bid, 100.0)
        self.assertEqual(ask, 101.0)

    def test_check_kraken_confidence_blocks_low_confidence(self):
        try:
            from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
        except Exception as exc:
            self.skipTest(f"NIJAApexStrategyV71 unavailable: {exc}")
        strategy = object.__new__(NIJAApexStrategyV71)
        strategy.kraken_min_confidence = 0.5

        result = strategy._check_kraken_confidence("kraken", {"confidence": 0.4})

        self.assertEqual(
            result,
            {
                "action": "hold",
                "reason": "Kraken confidence 0.40 < 0.50",
                "filter_stage": "kraken_confidence",
            },
        )

    def test_check_kraken_confidence_soft_band_is_advisory(self):
        try:
            from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
        except Exception as exc:
            self.skipTest(f"NIJAApexStrategyV71 unavailable: {exc}")
        strategy = object.__new__(NIJAApexStrategyV71)
        strategy.kraken_min_confidence = 0.50
        strategy.kraken_confidence_soft_margin = 0.05

        result = strategy._check_kraken_confidence("kraken", {"confidence": 0.47})

        self.assertIsNone(result)

    def test_verify_trade_eligibility_blocks_wide_spread(self):
        try:
            import pandas as pd
            from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
        except Exception as exc:
            self.skipTest(f"APEX dependencies unavailable: {exc}")
        strategy = object.__new__(NIJAApexStrategyV71)
        strategy._get_broker_name = lambda: "coinbase"
        strategy.kraken_min_rsi = 28.0
        strategy.kraken_max_rsi = 72.0
        strategy.kraken_min_atr_pct = 0.4

        df = pd.DataFrame(
            {
                "close": [100.0, 100.0],
                "volume": [1000.0, 1000.0],
            }
        )
        indicators = {
            "rsi": pd.Series([50.0]),
            "atr": pd.Series([0.5]),
        }

        result = strategy.verify_trade_eligibility(
            "BTC-USD",
            df,
            indicators,
            "long",
            25.0,
            bid_price=100.0,
            ask_price=101.0,
        )

        self.assertFalse(result["eligible"])
        self.assertIn("Spread too wide", result["reason"])

    def test_verify_trade_eligibility_allows_borderline_spread_with_reduced_size(self):
        try:
            import pandas as pd
            from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
        except Exception as exc:
            self.skipTest(f"APEX dependencies unavailable: {exc}")
        strategy = object.__new__(NIJAApexStrategyV71)
        strategy._get_broker_name = lambda: "coinbase"
        strategy.kraken_min_rsi = 28.0
        strategy.kraken_max_rsi = 72.0
        strategy.kraken_min_atr_pct = 0.4

        df = pd.DataFrame(
            {
                "close": [100.0, 100.0],
                "volume": [1000.0, 1000.0],
            }
        )
        indicators = {
            "rsi": pd.Series([50.0]),
            "atr": pd.Series([0.5]),
        }

        # 0.80% spread: above 0.75% max but inside 0.90% soft limit.
        result = strategy.verify_trade_eligibility(
            "BTC-USD",
            df,
            indicators,
            "long",
            25.0,
            bid_price=100.0,
            ask_price=100.8,
        )

        self.assertTrue(result["eligible"])
        self.assertTrue(result["allow_with_reduced_size"])

    def test_entry_gate_min_score_relaxes_after_fallback_window(self):
        try:
            from bot.nija_apex_strategy_v71 import (
                NIJAApexStrategyV71,
                ENTRY_GATE_MIN_SCORE,
                ENTRY_GATE_SAFETY_FLOOR,
                ENTRY_GATE_FALLBACK_WINDOW_SECS,
            )
        except Exception as exc:
            self.skipTest(f"NIJAApexStrategyV71 unavailable: {exc}")
        strategy = object.__new__(NIJAApexStrategyV71)
        drought = SimpleNamespace(
            secs_since_last_trade=ENTRY_GATE_FALLBACK_WINDOW_SECS + 1,
            active=False,
            score_reduction=0.0,
        )

        effective_score = strategy._get_entry_gate_min_score(drought)

        self.assertEqual(effective_score, max(ENTRY_GATE_SAFETY_FLOOR, ENTRY_GATE_MIN_SCORE - 1))

    def test_entry_gate_min_score_respects_safety_floor_under_active_drought(self):
        try:
            from bot.nija_apex_strategy_v71 import (
                NIJAApexStrategyV71,
                ENTRY_GATE_SAFETY_FLOOR,
            )
        except Exception as exc:
            self.skipTest(f"NIJAApexStrategyV71 unavailable: {exc}")
        strategy = object.__new__(NIJAApexStrategyV71)
        drought = SimpleNamespace(
            secs_since_last_trade=10_000,
            active=True,
            score_reduction=10.0,
        )

        effective_score = strategy._get_entry_gate_min_score(drought)

        self.assertEqual(effective_score, ENTRY_GATE_SAFETY_FLOOR)
