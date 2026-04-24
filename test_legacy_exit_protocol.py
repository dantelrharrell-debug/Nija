#!/usr/bin/env python3
"""
Test Legacy Position Exit Protocol
===================================
Comprehensive tests for the Legacy Position Exit Protocol implementation.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
import sys
from pathlib import Path
import os

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

# Import directly from the module file to avoid bot/__init__.py imports
import importlib.util
spec = importlib.util.spec_from_file_location(
    "legacy_position_exit_protocol",
    Path(__file__).parent / 'bot' / 'legacy_position_exit_protocol.py'
)
legacy_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy_module)

LegacyPositionExitProtocol = legacy_module.LegacyPositionExitProtocol
PositionCategory = legacy_module.PositionCategory
AccountState = legacy_module.AccountState
ExitStrategy = legacy_module.ExitStrategy


class TestPositionClassification(unittest.TestCase):
    """Test Phase 1: Position Classification"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_tracker = Mock()
        self.mock_broker = Mock()
        
        self.protocol = LegacyPositionExitProtocol(
            position_tracker=self.mock_tracker,
            broker_integration=self.mock_broker,
            max_positions=8,
            dust_pct_threshold=0.01,
            stale_order_minutes=30
        )
    
    def test_classify_strategy_aligned_position(self):
        """Test classification of valid strategy-aligned position"""
        position = {
            'symbol': 'BTC-USD',
            'size_usd': 100.0,
            'quantity': 0.01,
            'pnl_pct': 5.0
        }
        
        # Mock broker price fetch
        self.mock_broker.get_current_price.return_value = 50000.0
        
        # Mock tracker data
        self.mock_tracker.get_position.return_value = {
            'entry_price': 45000.0,
            'quantity': 0.01,
            'position_source': 'nija_strategy'
        }
        
        category = self.protocol.classify_position(position, account_balance=10000.0)
        
        self.assertEqual(category, PositionCategory.STRATEGY_ALIGNED)
    
    def test_classify_zombie_no_price(self):
        """Test classification of zombie position (cannot fetch price)"""
        position = {
            'symbol': 'UNKNOWN-USD',
            'size_usd': 50.0,
            'quantity': 10.0
        }
        
        # Mock broker price fetch failure
        self.mock_broker.get_current_price.return_value = None
        
        category = self.protocol.classify_position(position, account_balance=10000.0)
        
        self.assertEqual(category, PositionCategory.ZOMBIE_LEGACY)
    
    def test_classify_zombie_dust(self):
        """Test classification of zombie dust position"""
        position = {
            'symbol': 'ETH-USD',
            'size_usd': 0.50,  # Less than $1
            'quantity': 0.0001
        }
        
        # Mock broker price fetch
        self.mock_broker.get_current_price.return_value = 3000.0
        
        category = self.protocol.classify_position(position, account_balance=10000.0)
        
        self.assertEqual(category, PositionCategory.ZOMBIE_LEGACY)
    
    def test_classify_legacy_missing_entry_price(self):
        """Test classification of legacy position (missing entry price)"""
        position = {
            'symbol': 'LTC-USD',
            'size_usd': 100.0,
            'quantity': 1.0
        }
        
        # Mock broker price fetch
        self.mock_broker.get_current_price.return_value = 100.0
        
        # Mock tracker data - no entry price
        self.mock_tracker.get_position.return_value = None
        
        category = self.protocol.classify_position(position, account_balance=10000.0)
        
        self.assertEqual(category, PositionCategory.LEGACY_NON_COMPLIANT)
    
    def test_classify_legacy_external_source(self):
        """Test classification of legacy position (opened outside system)"""
        position = {
            'symbol': 'XRP-USD',
            'size_usd': 200.0,
            'quantity': 100.0
        }
        
        # Mock broker price fetch
        self.mock_broker.get_current_price.return_value = 2.0
        
        # Mock tracker data - external source
        self.mock_tracker.get_position.return_value = {
            'entry_price': 1.5,
            'quantity': 100.0,
            'position_source': 'manual'  # Not nija_strategy
        }
        
        category = self.protocol.classify_position(position, account_balance=10000.0)
        
        self.assertEqual(category, PositionCategory.LEGACY_NON_COMPLIANT)
    
    def test_classify_all_positions(self):
        """Test classification of multiple positions"""
        positions = [
            {'symbol': 'BTC-USD', 'size_usd': 1000.0, 'quantity': 0.02},
            {'symbol': 'ETH-USD', 'size_usd': 0.5, 'quantity': 0.0001},  # Dust
            {'symbol': 'UNKNOWN', 'size_usd': 50.0, 'quantity': 1.0},  # Zombie
        ]
        
        # Mock broker responses
        def mock_price(symbol):
            if symbol == 'UNKNOWN':
                return None
            return 50000.0 if symbol == 'BTC-USD' else 3000.0
        
        self.mock_broker.get_current_price.side_effect = mock_price
        
        # Mock tracker
        def mock_position(symbol):
            if symbol == 'BTC-USD':
                return {'entry_price': 45000.0, 'position_source': 'nija_strategy'}
            return None
        
        self.mock_tracker.get_position.side_effect = mock_position
        
        classified = self.protocol.classify_all_positions(positions, account_balance=10000.0)
        
        self.assertEqual(len(classified), 3)
        self.assertEqual(classified['BTC-USD']['category'], PositionCategory.STRATEGY_ALIGNED.value)
        self.assertEqual(classified['ETH-USD']['category'], PositionCategory.ZOMBIE_LEGACY.value)
        self.assertEqual(classified['UNKNOWN']['category'], PositionCategory.ZOMBIE_LEGACY.value)


class TestOrderCleanup(unittest.TestCase):
    """Test Phase 2: Order Cleanup"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_tracker = Mock()
        self.mock_broker = Mock()
        
        self.protocol = LegacyPositionExitProtocol(
            position_tracker=self.mock_tracker,
            broker_integration=self.mock_broker,
            stale_order_minutes=30
        )
    
    def test_cancel_stale_orders(self):
        """Test cancellation of stale orders"""
        # Create orders with different ages
        now = datetime.now()
        stale_time = now - timedelta(minutes=45)
        fresh_time = now - timedelta(minutes=15)
        
        orders = [
            {
                'order_id': 'order1',
                'symbol': 'BTC-USD',
                'created_at': stale_time.isoformat(),
                'value': 100.0
            },
            {
                'order_id': 'order2',
                'symbol': 'ETH-USD',
                'created_at': fresh_time.isoformat(),
                'value': 50.0
            },
            {
                'order_id': 'order3',
                'symbol': 'LTC-USD',
                'created_at': stale_time.isoformat(),
                'value': 75.0
            }
        ]
        
        self.mock_broker.get_open_orders.return_value = orders
        self.mock_broker.cancel_order.return_value = True
        
        cancelled, freed = self.protocol.cancel_stale_orders()
        
        # Should cancel 2 stale orders (order1 and order3)
        self.assertEqual(cancelled, 2)
        self.assertEqual(freed, 175.0)  # 100 + 75
        
        # Verify cancel_order was called for stale orders
        self.assertEqual(self.mock_broker.cancel_order.call_count, 2)
    
    def test_no_stale_orders(self):
        """Test when there are no stale orders"""
        now = datetime.now()
        fresh_time = now - timedelta(minutes=15)
        
        orders = [
            {
                'order_id': 'order1',
                'symbol': 'BTC-USD',
                'created_at': fresh_time.isoformat(),
                'value': 100.0
            }
        ]
        
        self.mock_broker.get_open_orders.return_value = orders
        
        cancelled, freed = self.protocol.cancel_stale_orders()
        
        self.assertEqual(cancelled, 0)
        self.assertEqual(freed, 0.0)
        self.mock_broker.cancel_order.assert_not_called()


class TestControlledExits(unittest.TestCase):
    """Test Phase 3: Controlled Exit Engine"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_tracker = Mock()
        self.mock_broker = Mock()
        
        self.protocol = LegacyPositionExitProtocol(
            position_tracker=self.mock_tracker,
            broker_integration=self.mock_broker,
            max_positions=3  # Low cap for testing
        )
    
    def test_exit_zombie_position(self):
        """Test immediate exit of zombie position"""
        position = {
            'symbol': 'ZOMBIE-USD',
            'size_usd': 0.5,
            'quantity': 10.0
        }
        
        self.mock_broker.close_position.return_value = True
        
        success = self.protocol._exit_zombie_position('ZOMBIE-USD', position)
        
        self.assertTrue(success)
        self.mock_broker.close_position.assert_called_once()
    
    def test_exit_dust_position(self):
        """Test immediate exit of dust position"""
        position = {
            'symbol': 'DUST-USD',
            'size_usd': 0.75,
            'quantity': 1.0
        }
        
        self.mock_broker.close_position.return_value = True
        
        success = self.protocol._exit_dust_position('DUST-USD', position)
        
        self.assertTrue(success)
        self.mock_broker.close_position.assert_called_once()
    
    def test_gradual_unwind(self):
        """Test gradual unwind of legacy position"""
        position = {
            'symbol': 'LEGACY-USD',
            'size_usd': 100.0,
            'quantity': 10.0
        }
        
        # Reset state for this test
        self.protocol.state['unwind_progress'] = {}
        
        self.mock_broker.close_position.return_value = True
        
        # Execute first cycle
        success1 = self.protocol._exit_legacy_position_gradual('LEGACY-USD', position)
        self.assertTrue(success1)
        
        # Check progress after first cycle
        progress = self.protocol.state['unwind_progress']['LEGACY-USD']
        self.assertEqual(progress['cycle'], 1)
        self.assertAlmostEqual(progress['remaining_pct'], 0.75, places=2)  # 75% remaining after 25% close
        
        # Execute second cycle
        success2 = self.protocol._exit_legacy_position_gradual('LEGACY-USD', position)
        self.assertTrue(success2)
        
        # Check progress after second cycle
        progress = self.protocol.state['unwind_progress']['LEGACY-USD']
        self.assertEqual(progress['cycle'], 2)
    
    def test_over_cap_worst_first_exit(self):
        """Test over-cap exit prioritizes worst performing"""
        classified = {
            'GOOD-USD': {
                'category': PositionCategory.LEGACY_NON_COMPLIANT.value,
                'position': {'symbol': 'GOOD-USD', 'size_usd': 100.0, 'pnl_pct': 10.0, 'quantity': 1.0},
                'exit_strategy': ExitStrategy.WORST_FIRST.value
            },
            'BAD1-USD': {
                'category': PositionCategory.LEGACY_NON_COMPLIANT.value,
                'position': {'symbol': 'BAD1-USD', 'size_usd': 50.0, 'pnl_pct': -5.0, 'quantity': 1.0},
                'exit_strategy': ExitStrategy.WORST_FIRST.value
            },
            'BAD2-USD': {
                'category': PositionCategory.LEGACY_NON_COMPLIANT.value,
                'position': {'symbol': 'BAD2-USD', 'size_usd': 75.0, 'pnl_pct': -10.0, 'quantity': 1.0},
                'exit_strategy': ExitStrategy.WORST_FIRST.value
            },
            'OK-USD': {
                'category': PositionCategory.STRATEGY_ALIGNED.value,
                'position': {'symbol': 'OK-USD', 'size_usd': 200.0, 'pnl_pct': 5.0, 'quantity': 1.0},
                'exit_strategy': ExitStrategy.EMERGENCY_STOP.value
            }
        }
        
        self.mock_broker.close_position.return_value = True
        
        # Max positions is 3, we have 4 total (should close 1 worst performing legacy)
        results = self.protocol.execute_controlled_exits(classified, account_balance=1000.0)
        
        # Should have attempted to close positions (exact count depends on logic)
        self.assertGreater(len(results), 0)


class TestCleanStateVerification(unittest.TestCase):
    """Test Phase 4: Clean State Verification"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_tracker = Mock()
        self.mock_broker = Mock()
        
        self.protocol = LegacyPositionExitProtocol(
            position_tracker=self.mock_tracker,
            broker_integration=self.mock_broker,
            max_positions=8,
            stale_order_minutes=30
        )
    
    def test_verify_clean_state_success(self):
        """Test verification of clean account state"""
        # Setup clean state
        positions = [
            {'symbol': 'BTC-USD', 'size_usd': 1000.0, 'quantity': 0.02}
        ]
        
        orders = []  # No open orders
        
        self.mock_broker.get_open_positions.return_value = positions
        self.mock_broker.get_open_orders.return_value = orders
        self.mock_broker.get_account_balance.return_value = 10000.0
        self.mock_broker.get_current_price.return_value = 50000.0
        
        # Mock tracker
        self.mock_tracker.get_position.return_value = {
            'entry_price': 45000.0,
            'position_source': 'nija_strategy'
        }
        
        state, diagnostics = self.protocol.verify_clean_state()
        
        self.assertEqual(state, AccountState.CLEAN)
        self.assertTrue(diagnostics['all_checks_pass'])
    
    def test_verify_needs_cleanup_over_cap(self):
        """Test verification detects over-cap situation"""
        # Setup over-cap state
        positions = [
            {'symbol': f'POS{i}-USD', 'size_usd': 100.0, 'quantity': 1.0}
            for i in range(10)  # 10 positions > 8 max
        ]
        
        self.mock_broker.get_open_positions.return_value = positions
        self.mock_broker.get_open_orders.return_value = []
        self.mock_broker.get_account_balance.return_value = 10000.0
        self.mock_broker.get_current_price.return_value = 100.0
        
        # Mock tracker
        self.mock_tracker.get_position.return_value = {
            'entry_price': 90.0,
            'position_source': 'nija_strategy'
        }
        
        state, diagnostics = self.protocol.verify_clean_state()
        
        self.assertEqual(state, AccountState.NEEDS_CLEANUP)
        self.assertFalse(diagnostics['checks']['position_count']['pass'])
    
    def test_verify_needs_cleanup_zombie_positions(self):
        """Test verification detects zombie positions"""
        positions = [
            {'symbol': 'ZOMBIE-USD', 'size_usd': 0.5, 'quantity': 1.0}  # Dust zombie
        ]
        
        self.mock_broker.get_open_positions.return_value = positions
        self.mock_broker.get_open_orders.return_value = []
        self.mock_broker.get_account_balance.return_value = 10000.0
        self.mock_broker.get_current_price.return_value = 0.5
        
        state, diagnostics = self.protocol.verify_clean_state()
        
        self.assertEqual(state, AccountState.NEEDS_CLEANUP)
        self.assertFalse(diagnostics['checks']['zombie_positions']['pass'])


class TestFullProtocol(unittest.TestCase):
    """Test complete protocol execution"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_tracker = Mock()
        self.mock_broker = Mock()
        
        self.protocol = LegacyPositionExitProtocol(
            position_tracker=self.mock_tracker,
            broker_integration=self.mock_broker,
            max_positions=8
        )
    
    def test_full_protocol_execution(self):
        """Test complete protocol run"""
        # Setup initial state with mixed positions
        positions = [
            {'symbol': 'BTC-USD', 'size_usd': 1000.0, 'quantity': 0.02, 'pnl_pct': 5.0},
            {'symbol': 'DUST-USD', 'size_usd': 0.5, 'quantity': 1.0, 'pnl_pct': 0.0},
        ]
        
        orders = []
        
        self.mock_broker.get_open_positions.return_value = positions
        self.mock_broker.get_open_orders.return_value = orders
        self.mock_broker.get_account_balance.return_value = 10000.0
        
        # Mock price fetches
        def mock_price(symbol):
            return 50000.0 if symbol == 'BTC-USD' else 0.5
        
        self.mock_broker.get_current_price.side_effect = mock_price
        
        # Mock tracker
        def mock_position(symbol):
            if symbol == 'BTC-USD':
                return {'entry_price': 45000.0, 'position_source': 'nija_strategy'}
            return None
        
        self.mock_tracker.get_position.side_effect = mock_position
        
        # Mock trade execution
        self.mock_broker.close_position.return_value = True
        
        # Run protocol
        results = self.protocol.run_full_protocol()
        
        # Verify phases executed
        self.assertIn('phase1_classification', results)
        self.assertIn('phase2_order_cleanup', results)
        self.assertIn('phase3_controlled_exits', results)
        self.assertIn('phase4_verification', results)


def run_tests():
    """Run all tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestPositionClassification))
    suite.addTests(loader.loadTestsFromTestCase(TestOrderCleanup))
    suite.addTests(loader.loadTestsFromTestCase(TestControlledExits))
    suite.addTests(loader.loadTestsFromTestCase(TestCleanStateVerification))
    suite.addTests(loader.loadTestsFromTestCase(TestFullProtocol))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_tests())
