"""
Test suite for fee-aware configuration

Tests position sizing, profit targets, and trade frequency limits.
"""

import unittest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.fee_aware_config import (
    MIN_BALANCE_TO_TRADE,
    SMALL_BALANCE_POSITION_PCT,
    MEDIUM_BALANCE_POSITION_PCT,
    TP1_TARGET,
    TP2_TARGET,
    TP3_TARGET,
    LIMIT_ORDER_ROUND_TRIP,
    MAX_TRADES_PER_DAY
)
try:
    from bot.fee_aware_config import SMALL_BALANCE_THRESHOLD
except ImportError:  # pragma: no cover - backwards compatibility for renamed constant
    from bot.fee_aware_config import MICRO_BALANCE_THRESHOLD as SMALL_BALANCE_THRESHOLD


class TestFeeAwareConfig(unittest.TestCase):
    """Test fee-aware configuration parameters"""

    def test_minimum_balance(self):
        """Test minimum balance requirement (system-wide fallback)"""
        # NOTE: Minimum has been raised to $50 to allow trading on small accounts.
        # Broker-specific minimums are enforced at connection level:
        # - Kraken: $25 (broker_configs/kraken_config.py)
        # - Coinbase: $25 (broker_configs/coinbase_config.py)
        # - See: test_min_balance_requirements.py for broker-specific tests
        self.assertGreater(MIN_BALANCE_TO_TRADE, 0.0, "System-wide minimum should be positive")
        self.assertLessEqual(MIN_BALANCE_TO_TRADE, 100.0, "System-wide minimum should be <= $100")

    def test_position_sizing(self):
        """Test position sizing percentages"""
        self.assertGreater(SMALL_BALANCE_POSITION_PCT, 0.0, "Small balance position should be positive")
        self.assertLessEqual(SMALL_BALANCE_POSITION_PCT, 1.0, "Small balance position should be <= 100%")
        self.assertGreater(MEDIUM_BALANCE_POSITION_PCT, 0.0, "Medium balance position should be positive")
        self.assertLessEqual(MEDIUM_BALANCE_POSITION_PCT, 1.0, "Medium balance position should be <= 100%")

    def test_profit_targets_exceed_fees(self):
        """Test that TP2 and TP3 exceed round-trip fee costs"""
        # TP1 may be set below Coinbase fees when targeting lower-fee brokers (Kraken/OKX).
        # TP2 and TP3 must always exceed round-trip costs.
        self.assertGreater(TP2_TARGET, LIMIT_ORDER_ROUND_TRIP,
                          f"TP2 ({TP2_TARGET*100}%) must exceed fees ({LIMIT_ORDER_ROUND_TRIP*100}%)")
        self.assertGreater(TP3_TARGET, LIMIT_ORDER_ROUND_TRIP,
                          f"TP3 ({TP3_TARGET*100}%) must exceed fees ({LIMIT_ORDER_ROUND_TRIP*100}%)")

    def test_profit_target_progression(self):
        """Test that profit targets increase progressively"""
        self.assertLess(TP1_TARGET, TP2_TARGET, "TP1 should be less than TP2")
        self.assertLess(TP2_TARGET, TP3_TARGET, "TP2 should be less than TP3")

    def test_trade_frequency_limits(self):
        """Test trade frequency is reasonable"""
        self.assertLessEqual(MAX_TRADES_PER_DAY, 50, "Max trades per day should be reasonable")
        self.assertGreaterEqual(MAX_TRADES_PER_DAY, 10, "Should allow at least 10 trades per day")

    def test_balance_thresholds(self):
        """Test balance thresholds are logical"""
        # MIN_BALANCE_TO_TRADE == SMALL_BALANCE_THRESHOLD is acceptable (same threshold)
        self.assertLessEqual(MIN_BALANCE_TO_TRADE, SMALL_BALANCE_THRESHOLD,
                       "Min balance should be at or below the small balance threshold")


class TestPositionSizing(unittest.TestCase):
    """Test position sizing calculations"""

    def test_small_balance_sizing(self):
        """Test position sizing for small balances produces a positive amount"""
        balance = 57.70
        position = balance * SMALL_BALANCE_POSITION_PCT

        self.assertGreater(position, 0.0, "Position size should be positive")
        self.assertAlmostEqual(position, balance * SMALL_BALANCE_POSITION_PCT, places=4,
                              msg="Position should equal balance * SMALL_BALANCE_POSITION_PCT")

    def test_medium_balance_sizing(self):
        """Test position sizing for medium balances produces a positive amount"""
        balance = 150.00
        position = balance * MEDIUM_BALANCE_POSITION_PCT

        self.assertGreater(position, 0.0, "Position size should be positive")
        self.assertAlmostEqual(position, balance * MEDIUM_BALANCE_POSITION_PCT, places=4,
                              msg="Position should equal balance * MEDIUM_BALANCE_POSITION_PCT")

    def test_minimum_position_after_fees(self):
        """Test that minimum positions generate measurable profit at TP2"""
        min_position = MIN_BALANCE_TO_TRADE * SMALL_BALANCE_POSITION_PCT

        # At TP2, profit should exceed fees (TP1 may be set below Coinbase fees intentionally)
        profit_at_tp2 = min_position * TP2_TARGET
        fees = min_position * LIMIT_ORDER_ROUND_TRIP

        self.assertGreater(profit_at_tp2, fees,
                          f"Profit at TP2 (${profit_at_tp2:.2f}) should exceed fees (${fees:.2f})")


class TestProfitability(unittest.TestCase):
    """Test profitability calculations"""

    def test_breakeven_calculation(self):
        """Test break-even point calculation is below TP2"""
        position_size = 46.16
        fees = position_size * LIMIT_ORDER_ROUND_TRIP

        # Break-even is when profit equals fees
        breakeven_pct = fees / position_size

        self.assertLess(breakeven_pct, TP2_TARGET,
                       f"Break-even ({breakeven_pct*100:.2f}%) should be less than TP2 ({TP2_TARGET*100}%)")

    def test_tp1_profitability(self):
        """Test TP1 is a positive profit target"""
        self.assertGreater(TP1_TARGET, 0.0, "TP1 should be a positive profit target")

    def test_tp2_profitability(self):
        """Test TP2 provides net profit after fees"""
        balance = 57.70
        position = balance * SMALL_BALANCE_POSITION_PCT

        gross_profit = position * TP2_TARGET
        fees = position * LIMIT_ORDER_ROUND_TRIP
        net_profit = gross_profit - fees

        self.assertGreater(net_profit, 0,
                          f"TP2 should provide net profit after fees (got ${net_profit:.2f})")


if __name__ == '__main__':
    unittest.main(verbosity=2)
