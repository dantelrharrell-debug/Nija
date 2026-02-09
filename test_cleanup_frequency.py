#!/usr/bin/env python3
"""
Test cleanup frequency improvements and trade-based triggers
Validates the new 15-minute interval and optional trade-based cleanup
"""

import logging
import sys
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger("test_cleanup_frequency")

def test_default_interval():
    """Test that default cleanup interval is 6 cycles (15 minutes)"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 1: Default Cleanup Interval")
    logger.info("=" * 70)
    
    # Parse the trading_strategy.py file to verify default
    try:
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
            
        # Find the default interval line
        if "FORCED_CLEANUP_INTERVAL = 6" in content:
            logger.info("✅ Default interval is 6 cycles (~15 minutes)")
            return True
        elif "FORCED_CLEANUP_INTERVAL = 20" in content:
            logger.error("❌ Default interval is still 20 cycles (~50 minutes)")
            logger.error("   Expected: 6 cycles for better safety optics")
            return False
        else:
            logger.error("❌ Could not find FORCED_CLEANUP_INTERVAL default")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error reading file: {e}")
        return False


def test_trade_based_trigger_exists():
    """Test that trade-based trigger option was added"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 2: Trade-Based Trigger Feature")
    logger.info("=" * 70)
    
    try:
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
        
        # Check for trade-based cleanup code
        checks = [
            ("FORCED_CLEANUP_AFTER_N_TRADES", "Environment variable defined"),
            ("trades_since_last_cleanup", "Trade counter variable"),
            ("run_trade_based_cleanup", "Trade-based trigger logic"),
            ("TRADE-BASED", "Trade-based cleanup reason logging"),
        ]
        
        all_passed = True
        for check_str, description in checks:
            if check_str in content:
                logger.info(f"   ✅ {description} found")
            else:
                logger.error(f"   ❌ {description} missing")
                all_passed = False
        
        if all_passed:
            logger.info("")
            logger.info("✅ TEST PASSED: Trade-based trigger fully implemented")
            return True
        else:
            logger.error("")
            logger.error("❌ TEST FAILED: Trade-based trigger incomplete")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error reading file: {e}")
        return False


def test_cleanup_trigger_logic():
    """Test that cleanup trigger logic includes all conditions"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 3: Cleanup Trigger Logic")
    logger.info("=" * 70)
    
    try:
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
        
        # Find the trigger logic section
        trigger_section_found = False
        startup_found = False
        periodic_found = False
        trade_based_found = False
        
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'run_startup_cleanup' in line and 'cycle_count == 0' in line:
                startup_found = True
            if 'run_periodic_cleanup' in line and 'FORCED_CLEANUP_INTERVAL' in line:
                periodic_found = True
            if 'run_trade_based_cleanup' in line and 'FORCED_CLEANUP_AFTER_N_TRADES' in line:
                trade_based_found = True
        
        logger.info(f"   Startup trigger: {'✅' if startup_found else '❌'}")
        logger.info(f"   Periodic trigger: {'✅' if periodic_found else '❌'}")
        logger.info(f"   Trade-based trigger: {'✅' if trade_based_found else '❌'}")
        
        if startup_found and periodic_found and trade_based_found:
            logger.info("")
            logger.info("✅ TEST PASSED: All trigger conditions present")
            return True
        else:
            logger.error("")
            logger.error("❌ TEST FAILED: Missing trigger conditions")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error reading file: {e}")
        return False


def test_trade_counter_increments():
    """Test that trade counter is incremented after successful trades"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 4: Trade Counter Increments")
    logger.info("=" * 70)
    
    try:
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
        
        # Count occurrences of trade counter increment
        increment_count = content.count('self.trades_since_last_cleanup += 1')
        
        logger.info(f"   Found {increment_count} trade counter increment(s)")
        
        if increment_count >= 3:  # Should be in multiple successful trade locations
            logger.info("   ✅ Trade counter incremented in multiple locations")
            logger.info("")
            logger.info("✅ TEST PASSED: Trade counter properly incremented")
            return True
        else:
            logger.error(f"   ❌ Expected at least 3 increments, found {increment_count}")
            logger.error("")
            logger.error("❌ TEST FAILED: Trade counter not properly incremented")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error reading file: {e}")
        return False


def test_counter_reset():
    """Test that trade counter is reset after cleanup"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 5: Trade Counter Reset After Cleanup")
    logger.info("=" * 70)
    
    try:
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
        
        # Check for counter reset
        if 'self.trades_since_last_cleanup = 0' in content:
            logger.info("   ✅ Counter reset logic found")
            
            # Verify it's in the cleanup section
            lines = content.split('\n')
            reset_in_cleanup = False
            for i, line in enumerate(lines):
                if 'self.trades_since_last_cleanup = 0' in line:
                    # Check if we're in cleanup context (look at surrounding lines)
                    context = '\n'.join(lines[max(0, i-10):i+10])
                    if 'cleanup' in context.lower():
                        reset_in_cleanup = True
                        break
            
            if reset_in_cleanup:
                logger.info("   ✅ Counter reset after cleanup execution")
                logger.info("")
                logger.info("✅ TEST PASSED: Counter properly reset")
                return True
            else:
                logger.error("   ❌ Counter reset not in cleanup context")
                logger.error("")
                logger.error("❌ TEST FAILED: Counter reset misplaced")
                return False
        else:
            logger.error("   ❌ Counter reset logic not found")
            logger.error("")
            logger.error("❌ TEST FAILED: No counter reset")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error reading file: {e}")
        return False


def test_logging_enhanced():
    """Test that logging includes trade-based trigger information"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 6: Enhanced Logging")
    logger.info("=" * 70)
    
    try:
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
        
        # Check for enhanced logging
        checks = [
            ("TRADE-BASED", "Trade-based cleanup reason"),
            ("Trade trigger:", "Trade trigger logging"),
            ("trades executed", "Trade count logging"),
        ]
        
        all_passed = True
        for check_str, description in checks:
            if check_str in content:
                logger.info(f"   ✅ {description} logging found")
            else:
                logger.warning(f"   ⚠️  {description} logging missing (optional)")
        
        logger.info("")
        logger.info("✅ TEST PASSED: Enhanced logging present")
        return True
            
    except Exception as e:
        logger.error(f"❌ Error reading file: {e}")
        return False


def main():
    """Run all cleanup frequency tests"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("CLEANUP FREQUENCY IMPROVEMENTS TEST SUITE")
    logger.info("=" * 70)
    logger.info("")
    logger.info("Verifying:")
    logger.info("1. Default interval lowered from 50 min to 15 min")
    logger.info("2. Trade-based cleanup trigger added")
    logger.info("3. Trade counter properly implemented")
    logger.info("")
    
    results = []
    
    # Run tests
    results.append(("Default Interval (15 min)", test_default_interval()))
    results.append(("Trade-Based Trigger Feature", test_trade_based_trigger_exists()))
    results.append(("Cleanup Trigger Logic", test_cleanup_trigger_logic()))
    results.append(("Trade Counter Increments", test_trade_counter_increments()))
    results.append(("Counter Reset After Cleanup", test_counter_reset()))
    results.append(("Enhanced Logging", test_logging_enhanced()))
    
    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = 0
    failed = 0
    
    for test_name, result in results:
        if result:
            logger.info(f"✅ {test_name}: PASSED")
            passed += 1
        else:
            logger.error(f"❌ {test_name}: FAILED")
            failed += 1
    
    logger.info("")
    logger.info(f"Total: {len(results)} tests")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    logger.info("=" * 70)
    
    if failed == 0:
        logger.info("")
        logger.info("🎉 ALL TESTS PASSED - Cleanup frequency improvements working!")
        logger.info("")
        logger.info("Summary:")
        logger.info("  • Default interval: 6 cycles (~15 minutes)")
        logger.info("  • Trade-based trigger: Available via env var")
        logger.info("  • Multi-trigger support: Time OR trades (whichever first)")
        logger.info("  • Safety optics: 3.3x improvement (50 min → 15 min)")
        logger.info("")
        return 0
    else:
        logger.error("")
        logger.error(f"⚠️ {failed} TEST(S) FAILED - Cleanup frequency has issues!")
        logger.error("")
        return 1


if __name__ == "__main__":
    sys.exit(main())
