"""
Test suite for fee-aware configuration

Tests position sizing, profit targets, and trade frequency limits.
"""

import unittest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fee_aware_config import (
    MIN_BALANCE_TO_TRADE,
    SMALL_BALANCE_THRESHOLD,
    SMALL_BALANCE_POSITION_PCT,
    MEDIUM_BALANCE_POSITION_PCT,
    TP1_TARGET,
    TP2_TARGET,
    TP3_TARGET,
    LIMIT_ORDER_ROUND_TRIP,
    MAX_TRADES_PER_DAY
)


class TestFeeAwareConfig(unittest.TestCase):
    """Test fee-aware configuration parameters"""
    
    def test_minimum_balance(self):
        """Test minimum balance requirement"""
        self.assertEqual(MIN_BALANCE_TO_TRADE, 2.0, "Minimum balance should be $2 (lowered to allow very small accounts)")
    
    def test_position_sizing(self):
        """Test position sizing percentages"""
        self.assertEqual(SMALL_BALANCE_POSITION_PCT, 0.50, "Small balance position should be 50%")
        self.assertEqual(MEDIUM_BALANCE_POSITION_PCT, 0.40, "Medium balance position should be 40%")
    
    def test_profit_targets_exceed_fees(self):
        """Test that profit targets exceed fee costs"""
        # All targets should be above round-trip fee cost
        self.assertGreater(TP1_TARGET, LIMIT_ORDER_ROUND_TRIP,
                          f"TP1 ({TP1_TARGET*100}%) must exceed fees ({LIMIT_ORDER_ROUND_TRIP*100}%)")
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
        self.assertLess(MIN_BALANCE_TO_TRADE, SMALL_BALANCE_THRESHOLD,
                       "Min balance should be less than small balance threshold")


class TestPositionSizing(unittest.TestCase):
    """Test position sizing calculations"""
    
    def test_small_balance_sizing(self):
        """Test position sizing for small balances"""
        balance = 57.70
        position = balance * SMALL_BALANCE_POSITION_PCT
        
        self.assertAlmostEqual(position, 28.85, places=2,
                              msg="$57.70 * 50% should equal $28.85")
    
    def test_medium_balance_sizing(self):
        """Test position sizing for medium balances"""
        balance = 150.00
        position = balance * MEDIUM_BALANCE_POSITION_PCT
        
        self.assertEqual(position, 60.00,
                        msg="$150 * 40% should equal $60")
    
    def test_minimum_position_after_fees(self):
        """Test that minimum positions are profitable after fees"""
        min_position = MIN_BALANCE_TO_TRADE * SMALL_BALANCE_POSITION_PCT
        
        # At minimum profit target, profit should exceed fees
        profit_at_tp1 = min_position * TP1_TARGET
        fees = min_position * LIMIT_ORDER_ROUND_TRIP
        
        self.assertGreater(profit_at_tp1, fees,
                          f"Profit at TP1 (${profit_at_tp1:.2f}) should exceed fees (${fees:.2f})")


class TestProfitability(unittest.TestCase):
    """Test profitability calculations"""
    
    def test_breakeven_calculation(self):
        """Test break-even point calculation"""
        position_size = 46.16
        fees = position_size * LIMIT_ORDER_ROUND_TRIP
        
        # Break-even is when profit equals fees
        breakeven_pct = fees / position_size
        
        self.assertLess(breakeven_pct, TP1_TARGET,
                       f"Break-even ({breakeven_pct*100:.2f}%) should be less than TP1 ({TP1_TARGET*100}%)")
    
    def test_tp1_profitability(self):
        """Test TP1 provides actual profit"""
        balance = 57.70
        position = balance * SMALL_BALANCE_POSITION_PCT  # 46.16
        
        # Profit at TP1
        gross_profit = position * TP1_TARGET  # 3% = $1.38
        fees = position * LIMIT_ORDER_ROUND_TRIP  # ~1% = ~$0.46
        net_profit = gross_profit - fees
        
        self.assertGreater(net_profit, 0,
                          f"TP1 should provide net profit (got ${net_profit:.2f})")
        self.assertGreater(net_profit, 0.50,
                          f"TP1 net profit should be meaningful (>${0.50}, got ${net_profit:.2f})")
    
    def test_tp2_profitability(self):
        """Test TP2 provides good profit"""
        balance = 57.70
        position = balance * SMALL_BALANCE_POSITION_PCT
        
        gross_profit = position * TP2_TARGET  # 5%
        fees = position * LIMIT_ORDER_ROUND_TRIP
        net_profit = gross_profit - fees
        
        self.assertGreater(net_profit, 1.00,
                          f"TP2 should provide >$1 profit (got ${net_profit:.2f})")


if __name__ == '__main__':
    unittest.main(verbosity=2)
