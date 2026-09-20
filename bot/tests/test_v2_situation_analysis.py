import unittest
from types import SimpleNamespace

from bot.control.situation_analysis import SituationAnalysisEngine
from bot.control.trading_context import TradingContext


def _ctx(user="u1", account="a1"):
    return TradingContext(
        user_id=user,
        trading_account_id=account,
        broker="kraken",
        broker_account_id=f"k-{account}",
        strategy_instance_id="orb",
        portfolio_id=f"p-{account}",
        request_id=f"r-{account}",
        correlation_id=f"c-{account}",
        environment="paper",
        mode="paper",
        decision_id=f"d-{account}",
    )


def _regime(name="trending", confidence=0.8):
    return SimpleNamespace(
        regime=SimpleNamespace(value=name),
        confidence=confidence,
        volatility=0.02,
    )


class TestSituationAnalysis(unittest.TestCase):
    def setUp(self):
        self.engine = SituationAnalysisEngine()
        self.ctx = _ctx()

    def test_clear_situation_is_eligible(self):
        result = self.engine.assess(
            trading_context=self.ctx,
            regime_result=_regime(),
            positions=[],
            checks={"market_data_fresh": True, "broker_available": True, "spread_ok": True, "liquidity_ok": True},
            authoritative_position_proven=True,
        )
        self.assertTrue(result.eligible_for_strategy_evaluation)
        self.assertEqual(result.risk_state, "clear")

    def test_unproven_positions_fail_closed(self):
        result = self.engine.assess(
            trading_context=self.ctx,
            regime_result=_regime(),
            authoritative_position_proven=False,
        )
        self.assertFalse(result.eligible_for_strategy_evaluation)
        self.assertIn("authoritative_position_unproven", result.reasons)

    def test_stale_market_or_broker_failure_blocks(self):
        result = self.engine.assess(
            trading_context=self.ctx,
            regime_result=_regime(),
            checks={"market_data_fresh": False, "broker_available": False},
        )
        self.assertFalse(result.eligible_for_strategy_evaluation)
        self.assertIn("market_data_stale", result.reasons)
        self.assertIn("broker_unavailable", result.reasons)

    def test_foreign_position_is_not_counted(self):
        other = _ctx("u2", "a2")
        result = self.engine.assess(
            trading_context=self.ctx,
            regime_result=_regime(),
            positions=[{
                "user_id": other.user_id,
                "trading_account_id": other.trading_account_id,
                "broker": other.broker,
                "broker_account_id": other.broker_account_id,
            }],
        )
        self.assertTrue(result.eligible_for_strategy_evaluation)
        self.assertEqual(result.open_positions, 0)

    def test_unscoped_position_fails_closed(self):
        result = self.engine.assess(
            trading_context=self.ctx,
            regime_result=_regime(),
            positions=[{"symbol": "BTC-USD"}],
        )
        self.assertFalse(result.eligible_for_strategy_evaluation)
        self.assertIn("unscoped_position_record", result.reasons)

    def test_unknown_regime_blocks_strategy_evaluation(self):
        result = self.engine.assess(
            trading_context=self.ctx,
            regime_result=_regime("unknown", 0.0),
        )
        self.assertFalse(result.eligible_for_strategy_evaluation)
        self.assertIn("market_regime_unproven", result.reasons)


if __name__ == "__main__":
    unittest.main()
