#!/usr/bin/env python3
"""
Tests for Broker Dust Cleanup, Enhanced Balance Fetcher, Symbol Freeze Manager
===============================================================================
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bot.broker_dust_cleanup import BrokerDustCleanup, DustPosition, get_broker_dust_cleanup
from bot.enhanced_balance_fetcher import EnhancedBalanceFetcher, get_enhanced_balance_fetcher
from bot.symbol_freeze_manager import SymbolFreezeManager, SymbolFreezeInfo, get_symbol_freeze_manager


class TestBrokerDustCleanup(unittest.TestCase):
    """Test broker-level dust position cleanup"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.cleanup = BrokerDustCleanup(dust_threshold_usd=1.00, dry_run=True)
        self.mock_broker = Mock()
    
    def test_initialization(self):
        """Test cleanup engine initialization"""
        self.assertEqual(self.cleanup.dust_threshold_usd, 1.00)
        self.assertTrue(self.cleanup.dry_run)
    
    def test_find_dust_positions_empty(self):
        """Test finding dust positions when there are none"""
        self.mock_broker.get_positions.return_value = []
        
        dust_positions = self.cleanup.find_dust_positions(self.mock_broker)
        
        self.assertEqual(len(dust_positions), 0)
    
    def test_find_dust_positions_with_dust(self):
        """Test finding dust positions"""
        # Mock positions
        self.mock_broker.get_positions.return_value = [
            {'symbol': 'BTC-USD', 'quantity': 0.0001, 'currency': 'BTC'},  # $5 (not dust)
            {'symbol': 'ETH-USD', 'quantity': 0.0002, 'currency': 'ETH'},  # $0.50 (dust)
            {'symbol': 'DOGE-USD', 'quantity': 5.0, 'currency': 'DOGE'},  # $0.75 (dust)
        ]
        
        # Mock prices
        def mock_get_price(symbol):
            prices = {
                'BTC-USD': 50000.0,  # 0.0001 * 50000 = $5.00
                'ETH-USD': 2500.0,   # 0.0002 * 2500 = $0.50
                'DOGE-USD': 0.15     # 5.0 * 0.15 = $0.75
            }
            return prices.get(symbol, 0)
        
        self.mock_broker.get_current_price.side_effect = mock_get_price
        
        dust_positions = self.cleanup.find_dust_positions(self.mock_broker)
        
        # Should find 2 dust positions (ETH-USD and DOGE-USD)
        self.assertEqual(len(dust_positions), 2)
        dust_symbols = [p.symbol for p in dust_positions]
        self.assertIn('ETH-USD', dust_symbols)
        self.assertIn('DOGE-USD', dust_symbols)
        self.assertNotIn('BTC-USD', dust_symbols)
    
    def test_close_dust_position_dry_run(self):
        """Test closing dust position in dry run mode"""
        dust_pos = DustPosition(
            symbol='ETH-USD',
            quantity=0.0002,
            usd_value=0.50,
            currency='ETH',
            source='broker'
        )
        
        success, message = self.cleanup.close_dust_position(self.mock_broker, dust_pos)
        
        self.assertTrue(success)
        self.assertIn("Dry run", message)
        # Should not call broker
        self.mock_broker.place_market_order.assert_not_called()
    
    def test_cleanup_all_dust(self):
        """Test full cleanup process"""
        # Setup mock positions
        self.mock_broker.get_positions.return_value = [
            {'symbol': 'ETH-USD', 'quantity': 0.0002, 'currency': 'ETH'},
        ]
        self.mock_broker.get_current_price.return_value = 2500.0  # $0.50 position
        
        result = self.cleanup.cleanup_all_dust(self.mock_broker)
        
        self.assertEqual(result['total_found'], 1)
        self.assertEqual(result['closed'], 1)  # Dry run counts as success
        self.assertEqual(result['failed'], 0)


class TestEnhancedBalanceFetcher(unittest.TestCase):
    """Test enhanced balance fetching with retry logic"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.fetcher = EnhancedBalanceFetcher(max_attempts=3, base_delay=0.1)  # Fast delays for testing
        self.mock_broker = Mock()
    
    def test_initialization(self):
        """Test fetcher initialization"""
        self.assertEqual(self.fetcher.max_attempts, 3)
        self.assertEqual(self.fetcher.base_delay, 0.1)
        self.assertIsNone(self.fetcher._last_known_balance)
    
    def test_successful_balance_fetch(self):
        """Test successful balance fetch on first attempt"""
        self.mock_broker.get_account_balance.return_value = 1000.0
        
        balance = self.fetcher.get_balance_with_retry(self.mock_broker, verbose=False)
        
        self.assertEqual(balance, 1000.0)
        self.assertEqual(self.fetcher._last_known_balance, 1000.0)
        self.assertEqual(self.fetcher._consecutive_errors, 0)
    
    def test_retry_on_failure(self):
        """Test retry logic when first attempt fails"""
        # First call fails, second succeeds
        self.mock_broker.get_account_balance.side_effect = [
            Exception("Network error"),
            1000.0
        ]
        
        balance = self.fetcher.get_balance_with_retry(self.mock_broker, verbose=False)
        
        self.assertEqual(balance, 1000.0)
        self.assertEqual(self.mock_broker.get_account_balance.call_count, 2)
    
    def test_fallback_to_last_known_balance(self):
        """Test fallback to last known balance after all retries fail"""
        # Set a known balance first
        self.fetcher._last_known_balance = 500.0
        self.fetcher._last_balance_time = datetime.now()
        
        # All attempts fail
        self.mock_broker.get_account_balance.side_effect = Exception("Network error")
        
        balance = self.fetcher.get_balance_with_fallback(self.mock_broker, verbose=False)
        
        self.assertEqual(balance, 500.0)
        self.assertEqual(self.mock_broker.get_account_balance.call_count, 3)
    
    def test_no_fallback_when_no_cached_balance(self):
        """Test behavior when no cached balance is available"""
        # All attempts fail and no cached balance
        self.mock_broker.get_account_balance.side_effect = Exception("Network error")
        
        balance = self.fetcher.get_balance_with_fallback(self.mock_broker, verbose=False)
        
        self.assertEqual(balance, 0.0)
    
    def test_get_last_known_balance(self):
        """Test getting last known balance info"""
        self.fetcher._last_known_balance = 1000.0
        self.fetcher._last_balance_time = datetime.now()
        
        info = self.fetcher.get_last_known_balance()
        
        self.assertIsNotNone(info)
        self.assertEqual(info['balance'], 1000.0)
        self.assertIn('timestamp', info)
        self.assertIn('age_seconds', info)


class TestSymbolFreezeManager(unittest.TestCase):
    """Test symbol freeze manager"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Use a temporary directory for testing
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SymbolFreezeManager(
            failure_threshold=3,
            cooldown_hours=24.0,
            data_dir=self.temp_dir
        )
    
    def tearDown(self):
        """Clean up temp directory"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_initialization(self):
        """Test manager initialization"""
        self.assertEqual(self.manager.failure_threshold, 3)
        self.assertEqual(self.manager.cooldown_hours, 24.0)
        self.assertEqual(len(self.manager._frozen_symbols), 0)
    
    def test_record_price_fetch_failure(self):
        """Test recording price fetch failures"""
        symbol = 'AUT-USD'
        
        # First failure
        frozen = self.manager.record_price_fetch_failure(symbol, "Price not available")
        self.assertFalse(frozen)
        self.assertEqual(self.manager.get_failure_count(symbol), 1)
        
        # Second failure
        frozen = self.manager.record_price_fetch_failure(symbol, "Price not available")
        self.assertFalse(frozen)
        self.assertEqual(self.manager.get_failure_count(symbol), 2)
        
        # Third failure - should freeze
        frozen = self.manager.record_price_fetch_failure(symbol, "Price not available")
        self.assertTrue(frozen)
        self.assertTrue(self.manager.is_frozen(symbol))
    
    def test_record_price_fetch_success(self):
        """Test recording successful price fetch resets counter"""
        symbol = 'BTC-USD'
        
        # Record some failures
        self.manager.record_price_fetch_failure(symbol, "Error")
        self.manager.record_price_fetch_failure(symbol, "Error")
        self.assertEqual(self.manager.get_failure_count(symbol), 2)
        
        # Success should reset counter
        self.manager.record_price_fetch_success(symbol)
        self.assertEqual(self.manager.get_failure_count(symbol), 0)
    
    def test_is_frozen(self):
        """Test checking if symbol is frozen"""
        symbol = 'TEST-USD'
        
        # Not frozen initially
        self.assertFalse(self.manager.is_frozen(symbol))
        
        # Freeze it
        for _ in range(3):
            self.manager.record_price_fetch_failure(symbol, "Error")
        
        # Should be frozen now
        self.assertTrue(self.manager.is_frozen(symbol))
    
    def test_unfreeze_symbol(self):
        """Test manually unfreezing a symbol"""
        symbol = 'TEST-USD'
        
        # Freeze it first
        for _ in range(3):
            self.manager.record_price_fetch_failure(symbol, "Error")
        self.assertTrue(self.manager.is_frozen(symbol))
        
        # Unfreeze it
        success = self.manager.unfreeze_symbol(symbol, "Manual unfreeze for testing")
        self.assertTrue(success)
        self.assertFalse(self.manager.is_frozen(symbol))
    
    def test_get_frozen_symbols(self):
        """Test getting all frozen symbols"""
        # Freeze multiple symbols
        for symbol in ['AUT-USD', 'BAD-USD', 'FAIL-USD']:
            for _ in range(3):
                self.manager.record_price_fetch_failure(symbol, "Error")
        
        frozen = self.manager.get_frozen_symbols()
        self.assertEqual(len(frozen), 3)
        self.assertIn('AUT-USD', frozen)
        self.assertIn('BAD-USD', frozen)
        self.assertIn('FAIL-USD', frozen)
    
    def test_get_stats(self):
        """Test getting freeze manager statistics"""
        # Freeze a symbol
        for _ in range(3):
            self.manager.record_price_fetch_failure('AUT-USD', "Error")
        
        # Add some failures to another symbol
        self.manager.record_price_fetch_failure('BTC-USD', "Error")
        
        stats = self.manager.get_stats()
        
        self.assertEqual(stats['frozen_count'], 1)
        # Note: symbols_with_failures includes both frozen and unfrozen symbols
        self.assertEqual(stats['symbols_with_failures'], 2)  # AUT-USD (frozen) + BTC-USD (pending)
        self.assertIn('AUT-USD', stats['frozen_symbols'])
        self.assertEqual(len(stats['pending_freeze']), 1)  # Only BTC-USD is pending


if __name__ == '__main__':
    # Run tests
    unittest.main()
