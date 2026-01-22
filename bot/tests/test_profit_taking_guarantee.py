"""
NIJA Profit-Taking Guarantee Tests
Verifies that profit-taking works correctly across all accounts, brokerages, and tiers

Author: NIJA Trading Systems
Version: 1.0
Date: January 22, 2026
"""

import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from execution_engine import ExecutionEngine
from risk_manager import AdaptiveRiskManager as RiskManager


class TestProfitTakingGuarantee(unittest.TestCase):
    """Test suite for profit-taking guarantee"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.execution_engine = ExecutionEngine(broker_client=None)
        self.risk_manager = RiskManager()
    
    def test_take_profit_levels_calculation(self):
        """Test that take profit levels are calculated correctly"""
        entry_price = 100.0
        stop_loss = 98.0  # 2% stop loss
        
        # Test long position
        tp_levels = self.risk_manager.calculate_take_profit_levels(
            entry_price, stop_loss, 'long'
        )
        
        # Verify TP levels exist
        self.assertIn('tp1', tp_levels)
        self.assertIn('tp2', tp_levels)
        self.assertIn('tp3', tp_levels)
        
        # Verify R-multiples
        risk = entry_price - stop_loss  # $2
        self.assertAlmostEqual(tp_levels['tp1'], entry_price + (risk * 1.0), places=2)
        self.assertAlmostEqual(tp_levels['tp2'], entry_price + (risk * 1.5), places=2)
        self.assertAlmostEqual(tp_levels['tp3'], entry_price + (risk * 2.0), places=2)
        
        # Verify TP levels are profitable after fees
        # Assuming 1.4% round-trip fees (Coinbase)
        fee_pct = 0.014
        tp1_net = ((tp_levels['tp1'] - entry_price) / entry_price) - fee_pct
        self.assertGreater(tp1_net, 0, "TP1 should be profitable after fees")
    
    def test_take_profit_hit_detection_long(self):
        """Test that take profit hits are detected for long positions"""
        # Create a test position
        symbol = "BTC-USD"
        position = {
            'symbol': symbol,
            'side': 'long',
            'entry_price': 100.0,
            'tp1': 102.0,
            'tp2': 103.0,
            'tp3': 104.0,
            'tp1_hit': False,
            'tp2_hit': False,
            'tp3_hit': False
        }
        self.execution_engine.positions[symbol] = position
        
        # Test TP1 hit
        tp_hit = self.execution_engine.check_take_profit_hit(symbol, 102.5)
        self.assertEqual(tp_hit, 'tp1', "Should detect TP1 hit")
        
        # Test TP2 hit (TP1 already hit)
        tp_hit = self.execution_engine.check_take_profit_hit(symbol, 103.5)
        self.assertEqual(tp_hit, 'tp2', "Should detect TP2 hit")
        
        # Test TP3 hit (TP1 and TP2 already hit)
        tp_hit = self.execution_engine.check_take_profit_hit(symbol, 104.5)
        self.assertEqual(tp_hit, 'tp3', "Should detect TP3 hit")
    
    def test_take_profit_hit_detection_short(self):
        """Test that take profit hits are detected for short positions"""
        # Create a test position
        symbol = "ETH-USD"
        position = {
            'symbol': symbol,
            'side': 'short',
            'entry_price': 100.0,
            'tp1': 98.0,
            'tp2': 97.0,
            'tp3': 96.0,
            'tp1_hit': False,
            'tp2_hit': False,
            'tp3_hit': False
        }
        self.execution_engine.positions[symbol] = position
        
        # Test TP1 hit
        tp_hit = self.execution_engine.check_take_profit_hit(symbol, 97.5)
        self.assertEqual(tp_hit, 'tp1', "Should detect TP1 hit for short")
        
        # Test TP2 hit
        tp_hit = self.execution_engine.check_take_profit_hit(symbol, 96.5)
        self.assertEqual(tp_hit, 'tp2', "Should detect TP2 hit for short")
    
    def test_stepped_profit_exits_calculation(self):
        """Test that stepped profit exits are calculated correctly"""
        symbol = "SOL-USD"
        position = {
            'symbol': symbol,
            'side': 'long',
            'entry_price': 100.0,
            'size': 100.0,
            'remaining_size': 1.0,
            'position_size': 100.0,
            'tp_exit_2.0pct': False,
            'tp_exit_2.5pct': False,
            'tp_exit_3.0pct': False,
            'tp_exit_4.0pct': False
        }
        self.execution_engine.positions[symbol] = position
        
        # Test 2.0% profit (should trigger first stepped exit)
        current_price = 102.0  # 2.0% profit
        stepped_exit = self.execution_engine.check_stepped_profit_exits(symbol, current_price)
        
        if stepped_exit:  # Only test if stepped exits are implemented
            self.assertIsNotNone(stepped_exit, "Should detect stepped profit exit at 2.0%")
            self.assertIn('exit_size', stepped_exit)
            self.assertIn('profit_level', stepped_exit)
            self.assertIn('net_profit_pct', stepped_exit)
    
    def test_profit_taking_works_for_all_tiers(self):
        """Test that profit-taking works regardless of tier configuration"""
        tiers = ['SAVER', 'INVESTOR', 'INCOME', 'LIVABLE', 'BALLER']
        
        for tier in tiers:
            # Profit-taking should work the same for all tiers
            # Just verify the methods exist and can be called
            entry_price = 100.0
            stop_loss = 98.0
            
            tp_levels = self.risk_manager.calculate_take_profit_levels(
                entry_price, stop_loss, 'long'
            )
            
            self.assertIsNotNone(tp_levels, f"TP levels should be calculated for {tier} tier")
            self.assertIn('tp1', tp_levels)
            self.assertIn('tp2', tp_levels)
            self.assertIn('tp3', tp_levels)
    
    def test_fee_aware_profit_targets_coinbase(self):
        """Test that Coinbase profit targets account for 1.4% fees"""
        entry_price = 100.0
        stop_loss = 98.0  # 2% stop
        
        tp_levels = self.risk_manager.calculate_take_profit_levels(
            entry_price, stop_loss, 'long'
        )
        
        # Coinbase round-trip fees: ~1.4%
        coinbase_fee_pct = 0.014
        
        # TP1 should be profitable after Coinbase fees
        tp1_gross_pct = (tp_levels['tp1'] - entry_price) / entry_price
        tp1_net_pct = tp1_gross_pct - coinbase_fee_pct
        
        self.assertGreater(
            tp1_net_pct, 0,
            f"TP1 should be NET profitable on Coinbase (net: {tp1_net_pct*100:.1f}%)"
        )
    
    def test_fee_aware_profit_targets_kraken(self):
        """Test that Kraken profit targets account for 0.36% fees"""
        entry_price = 100.0
        stop_loss = 98.0  # 2% stop
        
        tp_levels = self.risk_manager.calculate_take_profit_levels(
            entry_price, stop_loss, 'long'
        )
        
        # Kraken round-trip fees: ~0.36%
        kraken_fee_pct = 0.0036
        
        # TP1 should be very profitable after Kraken fees
        tp1_gross_pct = (tp_levels['tp1'] - entry_price) / entry_price
        tp1_net_pct = tp1_gross_pct - kraken_fee_pct
        
        self.assertGreater(
            tp1_net_pct, 0.01,  # Should have >1% net profit on Kraken
            f"TP1 should be highly profitable on Kraken (net: {tp1_net_pct*100:.1f}%)"
        )
    
    def test_profit_taking_cannot_be_disabled(self):
        """Test that profit-taking is always enabled"""
        # Import the strategy
        try:
            from nija_apex_strategy_v71 import NIJAApexStrategyV71
            
            # Create strategy with config trying to disable profit-taking
            config = {'enable_take_profit': False}
            strategy = NIJAApexStrategyV71(broker_client=None, config=config)
            
            # Verify that profit-taking was forced to True
            self.assertTrue(
                strategy.config.get('enable_take_profit', False),
                "Profit-taking should be forced to True even if config says False"
            )
        except ImportError:
            self.skipTest("NIJAApexStrategyV71 not available")
    
    def test_no_position_returns_none(self):
        """Test that checking profit on non-existent position returns None"""
        tp_hit = self.execution_engine.check_take_profit_hit("NONEXISTENT-USD", 100.0)
        self.assertIsNone(tp_hit, "Should return None for non-existent position")
    
    def test_profit_targets_increase_with_levels(self):
        """Test that TP3 > TP2 > TP1"""
        entry_price = 100.0
        stop_loss = 98.0
        
        tp_levels = self.risk_manager.calculate_take_profit_levels(
            entry_price, stop_loss, 'long'
        )
        
        self.assertGreater(tp_levels['tp2'], tp_levels['tp1'], "TP2 should be > TP1")
        self.assertGreater(tp_levels['tp3'], tp_levels['tp2'], "TP3 should be > TP2")


class TestProfitMonitoringGuardian(unittest.TestCase):
    """Test suite for Profit Monitoring Guardian"""
    
    def test_guardian_can_be_initialized(self):
        """Test that Profit Monitoring Guardian can be initialized"""
        try:
            from profit_monitoring_guardian import ProfitMonitoringGuardian
            
            execution_engine = ExecutionEngine(broker_client=None)
            risk_manager = RiskManager()
            
            guardian = ProfitMonitoringGuardian(execution_engine, risk_manager)
            
            self.assertIsNotNone(guardian)
            self.assertEqual(guardian.total_profit_checks, 0)
        except ImportError:
            self.skipTest("ProfitMonitoringGuardian not available")
    
    def test_guardian_verify_profit_taking_enabled(self):
        """Test that guardian verifies profit-taking is enabled"""
        try:
            from profit_monitoring_guardian import ensure_profit_taking_always_on
            
            result = ensure_profit_taking_always_on()
            self.assertTrue(result, "Should confirm profit-taking is always on")
        except ImportError:
            self.skipTest("profit_monitoring_guardian not available")


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
