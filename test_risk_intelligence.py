#!/usr/bin/env python3
"""
Test Risk Intelligence Features
================================
Tests for:
1. High-exposure asset monitoring
2. Risk intelligence gate
3. Integration features

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import pandas as pd
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

from bot.legacy_position_exit_protocol import (
    LegacyPositionExitProtocol,
    PositionCategory,
    AccountState
)
from bot.risk_intelligence_gate import RiskIntelligenceGate, create_risk_intelligence_gate


class TestHighExposureMonitoring(unittest.TestCase):
    """Test high-exposure asset monitoring features"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_tracker = Mock()
        self.mock_broker = Mock()
        
        self.protocol = LegacyPositionExitProtocol(
            position_tracker=self.mock_tracker,
            broker_integration=self.mock_broker,
            monitor_high_exposure=True
        )
    
    def test_high_exposure_asset_classification(self):
        """Test that high-exposure assets are flagged as LEGACY_NON_COMPLIANT"""
        # Mock position tracker to return a tracked position
        self.mock_tracker.get_position.return_value = {
            'entry_price': 0.001,
            'position_source': 'nija_strategy'
        }
        
        # Mock price fetch
        self.mock_broker.get_current_price = Mock(return_value=0.0015)
        
        # Test PEPE position
        position = {
            'symbol': 'PEPE-USD',
            'size_usd': 100.0,
            'quantity': 100000
        }
        
        category = self.protocol.classify_position(position, account_balance=1000.0)
        
        # Should be flagged as LEGACY_NON_COMPLIANT
        self.assertEqual(category, PositionCategory.LEGACY_NON_COMPLIANT)
    
    def test_normal_asset_not_flagged(self):
        """Test that normal assets are not flagged as high-exposure"""
        # Mock position tracker
        self.mock_tracker.get_position.return_value = {
            'entry_price': 50000,
            'position_source': 'nija_strategy'
        }
        
        # Mock price fetch
        self.mock_broker.get_current_price = Mock(return_value=51000)
        
        # Test BTC position
        position = {
            'symbol': 'BTC-USD',
            'size_usd': 100.0,
            'quantity': 0.002
        }
        
        category = self.protocol.classify_position(position, account_balance=1000.0)
        
        # Should be strategy-aligned
        self.assertEqual(category, PositionCategory.STRATEGY_ALIGNED)
    
    def test_high_exposure_monitoring(self):
        """Test high-exposure asset monitoring method"""
        positions = [
            {'symbol': 'PEPE-USD', 'size_usd': 1500.0},  # 15% of account
            {'symbol': 'BTC-USD', 'size_usd': 2000.0},
            {'symbol': 'SHIB-USD', 'size_usd': 500.0}    # 5% of account
        ]
        
        account_balance = 10000.0
        
        result = self.protocol.monitor_high_exposure_assets(positions, account_balance)
        
        # Should track 2 high-exposure positions
        self.assertEqual(result['positions_tracked'], 2)
        
        # Should have alerts for oversized position (PEPE >10%)
        self.assertGreater(result['alert_count'], 0)
        
        # Check alert types
        alert_types = [alert['type'] for alert in result['alerts']]
        self.assertIn('OVERSIZED_HIGH_EXPOSURE', alert_types)
    
    def test_monitoring_disabled(self):
        """Test that monitoring can be disabled"""
        protocol_no_monitoring = LegacyPositionExitProtocol(
            position_tracker=self.mock_tracker,
            broker_integration=self.mock_broker,
            monitor_high_exposure=False
        )
        
        positions = [{'symbol': 'PEPE-USD', 'size_usd': 1500.0}]
        result = protocol_no_monitoring.monitor_high_exposure_assets(positions, 10000.0)
        
        self.assertFalse(result['enabled'])


class TestRiskIntelligenceGate(unittest.TestCase):
    """Test risk intelligence gate features"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.risk_gate = create_risk_intelligence_gate()
    
    def test_volatility_check_creation(self):
        """Test risk gate can be created"""
        self.assertIsInstance(self.risk_gate, RiskIntelligenceGate)
        self.assertEqual(self.risk_gate.max_volatility_multiplier, 3.0)
        self.assertEqual(self.risk_gate.max_correlation_exposure, 0.40)
    
    def test_volatility_check_without_sizer(self):
        """Test volatility check when sizer is not available"""
        df = pd.DataFrame({
            'open': [50000] * 100,
            'high': [51000] * 100,
            'low': [49000] * 100,
            'close': [50500] * 100
        })
        
        approved, details = self.risk_gate.check_volatility_before_entry(
            symbol='BTC-USD',
            df=df,
            proposed_position_size=500.0,
            account_balance=10000.0
        )
        
        # Without sizer, should skip check and approve
        self.assertTrue(approved)
        self.assertEqual(details['check'], 'skipped')
    
    def test_correlation_check_without_engine(self):
        """Test correlation check when engine is not available"""
        approved, details = self.risk_gate.check_correlation_before_entry(
            symbol='BTC-USD',
            proposed_position_size=500.0,
            current_positions=[],
            account_balance=10000.0
        )
        
        # Without engine, should skip check and approve
        self.assertTrue(approved)
        self.assertEqual(details['check'], 'skipped')
    
    def test_pre_trade_assessment(self):
        """Test complete pre-trade assessment"""
        df = pd.DataFrame({
            'open': [50000] * 100,
            'high': [51000] * 100,
            'low': [49000] * 100,
            'close': [50500] * 100
        })
        
        approved, assessment = self.risk_gate.pre_trade_risk_assessment(
            symbol='BTC-USD',
            df=df,
            proposed_position_size=500.0,
            current_positions=[],
            account_balance=10000.0
        )
        
        # Should have assessment results
        self.assertIn('checks', assessment)
        self.assertIn('volatility_scaling', assessment['checks'])
        self.assertIn('correlation_exposure', assessment['checks'])
        self.assertIn('approved', assessment)
        self.assertEqual(assessment['checks_total'], 2)
    
    def test_correlation_groups(self):
        """Test correlation group detection"""
        groups = self.risk_gate._get_correlation_groups()
        
        # Should have defined groups
        self.assertIn('BTC_RELATED', groups)
        self.assertIn('MEME_COINS', groups)
        self.assertIn('DEFI', groups)
        
        # PEPE should be in MEME_COINS
        self.assertIn('PEPE-USD', groups['MEME_COINS'])
        
        # BTC should be in BTC_RELATED
        self.assertIn('BTC-USD', groups['BTC_RELATED'])
    
    def test_asset_group_detection(self):
        """Test asset group detection"""
        groups = self.risk_gate._get_correlation_groups()
        
        # Test BTC
        btc_group = self.risk_gate._get_asset_group('BTC-USD', groups)
        self.assertEqual(btc_group, 'BTC_RELATED')
        
        # Test PEPE
        pepe_group = self.risk_gate._get_asset_group('PEPE-USD', groups)
        self.assertEqual(pepe_group, 'MEME_COINS')
        
        # Test unknown asset
        unknown_group = self.risk_gate._get_asset_group('UNKNOWN-USD', groups)
        self.assertEqual(unknown_group, 'OTHER')


class TestIntegration(unittest.TestCase):
    """Test integration of features"""
    
    def test_state_persistence_structure(self):
        """Test that state structure includes new fields"""
        mock_tracker = Mock()
        mock_broker = Mock()
        
        protocol = LegacyPositionExitProtocol(
            position_tracker=mock_tracker,
            broker_integration=mock_broker,
            monitor_high_exposure=True
        )
        
        default_state = protocol._default_state()
        
        # Should include new fields
        self.assertIn('high_exposure_assets_tracked', default_state)
        self.assertIn('high_exposure_alerts', default_state)
        
        # Should still have original fields
        self.assertIn('account_state', default_state)
        self.assertIn('cleanup_metrics', default_state)
    
    def test_high_exposure_list(self):
        """Test that HIGH_EXPOSURE_ASSETS list is defined"""
        self.assertIsNotNone(LegacyPositionExitProtocol.HIGH_EXPOSURE_ASSETS)
        self.assertGreater(len(LegacyPositionExitProtocol.HIGH_EXPOSURE_ASSETS), 0)
        
        # Should include PEPE and LUNA
        self.assertIn('PEPE-USD', LegacyPositionExitProtocol.HIGH_EXPOSURE_ASSETS)
        self.assertIn('LUNA-USD', LegacyPositionExitProtocol.HIGH_EXPOSURE_ASSETS)


def run_tests():
    """Run all tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestHighExposureMonitoring))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskIntelligenceGate))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
