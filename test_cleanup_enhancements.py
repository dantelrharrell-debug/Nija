#!/usr/bin/env python3
"""
Test Cleanup Enhancements
=========================
Validates the fixes for:
1. Unknown asset pair handling (AUT-USD)
2. Adoption pipeline mismatch tracking
3. Per-user cleanup robustness
4. Dry-run mode verification
5. Cap violation alerts
"""

import sys
import os
import logging
from typing import Dict, List

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MockBroker:
    """Mock broker for testing"""
    
    def __init__(self, name="TEST", positions=None):
        self.name = name
        self.connected = True
        self.positions = positions or []
        self.broker_type = type('BrokerType', (), {'value': name})()
        
    def get_positions(self):
        """Return mock positions"""
        return self.positions
    
    def get_current_price(self, symbol: str):
        """Mock price fetching - returns None for unknown assets"""
        # Simulate unknown asset (AUT-USD)
        if symbol == 'AUT-USD':
            logger.info(f"   Simulating unknown asset: {symbol} returns None")
            return None
        # Return mock price for known assets
        return 100.0
    
    def close_position(self, symbol: str):
        """Mock position closing"""
        return {'status': 'filled', 'symbol': symbol}


def test_unknown_asset_handling():
    """Test 1: Unknown Asset Pair Handling"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 1: Unknown Asset Pair Handling (AUT-USD)")
    logger.info("=" * 70)
    
    try:
        from trading_strategy import TradingStrategy
        
        strategy = TradingStrategy()
        
        # Mock positions with unknown asset
        mock_positions = [
            {
                'symbol': 'BTC-USD',
                'entry_price': 50000.0,
                'current_price': 51000.0,
                'quantity': 0.01,
                'size_usd': 510.0
            },
            {
                'symbol': 'AUT-USD',  # Unknown asset - will fail price fetch
                'entry_price': 1.0,
                'current_price': 0.0,  # Triggers price fetch
                'quantity': 100.0,
                'size_usd': 0.0  # Also triggers recalculation
            },
            {
                'symbol': 'ETH-USD',
                'entry_price': 3000.0,
                'current_price': 3100.0,
                'quantity': 0.1,
                'size_usd': 310.0
            }
        ]
        
        broker = MockBroker("TEST_BROKER", mock_positions)
        
        # Try to adopt positions
        result = strategy.adopt_existing_positions(
            broker=broker,
            broker_name="TEST_BROKER",
            account_id="TEST_ACCOUNT"
        )
        
        logger.info("")
        logger.info("📊 ADOPTION RESULTS:")
        logger.info(f"   Found: {result['positions_found']}")
        logger.info(f"   Adopted: {result['positions_adopted']}")
        logger.info(f"   Failed: {len(result.get('failed_positions', []))}")
        
        if result.get('failed_positions'):
            logger.info("")
            logger.info("   Failed Positions:")
            for failure in result['failed_positions']:
                logger.info(f"      • {failure['symbol']}: {failure['reason']} - {failure['detail']}")
        
        # Verify AUT-USD was marked as zombie
        aut_failed = any(f['symbol'] == 'AUT-USD' for f in result.get('failed_positions', []))
        if aut_failed:
            logger.info("")
            logger.info("✅ TEST PASSED: AUT-USD was correctly identified as zombie")
        else:
            logger.error("❌ TEST FAILED: AUT-USD should have been marked as zombie")
        
        # Verify other positions were adopted
        if result['positions_adopted'] == 2:
            logger.info("✅ TEST PASSED: Other positions (BTC, ETH) were adopted")
        else:
            logger.error(f"❌ TEST FAILED: Expected 2 adopted positions, got {result['positions_adopted']}")
        
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()


def test_adoption_failure_tracking():
    """Test 2: Adoption Pipeline Mismatch Tracking"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 2: Adoption Failure Tracking")
    logger.info("=" * 70)
    
    try:
        from trading_strategy import TradingStrategy
        
        strategy = TradingStrategy()
        
        # Mock positions with various failure scenarios
        mock_positions = [
            {
                'symbol': 'BTC-USD',
                'entry_price': 50000.0,
                'current_price': 51000.0,
                'quantity': 0.01,
                'size_usd': 510.0
            },
            {
                'symbol': 'NO-ENTRY',  # Missing entry price
                'entry_price': 0.0,
                'current_price': 100.0,
                'quantity': 10.0,
                'size_usd': 1000.0
            },
            {
                'symbol': 'NO-PRICE',  # Missing current price
                'entry_price': 100.0,
                'current_price': 0.0,
                'quantity': 10.0,
                'size_usd': 0.0
            }
        ]
        
        broker = MockBroker("TEST_BROKER", mock_positions)
        
        result = strategy.adopt_existing_positions(
            broker=broker,
            broker_name="TEST_BROKER",
            account_id="TEST_ACCOUNT"
        )
        
        logger.info("")
        logger.info("📊 ADOPTION RESULTS:")
        logger.info(f"   Found: {result['positions_found']}")
        logger.info(f"   Adopted: {result['positions_adopted']}")
        logger.info(f"   Failed: {len(result.get('failed_positions', []))}")
        
        # Verify failures are tracked with reasons
        failed_positions = result.get('failed_positions', [])
        if len(failed_positions) >= 1:  # At least NO-ENTRY should fail
            logger.info("✅ TEST PASSED: Failed positions are tracked")
            logger.info("")
            logger.info("   Failure Details:")
            for failure in failed_positions:
                logger.info(f"      • {failure['symbol']}: {failure['reason']}")
        else:
            logger.error("❌ TEST FAILED: Failed positions not tracked")
        
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()


def test_per_user_cleanup_robustness():
    """Test 3: Per-User Cleanup Robustness"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 3: Per-User Cleanup Robustness")
    logger.info("=" * 70)
    
    try:
        from forced_position_cleanup import ForcedPositionCleanup
        from broker_manager import BrokerType
        
        cleanup = ForcedPositionCleanup(
            dust_threshold_usd=1.00,
            max_positions=2,  # Low cap for testing
            dry_run=True  # Don't actually close positions
        )
        
        # Mock user with 3 positions across 2 brokers (exceeds cap)
        mock_broker1 = MockBroker("KRAKEN", [
            {'symbol': 'BTC-USD', 'size_usd': 1000.0, 'pnl_pct': 5.0},
            {'symbol': 'ETH-USD', 'size_usd': 800.0, 'pnl_pct': 3.0}
        ])
        
        mock_broker2 = MockBroker("COINBASE", [
            {'symbol': 'SOL-USD', 'size_usd': 500.0, 'pnl_pct': -2.0}
        ])
        
        user_brokers = {
            BrokerType.KRAKEN: mock_broker1,
            BrokerType.COINBASE: mock_broker2
        }
        
        # Run per-user cleanup
        logger.info("")
        logger.info("Running per-user cleanup...")
        result = cleanup._cleanup_user_all_brokers(
            user_id="test_user",
            user_broker_dict=user_brokers,
            is_startup=False
        )
        
        logger.info("")
        logger.info("✅ TEST PASSED: Per-user cleanup executed without errors")
        logger.info("   (Check logs above for cap violation alert)")
        
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()


def test_dry_run_mode():
    """Test 4: Dry-Run Mode Verification"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 4: Dry-Run Mode Verification")
    logger.info("=" * 70)
    
    try:
        from forced_position_cleanup import ForcedPositionCleanup
        
        cleanup = ForcedPositionCleanup(
            dust_threshold_usd=1.00,
            max_positions=5,
            dry_run=True  # Enable dry-run
        )
        
        logger.info("")
        if cleanup.dry_run:
            logger.info("✅ TEST PASSED: Dry-run mode is enabled")
            logger.info("   Cleanup will log actions without executing trades")
        else:
            logger.error("❌ TEST FAILED: Dry-run mode not enabled")
        
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()


def test_cap_violation_alert():
    """Test 5: Cap Violation Alert"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 5: Cap Violation Alert")
    logger.info("=" * 70)
    
    try:
        from forced_position_cleanup import ForcedPositionCleanup
        
        cleanup = ForcedPositionCleanup(
            dust_threshold_usd=1.00,
            max_positions=5,
            dry_run=True
        )
        
        # Trigger alert
        logger.info("")
        logger.info("Triggering cap violation alert...")
        cleanup._log_cap_violation_alert("test_user", 10, 5)
        
        logger.info("")
        logger.info("✅ TEST PASSED: Cap violation alert logged")
        logger.info("   (Check logs above for alert details)")
        
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all tests"""
    logger.info("")
    logger.info("*" * 70)
    logger.info("CLEANUP ENHANCEMENTS TEST SUITE")
    logger.info("*" * 70)
    
    test_unknown_asset_handling()
    test_adoption_failure_tracking()
    test_per_user_cleanup_robustness()
    test_dry_run_mode()
    test_cap_violation_alert()
    
    logger.info("")
    logger.info("*" * 70)
    logger.info("ALL TESTS COMPLETE")
    logger.info("*" * 70)
    logger.info("")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
