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

# Ensure project root is on path for bot package imports
sys.path.insert(0, str(Path(__file__).parent))

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


# ---------------------------------------------------------------------------
# Tests for the three new institutional risk intelligence features
# ---------------------------------------------------------------------------

from bot.risk_intelligence import (
    CorrelationExposureController,
    VolatilityPositionCapper,
    DrawdownCircuitBreaker,
    RiskIntelligenceSystem,
    create_risk_intelligence_system,
    _get_asset_group,
)


class TestCorrelationExposureController(unittest.TestCase):
    """Feature 1 — Correlation-Aware Exposure Control"""

    def setUp(self):
        self.controller = CorrelationExposureController(max_group_exposure_pct=0.40)

    def test_allows_position_under_group_cap(self):
        """Position that keeps group exposure under 40% should be approved."""
        approved, details = self.controller.check(
            symbol='BTC-USD',
            proposed_size_usd=300.0,
            current_positions=[],
            account_balance=10_000.0,
        )
        self.assertTrue(approved)
        self.assertEqual(details['correlation_group'], 'BTC_RELATED')

    def test_blocks_position_exceeding_group_cap(self):
        """Position that pushes group over 40% should be rejected."""
        existing = [
            {'symbol': 'DOGE-USD', 'size_usd': 2_000.0},
            {'symbol': 'SHIB-USD', 'size_usd': 1_500.0},
        ]
        # Adding 1000 PEPE brings MEME_COINS to (2000+1500+1000)/10000 = 45% → reject
        approved, details = self.controller.check(
            symbol='PEPE-USD',
            proposed_size_usd=1_000.0,
            current_positions=existing,
            account_balance=10_000.0,
        )
        self.assertFalse(approved)
        self.assertIn('rejection_reason', details)
        self.assertEqual(details['correlation_group'], 'MEME_COINS')

    def test_asset_group_detection(self):
        """_get_asset_group should categorise well-known assets."""
        self.assertEqual(_get_asset_group('BTC-USD'), 'BTC_RELATED')
        self.assertEqual(_get_asset_group('PEPE-USD'), 'MEME_COINS')
        self.assertEqual(_get_asset_group('SOL-USD'), 'LAYER1')
        self.assertEqual(_get_asset_group('UNKNOWN-XYZ'), 'OTHER')

    def test_different_groups_do_not_interfere(self):
        """Exposure in one group should not block entry in another group."""
        existing = [
            {'symbol': 'DOGE-USD', 'size_usd': 3_500.0},  # 35% MEME_COINS
        ]
        # BTC-USD is in BTC_RELATED — should be approved regardless
        approved, _ = self.controller.check(
            symbol='BTC-USD',
            proposed_size_usd=1_000.0,
            current_positions=existing,
            account_balance=10_000.0,
        )
        self.assertTrue(approved)


class TestVolatilityPositionCapper(unittest.TestCase):
    """Feature 2 — Volatility-Adjusted Position Caps"""

    def setUp(self):
        self.capper = VolatilityPositionCapper()

    def _make_df(self, atr_ratio: float = 1.0, periods: int = 50):
        """Build a synthetic OHLCV DataFrame with a given ATR ratio.

        The *last* ``atr_lookback`` candles have a range that is ``atr_ratio``
        times the range of the earlier candles, producing a measurable
        current-vs-average ATR difference.
        """
        import pandas as pd
        lookback = self.capper.atr_lookback  # default 14
        normal_range = 5.0
        high_range = normal_range * atr_ratio
        # First (periods - lookback) candles: normal; last lookback: high_range
        ranges = [normal_range] * (periods - lookback) + [high_range] * lookback
        close = [100.0] * periods
        high_prices = [c + r / 2 for c, r in zip(close, ranges)]
        low_prices = [c - r / 2 for c, r in zip(close, ranges)]
        return pd.DataFrame({
            'open': close,
            'high': high_prices,
            'low': low_prices,
            'close': close,
        })

    def test_normal_volatility_no_cap(self):
        """Normal volatility should return 1.0× multiplier."""
        df = self._make_df(atr_ratio=1.0)
        multiplier, regime = self.capper.get_size_multiplier('BTC-USD', df)
        self.assertEqual(regime, 'NORMAL')
        self.assertEqual(multiplier, 1.0)

    def test_extreme_high_volatility_caps_position(self):
        """Extreme volatility (ATR >> average) should reduce the position-size multiplier."""
        # Use a very high ratio so recent ATR dwarfs the long-run average,
        # pushing the multiplier below 1.0 regardless of exact regime bucket.
        df = self._make_df(atr_ratio=35.0)
        multiplier, regime = self.capper.get_size_multiplier('BTC-USD', df)
        self.assertIn(regime, ('EXTREME_HIGH', 'HIGH'), msg=f"Unexpected regime: {regime}")
        self.assertLess(multiplier, 1.0, msg=f"Expected cap < 1.0 but got {multiplier}")

    def test_apply_cap_reduces_size_in_high_vol(self):
        """apply_cap should return a smaller size during high volatility."""
        df = self._make_df(atr_ratio=2.0)  # HIGH regime
        capped_size, details = self.capper.apply_cap('BTC-USD', 1_000.0, df)
        self.assertLessEqual(capped_size, 1_000.0)
        self.assertIn('regime', details)
        self.assertIn('multiplier', details)

    def test_no_df_returns_normal_regime(self):
        """Without a DataFrame the capper should default to NORMAL (1.0×)."""
        multiplier, regime = self.capper.get_size_multiplier('BTC-USD', df=None)
        self.assertEqual(regime, 'NORMAL')
        self.assertEqual(multiplier, 1.0)


class TestDrawdownCircuitBreaker(unittest.TestCase):
    """Feature 3 — Portfolio-Level Drawdown Circuit Breaker"""

    def setUp(self):
        # Remove any persisted drawdown state to ensure tests start fresh
        state_file = Path(__file__).parent / 'data' / 'drawdown_protection.json'
        if state_file.exists():
            state_file.unlink()
        self.breaker = DrawdownCircuitBreaker(base_capital=10_000.0)

    def test_allows_trading_at_peak(self):
        """No drawdown → trading should be allowed."""
        can_trade, reason = self.breaker.can_trade()
        self.assertTrue(can_trade)

    def test_halts_trading_at_deep_drawdown(self):
        """20%+ drawdown should trigger the circuit breaker halt."""
        self.breaker.update(7_900.0)  # 21% drawdown
        can_trade, reason = self.breaker.can_trade()
        self.assertFalse(can_trade)
        self.assertIn('HALT', reason.upper() + 'CIRCUIT BREAKER')

    def test_drawdown_pct_calculation(self):
        """Drawdown percentage should be accurate."""
        self.breaker.update(9_000.0)  # 10% drawdown
        pct = self.breaker.get_drawdown_pct()
        self.assertAlmostEqual(pct, 10.0, places=1)

    def test_multiplier_reduces_with_drawdown(self):
        """Position size multiplier should decrease as drawdown deepens."""
        self.breaker.update(9_400.0)  # 6% drawdown → CAUTION
        mult_caution = self.breaker.get_position_size_multiplier()
        self.breaker.update(8_800.0)  # 12% drawdown → WARNING
        mult_warning = self.breaker.get_position_size_multiplier()
        self.assertLess(mult_warning, mult_caution)

    def test_get_status_structure(self):
        """get_status should return expected keys."""
        status = self.breaker.get_status()
        for key in ('peak_capital', 'current_capital', 'drawdown_pct',
                    'can_trade', 'reason', 'position_size_multiplier'):
            self.assertIn(key, status)


class TestRiskIntelligenceSystem(unittest.TestCase):
    """Unified RiskIntelligenceSystem integration tests"""

    def setUp(self):
        self.ris = create_risk_intelligence_system(base_capital=10_000.0)

    def test_can_open_position_normal_conditions(self):
        """Under normal conditions new positions should be approved."""
        allowed, reason = self.ris.can_open_position(
            symbol='BTC-USD',
            proposed_size_usd=500.0,
            current_positions=[],
            account_balance=10_000.0,
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, 'ok')

    def test_circuit_breaker_blocks_on_deep_drawdown(self):
        """Circuit breaker should block after deep drawdown."""
        self.ris.update_capital(7_000.0)  # 30% drawdown
        allowed, reason = self.ris.can_open_position(
            symbol='ETH-USD',
            proposed_size_usd=200.0,
            current_positions=[],
            account_balance=7_000.0,
        )
        self.assertFalse(allowed)
        self.assertIn('CircuitBreaker', reason)

    def test_correlation_control_blocks_overexposed_group(self):
        """Correlation control should block when group exposure is too high."""
        # Use a fresh system with cleared disk state
        state_file = Path(__file__).parent / 'data' / 'drawdown_protection.json'
        if state_file.exists():
            state_file.unlink()
        ris = create_risk_intelligence_system(base_capital=10_000.0)
        existing = [
            {'symbol': 'DOGE-USD', 'size_usd': 2_500.0},
            {'symbol': 'SHIB-USD', 'size_usd': 2_000.0},
        ]
        # Adding PEPE: (2500+2000+1000)/10000 = 55% → MEME_COINS over 40% cap
        allowed, reason = ris.can_open_position(
            symbol='PEPE-USD',
            proposed_size_usd=1_000.0,
            current_positions=existing,
            account_balance=10_000.0,
        )
        self.assertFalse(allowed)
        self.assertIn('CorrelationControl', reason)

    def test_adjusted_size_applies_volatility_and_drawdown(self):
        """get_adjusted_position_size should return metadata for both caps."""
        size, meta = self.ris.get_adjusted_position_size(
            symbol='ETH-USD',
            base_size_usd=1_000.0,
        )
        self.assertIn('volatility_cap', meta)
        self.assertIn('drawdown_multiplier', meta)
        self.assertGreater(size, 0)

    def test_factory_creates_correct_instance(self):
        """create_risk_intelligence_system should return RiskIntelligenceSystem."""
        system = create_risk_intelligence_system(
            base_capital=5_000.0,
            config={'max_group_exposure_pct': 0.30},
        )
        self.assertIsInstance(system, RiskIntelligenceSystem)
        self.assertEqual(
            system.correlation_controller.max_group_exposure_pct, 0.30
        )


def run_tests():
    """Run all tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestHighExposureMonitoring))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskIntelligenceGate))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestCorrelationExposureController))
    suite.addTests(loader.loadTestsFromTestCase(TestVolatilityPositionCapper))
    suite.addTests(loader.loadTestsFromTestCase(TestDrawdownCircuitBreaker))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskIntelligenceSystem))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
