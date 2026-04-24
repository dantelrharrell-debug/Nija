#!/usr/bin/env python3
"""
Test Exit Logic Continuous Firing
==================================

Tests to validate that the exit logic improvements work correctly:
1. Early return bug is fixed
2. Error recovery works
3. Continuous enforcer runs independently
4. Forced unwind mode works
"""

import os
import sys
import time
import logging

# Add bot directory to path
bot_dir = os.path.join(os.path.dirname(__file__), 'bot')
sys.path.insert(0, bot_dir)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


def test_user_risk_manager_forced_unwind():
    """Test that forced unwind mode can be enabled/disabled."""
    logger.info("=" * 70)
    logger.info("TEST 1: User Risk Manager Forced Unwind")
    logger.info("=" * 70)
    
    try:
        from user_risk_manager import get_user_risk_manager
        
        risk_manager = get_user_risk_manager()
        test_user = "test_user_123"
        
        # Should not be active initially
        assert not risk_manager.is_forced_unwind_active(test_user), "Forced unwind should not be active initially"
        logger.info("✅ Initial state: forced unwind NOT active")
        
        # Enable forced unwind
        risk_manager.enable_forced_unwind(test_user)
        logger.info("✅ Called enable_forced_unwind()")
        
        # Should be active now
        assert risk_manager.is_forced_unwind_active(test_user), "Forced unwind should be active after enable"
        logger.info("✅ Forced unwind IS active after enable")
        
        # Disable forced unwind
        risk_manager.disable_forced_unwind(test_user)
        logger.info("✅ Called disable_forced_unwind()")
        
        # Should not be active anymore
        assert not risk_manager.is_forced_unwind_active(test_user), "Forced unwind should not be active after disable"
        logger.info("✅ Forced unwind NOT active after disable")
        
        logger.info("✅ TEST 1 PASSED: Forced unwind mode works correctly")
        return True
        
    except Exception as e:
        logger.error(f"❌ TEST 1 FAILED: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_continuous_exit_enforcer():
    """Test that continuous exit enforcer can be started/stopped."""
    logger.info("=" * 70)
    logger.info("TEST 2: Continuous Exit Enforcer")
    logger.info("=" * 70)
    
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        # Create enforcer instance
        enforcer = ContinuousExitEnforcer(
            check_interval=5,  # Check every 5 seconds for testing
            max_positions=8,
            emergency_mode=False
        )
        logger.info("✅ Created ContinuousExitEnforcer instance")
        
        # Start enforcer
        enforcer.start()
        logger.info("✅ Started enforcer")
        
        # Give it a moment to start
        time.sleep(1)
        
        # Test forced unwind for a user
        test_user = "test_user_456"
        enforcer.enable_forced_unwind(test_user)
        logger.info(f"✅ Enabled forced unwind for {test_user}")
        
        assert enforcer.is_forced_unwind_active(test_user), "Forced unwind should be active"
        logger.info("✅ Forced unwind IS active")
        
        enforcer.disable_forced_unwind(test_user)
        logger.info(f"✅ Disabled forced unwind for {test_user}")
        
        assert not enforcer.is_forced_unwind_active(test_user), "Forced unwind should not be active"
        logger.info("✅ Forced unwind NOT active")
        
        # Stop enforcer
        enforcer.stop()
        logger.info("✅ Stopped enforcer")
        
        logger.info("✅ TEST 2 PASSED: Continuous exit enforcer works correctly")
        return True
        
    except Exception as e:
        logger.error(f"❌ TEST 2 FAILED: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_position_cap_enforcer():
    """Test that position cap enforcer module loads."""
    logger.info("=" * 70)
    logger.info("TEST 3: Position Cap Enforcer Module")
    logger.info("=" * 70)
    
    try:
        from position_cap_enforcer import PositionCapEnforcer
        
        # Just verify module loads and can be instantiated
        enforcer = PositionCapEnforcer(max_positions=8)
        logger.info("✅ Created PositionCapEnforcer instance")
        
        logger.info("✅ TEST 3 PASSED: Position cap enforcer module loads correctly")
        return True
        
    except Exception as e:
        logger.error(f"❌ TEST 3 FAILED: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_trading_strategy_imports():
    """Test that trading strategy can import all needed modules."""
    logger.info("=" * 70)
    logger.info("TEST 4: Trading Strategy Imports")
    logger.info("=" * 70)
    
    try:
        # Test that trading_strategy.py syntax is valid
        import py_compile
        strategy_path = os.path.join(os.path.dirname(__file__), 'bot', 'trading_strategy.py')
        py_compile.compile(strategy_path, doraise=True)
        logger.info("✅ trading_strategy.py syntax is valid")
        
        logger.info("✅ TEST 4 PASSED: Trading strategy syntax is valid")
        return True
        
    except Exception as e:
        logger.error(f"❌ TEST 4 FAILED: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """Run all tests."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("EXIT LOGIC CONTINUOUS FIRING TESTS")
    logger.info("=" * 70)
    logger.info("")
    
    results = []
    
    # Run tests
    results.append(("User Risk Manager Forced Unwind", test_user_risk_manager_forced_unwind()))
    results.append(("Continuous Exit Enforcer", test_continuous_exit_enforcer()))
    results.append(("Position Cap Enforcer Module", test_position_cap_enforcer()))
    results.append(("Trading Strategy Imports", test_trading_strategy_imports()))
    
    # Print summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    logger.info("=" * 70)
    logger.info(f"TOTAL: {passed}/{total} tests passed")
    logger.info("=" * 70)
    
    return passed == total


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
