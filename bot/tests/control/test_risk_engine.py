"""
Unit tests for bot.control.risk_engine
========================================

Coverage:
  1. Position count limit
  2. Position size limit
  3. Daily loss limit
  4. Drawdown limit
  5. Correlation check
  6. Trade frequency (time between trades)
  7. Rule updates and Redis persistence
  8. Health / observability
  9. Singleton stability
"""

import time
import unittest
from unittest.mock import MagicMock

import numpy as np

from bot.control.risk_engine import (
    RiskEngine,
    RiskRules,
    get_risk_engine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_engine() -> RiskEngine:
    """Return a new, isolated RiskEngine (not the process singleton)."""
    return RiskEngine()


def _make_positions(n: int, size_usd: float = 100.0) -> list:
    return [{"symbol": f"COIN{i}-USD", "size_usd": size_usd} for i in range(n)]


def _make_returns(n: int = 50, seed: int = 42) -> list:
    np.random.seed(seed)
    return list(np.random.randn(n) * 0.01)


# ---------------------------------------------------------------------------
# 1. Position count limit
# ---------------------------------------------------------------------------

class TestPositionCountLimit(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh_engine()

    def test_below_limit_approved(self):
        positions = _make_positions(3)  # max default = 7
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=positions,
        )
        self.assertTrue(approved)

    def test_at_limit_rejected(self):
        positions = _make_positions(7)  # exactly at max
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=positions,
        )
        self.assertFalse(approved)
        self.assertTrue(any("position_count_limit" in n for n in notes))

    def test_above_limit_rejected(self):
        positions = _make_positions(10)
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=positions,
        )
        self.assertFalse(approved)

    def test_zero_positions_approved(self):
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        self.assertTrue(approved)


# ---------------------------------------------------------------------------
# 2. Position size limit
# ---------------------------------------------------------------------------

class TestPositionSizeLimit(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh_engine()

    def test_size_within_limit_approved(self):
        # 500 / 10_000 = 5% < 10% limit
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=500.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        self.assertTrue(approved)

    def test_size_exceeding_limit_rejected(self):
        # 1500 / 10_000 = 15% > 10% limit
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=1500.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        self.assertFalse(approved)
        self.assertTrue(any("position_size_limit" in n for n in notes))

    def test_size_exactly_at_limit_approved(self):
        # 1000 / 10_000 = 10% == 10% limit
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=1000.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        self.assertTrue(approved)

    def test_zero_portfolio_value_skips_size_check(self):
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=99999.0,
            portfolio_value_usd=0.0, current_positions=[],
        )
        self.assertTrue(approved)


# ---------------------------------------------------------------------------
# 3. Daily loss limit
# ---------------------------------------------------------------------------

class TestDailyLossLimit(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh_engine()

    def test_no_loss_approved(self):
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
            daily_pnl=0.0,
        )
        self.assertTrue(approved)

    def test_profit_approved(self):
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
            daily_pnl=+500.0,
        )
        self.assertTrue(approved)

    def test_loss_below_limit_approved(self):
        # -400 / 10_000 = 4% < 5% limit
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
            daily_pnl=-400.0,
        )
        self.assertTrue(approved)

    def test_loss_at_limit_rejected(self):
        # -500 / 10_000 = 5% == 5% limit
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
            daily_pnl=-500.0,
        )
        self.assertFalse(approved)
        self.assertTrue(any("daily_loss_limit" in n for n in notes))

    def test_loss_above_limit_rejected(self):
        # -800 / 10_000 = 8% > 5% limit
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
            daily_pnl=-800.0,
        )
        self.assertFalse(approved)


# ---------------------------------------------------------------------------
# 4. Drawdown limit
# ---------------------------------------------------------------------------

class TestDrawdownLimit(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh_engine()

    def test_no_drawdown_approved(self):
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
            peak_portfolio_value=10_000.0,
        )
        self.assertTrue(approved)

    def test_small_drawdown_approved(self):
        # (11_000 - 10_500) / 11_000 = 4.5% < 15%
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_500.0, current_positions=[],
            peak_portfolio_value=11_000.0,
        )
        self.assertTrue(approved)

    def test_drawdown_at_limit_rejected(self):
        # (10_000 - 8_500) / 10_000 = 15% == 15% limit
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=8_500.0, current_positions=[],
            peak_portfolio_value=10_000.0,
        )
        self.assertFalse(approved)
        self.assertTrue(any("drawdown_limit" in n for n in notes))

    def test_drawdown_above_limit_rejected(self):
        # (10_000 - 8_000) / 10_000 = 20% > 15%
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=8_000.0, current_positions=[],
            peak_portfolio_value=10_000.0,
        )
        self.assertFalse(approved)

    def test_no_peak_value_skips_drawdown_check(self):
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=5_000.0, current_positions=[],
            peak_portfolio_value=None,
        )
        self.assertTrue(approved)


# ---------------------------------------------------------------------------
# 5. Correlation check
# ---------------------------------------------------------------------------

class TestCorrelationCheck(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh_engine()

    def test_no_existing_positions_approved(self):
        returns = _make_returns(50)
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
            returns_series=returns,
        )
        self.assertTrue(approved)

    def test_uncorrelated_position_approved(self):
        np.random.seed(1)
        returns_new = list(np.random.randn(50) * 0.01)
        np.random.seed(99)
        returns_existing = list(np.random.randn(50) * 0.01)
        positions = [{"symbol": "ETH-USD", "size_usd": 100.0, "returns_series": returns_existing}]
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=positions,
            returns_series=returns_new,
        )
        self.assertTrue(approved)

    def test_highly_correlated_position_rejected(self):
        np.random.seed(42)
        base = list(np.random.randn(50) * 0.01)
        # Perfectly correlated (same series)
        positions = [{"symbol": "ETH-USD", "size_usd": 100.0, "returns_series": base}]
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=positions,
            returns_series=base,
        )
        self.assertFalse(approved)
        self.assertTrue(any("correlation_limit" in n for n in notes))

    def test_position_without_returns_series_skipped(self):
        returns = _make_returns(50)
        positions = [{"symbol": "ETH-USD", "size_usd": 100.0}]  # no returns_series
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=positions,
            returns_series=returns,
        )
        self.assertTrue(approved)

    def test_short_returns_series_skips_correlation(self):
        short_returns = [0.01, -0.01, 0.02]  # < 10 points
        positions = [{"symbol": "ETH-USD", "size_usd": 100.0, "returns_series": short_returns}]
        approved, notes = self.engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=positions,
            returns_series=short_returns,
        )
        self.assertTrue(approved)


# ---------------------------------------------------------------------------
# 6. Trade frequency (time between trades)
# ---------------------------------------------------------------------------

class TestTradeFrequency(unittest.TestCase):

    def test_first_trade_always_approved(self):
        engine = _fresh_engine()
        approved, notes = engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        self.assertTrue(approved)

    def test_immediate_second_trade_rejected(self):
        engine = _fresh_engine()
        # First trade
        engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        # Immediate second trade on same symbol
        approved, notes = engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        self.assertFalse(approved)
        self.assertTrue(any("trade_frequency_limit" in n for n in notes))

    def test_different_symbol_not_throttled(self):
        engine = _fresh_engine()
        engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        # Different symbol should not be throttled
        approved, notes = engine.validate_trade(
            symbol="ETH-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        self.assertTrue(approved)


# ---------------------------------------------------------------------------
# 7. Rule updates and Redis persistence
# ---------------------------------------------------------------------------

class TestRuleUpdates(unittest.TestCase):

    def test_update_rules_changes_limits(self):
        engine = _fresh_engine()
        engine.update_rules({"max_concurrent_positions": 2})
        rules = engine.get_rules()
        self.assertEqual(rules.max_concurrent_positions, 2)

    def test_updated_position_limit_enforced(self):
        engine = _fresh_engine()
        engine.update_rules({"max_concurrent_positions": 2})
        positions = _make_positions(2)
        approved, notes = engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=positions,
        )
        self.assertFalse(approved)

    def test_rules_stored_in_redis(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        engine = RiskEngine(redis_client=mock_redis)
        # Constructor should store rules
        mock_redis.set.assert_called_once()

    def test_rules_loaded_from_redis(self):
        import json
        rules_data = {
            "max_concurrent_positions":   3,
            "max_position_size_pct":      5.0,
            "max_daily_loss_pct":         3.0,
            "max_drawdown_pct":           10.0,
            "max_correlation":            0.70,
            "min_time_between_trades_ms": 2000,
        }
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(rules_data).encode()
        engine = RiskEngine(redis_client=mock_redis)
        rules = engine.get_rules()
        self.assertEqual(rules.max_concurrent_positions, 3)
        self.assertAlmostEqual(rules.max_position_size_pct, 5.0)

    def test_risk_rules_from_dict_roundtrip(self):
        rules = RiskRules(
            max_concurrent_positions=5,
            max_position_size_pct=8.0,
            max_daily_loss_pct=4.0,
            max_drawdown_pct=12.0,
            max_correlation=0.75,
            min_time_between_trades_ms=500,
        )
        d = rules.to_dict()
        restored = RiskRules.from_dict(d)
        self.assertEqual(restored.max_concurrent_positions, 5)
        self.assertAlmostEqual(restored.max_position_size_pct, 8.0)
        self.assertAlmostEqual(restored.max_correlation, 0.75)


# ---------------------------------------------------------------------------
# 8. Health / observability
# ---------------------------------------------------------------------------

class TestHealth(unittest.TestCase):

    def test_health_available_flag(self):
        engine = _fresh_engine()
        health = engine.get_health()
        self.assertTrue(health["available"])

    def test_health_contains_active_rules(self):
        engine = _fresh_engine()
        health = engine.get_health()
        self.assertIn("active_rules", health)
        self.assertIn("max_concurrent_positions", health["active_rules"])

    def test_health_enabled_flag(self):
        engine = _fresh_engine()
        health = engine.get_health()
        self.assertIn("enabled", health)


# ---------------------------------------------------------------------------
# 9. Singleton stability
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):

    def test_get_risk_engine_returns_same_instance(self):
        e1 = get_risk_engine()
        e2 = get_risk_engine()
        self.assertIs(e1, e2)

    def test_singleton_validates_trade(self):
        engine = get_risk_engine()
        approved, notes = engine.validate_trade(
            symbol="BTC-USD", side="buy", size_usd=100.0,
            portfolio_value_usd=10_000.0, current_positions=[],
        )
        # Should return a bool (may be True or False depending on state)
        self.assertIsInstance(approved, bool)


if __name__ == "__main__":
    unittest.main()
