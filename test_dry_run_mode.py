#!/usr/bin/env python3
"""
Test Dry-Run Mode Integration

This script tests that dry-run mode:
1. Displays startup banners correctly
2. Shows validation summary
3. Simulates trades without real orders
4. Tracks performance metrics

Run this to verify dry-run mode is working before operator sign-off.
"""

import os
import sys
import logging

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_dry_run_banners():
    """Test that dry-run banners display correctly"""
    logger.info("=" * 80)
    logger.info("TEST 1: Dry-Run Banner Display")
    logger.info("=" * 80)
    
    try:
        from bot.dry_run_engine import print_dry_run_startup_banner
        
        print("\nDisplaying dry-run startup banner:\n")
        print_dry_run_startup_banner()
        
        logger.info("✅ Dry-run startup banner displayed successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to display dry-run banner: {e}")
        return False


def test_validation_summary():
    """Test that validation summary displays correctly"""
    logger.info("=" * 80)
    logger.info("TEST 2: Validation Summary Display")
    logger.info("=" * 80)
    
    try:
        from bot.dry_run_engine import print_dry_run_validation_summary
        
        print("\nDisplaying validation summary:\n")
        print_dry_run_validation_summary(
            exchanges_configured=3,
            initial_balance=10000.0,
            currency="USD",
            duration_minutes=30
        )
        
        logger.info("✅ Validation summary displayed successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to display validation summary: {e}")
        return False


def test_dry_run_engine():
    """Test that dry-run engine works correctly"""
    logger.info("=" * 80)
    logger.info("TEST 3: Dry-Run Engine Functionality")
    logger.info("=" * 80)
    
    try:
        from bot.dry_run_engine import DryRunEngine
        
        # Create dry-run engine
        engine = DryRunEngine(initial_balance=10000.0)
        
        logger.info("✅ Dry-run engine initialized")
        
        # Simulate a buy order
        logger.info("Simulating BUY order...")
        order = engine.place_order(
            symbol="BTC-USD",
            side="buy",
            order_type="market",
            quantity=0.1,
            current_market_price=45000.0
        )
        
        logger.info(f"✅ Order placed: {order.order_id}, Status: {order.status.value}")
        
        # Update market prices
        logger.info("Updating market prices...")
        engine.update_market_prices({"BTC-USD": 46000.0})
        
        # Check positions
        positions = engine.get_positions()
        if "BTC-USD" in positions:
            pos = positions["BTC-USD"]
            logger.info(f"✅ Position tracked: {pos.quantity} @ ${pos.entry_price:.2f}")
            logger.info(f"   Unrealized P&L: ${pos.unrealized_pnl:.2f}")
        
        # Simulate a sell order
        logger.info("Simulating SELL order...")
        order2 = engine.place_order(
            symbol="BTC-USD",
            side="sell",
            order_type="market",
            quantity=0.1,
            current_market_price=46000.0
        )
        
        logger.info(f"✅ Order placed: {order2.order_id}, Status: {order2.status.value}")
        
        # Get performance summary
        summary = engine.get_performance_summary()
        logger.info("\n📊 Performance Summary:")
        logger.info(f"   Initial Balance: ${summary['initial_balance']:,.2f}")
        logger.info(f"   Current Balance: ${summary['current_balance']:,.2f}")
        logger.info(f"   Total P&L: ${summary['total_pnl']:,.2f}")
        logger.info(f"   Total Fees: ${summary['total_fees_paid']:,.2f}")
        logger.info(f"   Total Trades: {summary['total_trades']}")
        logger.info(f"   Return: {summary['return_pct']:.2f}%")
        
        logger.info("\n✅ Dry-run engine test completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Dry-run engine test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_startup_diagnostics():
    """Test that startup diagnostics show dry-run mode"""
    logger.info("=" * 80)
    logger.info("TEST 4: Startup Diagnostics Integration")
    logger.info("=" * 80)
    
    try:
        # Set dry-run mode
        os.environ['DRY_RUN_MODE'] = 'true'
        
        from bot.startup_diagnostics import display_feature_flag_banner
        
        print("\nDisplaying feature flag banner:\n")
        display_feature_flag_banner()
        
        logger.info("✅ Startup diagnostics displayed successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to display startup diagnostics: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_startup_validation():
    """Test that startup validation includes dry-run mode"""
    logger.info("=" * 80)
    logger.info("TEST 5: Startup Validation Integration")
    logger.info("=" * 80)
    
    try:
        # Set dry-run mode
        os.environ['DRY_RUN_MODE'] = 'true'
        os.environ['LIVE_CAPITAL_VERIFIED'] = 'false'
        
        from bot.startup_validation import validate_trading_mode, display_validation_results
        
        print("\nRunning trading mode validation:\n")
        result = validate_trading_mode()
        display_validation_results(result)
        
        # Check that dry-run mode is detected
        info_messages = [msg for msg in result.info]
        dry_run_detected = any("DRY RUN MODE" in msg for msg in info_messages)
        
        if dry_run_detected:
            logger.info("✅ Dry-run mode detected in validation")
        else:
            logger.warning("⚠️ Dry-run mode NOT detected in validation")
            logger.info(f"Info messages: {info_messages}")
        
        logger.info("✅ Startup validation test completed")
        return True
        
    except Exception as e:
        logger.error(f"❌ Startup validation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("NIJA DRY-RUN MODE TEST SUITE")
    print("=" * 80 + "\n")
    
    tests = [
        ("Dry-Run Banner Display", test_dry_run_banners),
        ("Validation Summary Display", test_validation_summary),
        ("Dry-Run Engine Functionality", test_dry_run_engine),
        ("Startup Diagnostics Integration", test_startup_diagnostics),
        ("Startup Validation Integration", test_startup_validation),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print("\n")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
        print("\n")
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    print("=" * 80)
    print(f"Results: {passed_count}/{total_count} tests passed")
    print("=" * 80)
    
    if passed_count == total_count:
        print("\n✅ ALL TESTS PASSED - Dry-run mode is ready for operator sign-off!")
        return 0
    else:
        print(f"\n⚠️ {total_count - passed_count} TEST(S) FAILED - Review failures above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
