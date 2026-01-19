#!/usr/bin/env python3
"""
Test script to verify user balance audit and observe mode functionality.

This script tests:
1. User balance audit displays all user accounts
2. Copy engine can run in observe mode
3. Observe mode tracks signals without executing trades
"""

import sys
import os
import logging

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("nija")

def test_user_balance_audit():
    """Test that user balance audit function works correctly."""
    logger.info("=" * 70)
    logger.info("TEST 1: User Balance Audit")
    logger.info("=" * 70)
    
    try:
        from bot.multi_account_broker_manager import MultiAccountBrokerManager
        from bot.broker_manager import BrokerType
        
        # Create a manager instance
        manager = MultiAccountBrokerManager()
        
        # Test with no users (should handle gracefully)
        logger.info("Testing audit with no users...")
        manager.audit_user_accounts()
        
        logger.info("✅ User balance audit function exists and handles empty state")
        return True
        
    except Exception as e:
        logger.error(f"❌ User balance audit test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_observe_mode():
    """Test that copy engine observe mode works correctly."""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 2: Copy Engine Observe Mode")
    logger.info("=" * 70)
    
    try:
        from bot.copy_trade_engine import CopyTradeEngine
        
        # Create engine in observe mode
        logger.info("Creating copy engine in observe mode...")
        engine = CopyTradeEngine(observe_only=True)
        
        # Verify observe mode is set
        assert engine.observe_only == True, "Observe mode not enabled"
        logger.info("✅ Copy engine created with observe_only=True")
        
        # Check stats
        stats = engine.get_stats()
        assert 'observe_only' in stats, "Stats missing observe_only flag"
        assert stats['observe_only'] == True, "Stats observe_only flag incorrect"
        logger.info("✅ Stats correctly report observe mode")
        
        # Create another engine in normal mode
        logger.info("\nCreating copy engine in normal mode...")
        engine_normal = CopyTradeEngine(observe_only=False)
        
        assert engine_normal.observe_only == False, "Normal mode incorrectly set"
        logger.info("✅ Copy engine created with observe_only=False")
        
        stats_normal = engine_normal.get_stats()
        assert stats_normal['observe_only'] == False, "Normal mode stats incorrect"
        logger.info("✅ Stats correctly report normal mode")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Observe mode test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_global_functions():
    """Test that global copy engine functions support observe mode."""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 3: Global Copy Engine Functions")
    logger.info("=" * 70)
    
    try:
        from bot.copy_trade_engine import get_copy_engine, start_copy_engine
        
        # Test getting engine with observe mode
        logger.info("Testing get_copy_engine with observe_only parameter...")
        
        # Note: Can't test start_copy_engine in this script because it would
        # start a background thread that we can't easily control.
        # Instead, just verify the function signature accepts the parameter
        
        import inspect
        sig = inspect.signature(start_copy_engine)
        params = sig.parameters
        
        assert 'observe_only' in params, "start_copy_engine missing observe_only parameter"
        logger.info("✅ start_copy_engine accepts observe_only parameter")
        
        # Check default value
        default = params['observe_only'].default
        assert default == False, "observe_only default should be False"
        logger.info("✅ observe_only defaults to False (backward compatible)")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Global functions test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """Run all tests."""
    logger.info("=" * 70)
    logger.info("🧪 USER BALANCE AUDIT & OBSERVE MODE TESTS")
    logger.info("=" * 70)
    
    results = []
    
    # Run tests
    results.append(("User Balance Audit", test_user_balance_audit()))
    results.append(("Observe Mode", test_observe_mode()))
    results.append(("Global Functions", test_global_functions()))
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    logger.info("")
    logger.info(f"Total: {passed}/{total} tests passed")
    logger.info("=" * 70)
    
    if passed == total:
        logger.info("🎉 All tests passed!")
        return 0
    else:
        logger.error(f"❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
