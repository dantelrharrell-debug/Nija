"""
Test suite for advanced trading integration
Tests progressive targets, exchange profiles, and capital allocation integration.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advanced_trading_integration import (
    AdvancedTradingManager,
    ExchangeType,
    validate_configuration
)


class TestConfigurationValidation(unittest.TestCase):
    """Test configuration validation"""
    
    def test_valid_configuration(self):
        """Test valid configuration passes"""
        is_valid, msg = validate_configuration(1000.0, 'conservative')
        self.assertTrue(is_valid)
        self.assertEqual(msg, "")
    
    def test_zero_capital(self):
        """Test zero capital is rejected"""
        is_valid, msg = validate_configuration(0, 'conservative')
        self.assertFalse(is_valid)
        self.assertIn("must be > 0", msg)
    
    def test_negative_capital(self):
        """Test negative capital is rejected"""
        is_valid, msg = validate_configuration(-100, 'conservative')
        self.assertFalse(is_valid)
        self.assertIn("must be > 0", msg)
    
    def test_invalid_strategy(self):
        """Test invalid allocation strategy is rejected"""
        is_valid, msg = validate_configuration(1000.0, 'invalid_strategy')
        self.assertFalse(is_valid)
        self.assertIn("Invalid allocation strategy", msg)
    
    def test_valid_strategies(self):
        """Test all valid strategies are accepted"""
        valid_strategies = ['conservative', 'risk_adjusted', 'equal_weight']
        for strategy in valid_strategies:
            is_valid, msg = validate_configuration(1000.0, strategy)
            self.assertTrue(is_valid, f"Strategy '{strategy}' should be valid")


class TestAdvancedTradingManager(unittest.TestCase):
    """Test Advanced Trading Manager"""
    
    def test_initialization_with_valid_config(self):
        """Test manager initializes with valid configuration"""
        manager = AdvancedTradingManager(1000.0, 'conservative')
        self.assertIsNotNone(manager.target_manager)
        self.assertIsNotNone(manager.risk_manager)
        self.assertIsNotNone(manager.capital_allocator)
    
    def test_initialization_with_invalid_capital(self):
        """Test manager raises ValueError with invalid capital"""
        with self.assertRaises(ValueError) as context:
            AdvancedTradingManager(0, 'conservative')
        self.assertIn("Invalid configuration", str(context.exception))
    
    def test_initialization_with_invalid_strategy(self):
        """Test manager raises ValueError with invalid strategy"""
        with self.assertRaises(ValueError) as context:
            AdvancedTradingManager(1000.0, 'invalid')
        self.assertIn("Invalid configuration", str(context.exception))
    
    def test_get_position_size_for_trade(self):
        """Test position size calculation"""
        manager = AdvancedTradingManager(1000.0, 'conservative')
        
        # Test position size calculation
        pos_size = manager.get_position_size_for_trade(
            ExchangeType.COINBASE,
            base_position_pct=0.05,
            signal_strength=0.8
        )
        
        # Position size should be positive
        self.assertGreater(pos_size, 0)
        # Position size should be reasonable (not exceed account balance)
        self.assertLess(pos_size, 1000.0)
    
    def test_get_stop_loss_for_trade(self):
        """Test stop-loss calculation"""
        manager = AdvancedTradingManager(1000.0, 'conservative')
        
        stop_loss = manager.get_stop_loss_for_trade(
            ExchangeType.COINBASE,
            base_stop_pct=-0.02
        )
        
        # Stop-loss should be a positive decimal (it's returned as absolute value)
        self.assertIsInstance(stop_loss, float)
        self.assertGreater(stop_loss, 0)
    
    def test_get_take_profit_targets(self):
        """Test take-profit target retrieval"""
        manager = AdvancedTradingManager(1000.0, 'conservative')
        
        targets = manager.get_take_profit_targets(ExchangeType.COINBASE)
        
        # Should return dictionary with expected keys
        self.assertIn('tp1', targets)
        self.assertIn('tp2', targets)
        self.assertIn('tp3', targets)
        self.assertIn('min_target', targets)
        
        # All targets should be positive
        self.assertGreater(targets['tp1'], 0)
        self.assertGreater(targets['tp2'], 0)
        self.assertGreater(targets['tp3'], 0)
    
    def test_record_completed_trade(self):
        """Test trade recording"""
        manager = AdvancedTradingManager(1000.0, 'conservative')
        
        # Should not raise exception
        manager.record_completed_trade(
            ExchangeType.COINBASE,
            profit_usd=10.0,
            is_win=True
        )
    
    def test_get_trading_limits_for_exchange(self):
        """Test trading limits retrieval"""
        manager = AdvancedTradingManager(1000.0, 'conservative')
        
        limits = manager.get_trading_limits_for_exchange(ExchangeType.COINBASE)
        
        # Should return dictionary with limits
        self.assertIsInstance(limits, dict)
        # Check for actual keys returned by the implementation
        self.assertIn('max_position_size_usd', limits)
        self.assertIn('min_position_size_usd', limits)


class TestExchangeTypes(unittest.TestCase):
    """Test exchange type enumeration"""
    
    def test_all_exchanges_defined(self):
        """Test all expected exchanges are defined"""
        expected_exchanges = ['COINBASE', 'BINANCE', 'OKX', 'KRAKEN', 'ALPACA']
        
        for exchange_name in expected_exchanges:
            self.assertTrue(
                hasattr(ExchangeType, exchange_name),
                f"Exchange {exchange_name} should be defined"
            )
    
    def test_exchange_values(self):
        """Test exchange values are lowercase"""
        for exchange in ExchangeType:
            self.assertEqual(
                exchange.value,
                exchange.value.lower(),
                f"Exchange value should be lowercase: {exchange.value}"
            )


class TestIntegrationScenarios(unittest.TestCase):
    """Test realistic integration scenarios"""
    
    def test_small_account_scenario(self):
        """Test with small account balance"""
        manager = AdvancedTradingManager(50.0, 'conservative')
        
        # Get position size for small account
        pos_size = manager.get_position_size_for_trade(
            ExchangeType.COINBASE,
            base_position_pct=0.05,
            signal_strength=1.0
        )
        
        # Position should be small but positive
        self.assertGreater(pos_size, 0)
        self.assertLess(pos_size, 50.0)
    
    def test_medium_account_scenario(self):
        """Test with medium account balance"""
        manager = AdvancedTradingManager(500.0, 'risk_adjusted')
        
        pos_size = manager.get_position_size_for_trade(
            ExchangeType.OKX,
            base_position_pct=0.05,
            signal_strength=0.9
        )
        
        self.assertGreater(pos_size, 0)
        self.assertLess(pos_size, 500.0)
    
    def test_large_account_scenario(self):
        """Test with large account balance"""
        manager = AdvancedTradingManager(10000.0, 'equal_weight')
        
        pos_size = manager.get_position_size_for_trade(
            ExchangeType.BINANCE,
            base_position_pct=0.03,
            signal_strength=0.95
        )
        
        # Position size should be non-negative (may be 0 if exchange not in allocation)
        self.assertGreaterEqual(pos_size, 0)
        if pos_size > 0:
            self.assertLess(pos_size, 10000.0)
    
    def test_multiple_exchanges(self):
        """Test trading across multiple exchanges"""
        manager = AdvancedTradingManager(1000.0, 'conservative')
        
        # Use only exchanges that are included in conservative allocation (Coinbase and OKX)
        exchanges = [ExchangeType.COINBASE, ExchangeType.OKX]
        
        for exchange in exchanges:
            pos_size = manager.get_position_size_for_trade(
                exchange,
                base_position_pct=0.05,
                signal_strength=0.8
            )
            
            # Each exchange should return valid position size
            self.assertGreater(pos_size, 0, f"{exchange.value} should have positive position size")
            self.assertLess(pos_size, 1000.0)


if __name__ == '__main__':
    unittest.main()
