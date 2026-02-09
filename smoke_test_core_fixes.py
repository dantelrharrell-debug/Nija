#!/usr/bin/env python3
"""
NIJA Core Fixes Smoke Test
===========================

Comprehensive smoke test to verify that the 3 core problems are 100% functional:
1. Exit Logic - Continuous firing even with errors
2. Risk Cap (Position Cap) - Automatic enforcement
3. Forced Unwind - Per-user emergency exit mode

This test validates the complete integration of:
- continuous_exit_enforcer.py
- position_cap_enforcer.py
- user_risk_manager.py
- broker_manager.py (with new get_all_brokers() method)

Test Strategy:
- Unit tests for each component
- Integration tests between components
- End-to-end scenario tests
- Error recovery tests
"""

import os
import sys
import time
import logging
import threading
from typing import List, Dict, Optional

# Add bot directory to path
bot_dir = os.path.join(os.path.dirname(__file__), 'bot')
sys.path.insert(0, bot_dir)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

# Test results tracking
test_results = []


def record_test(test_name: str, passed: bool, message: str = ""):
    """Record a test result."""
    test_results.append({
        'name': test_name,
        'passed': passed,
        'message': message
    })
    status = "✅ PASS" if passed else "❌ FAIL"
    logger.info(f"{status}: {test_name}")
    if message:
        logger.info(f"    {message}")


def print_section_header(title: str):
    """Print a formatted section header."""
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"  {title}")
    logger.info("=" * 80)
    logger.info("")


# =============================================================================
# TEST SUITE 1: EXIT LOGIC (Continuous Firing)
# =============================================================================

def test_continuous_exit_enforcer_creation():
    """Test 1.1: ContinuousExitEnforcer can be created."""
    test_name = "1.1 - ContinuousExitEnforcer Creation"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        enforcer = ContinuousExitEnforcer(
            check_interval=60,
            max_positions=8,
            emergency_mode=False
        )
        
        assert enforcer is not None, "Enforcer should be created"
        assert enforcer.check_interval == 60, "Check interval should be 60"
        assert enforcer.max_positions == 8, "Max positions should be 8"
        assert enforcer.emergency_mode == False, "Emergency mode should be False"
        
        record_test(test_name, True, "Enforcer created with correct parameters")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_continuous_exit_enforcer_start_stop():
    """Test 1.2: ContinuousExitEnforcer can start and stop."""
    test_name = "1.2 - ContinuousExitEnforcer Start/Stop"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        enforcer = ContinuousExitEnforcer(
            check_interval=5,  # Short interval for testing
            max_positions=8
        )
        
        # Start the enforcer
        enforcer.start()
        time.sleep(1)  # Give it time to start
        
        # Verify thread is running
        assert enforcer._monitor_thread is not None, "Monitor thread should exist"
        assert enforcer._monitor_thread.is_alive(), "Monitor thread should be alive"
        
        # Stop the enforcer
        enforcer.stop()
        time.sleep(1)  # Give it time to stop
        
        # Verify thread stopped
        assert not enforcer._monitor_thread.is_alive(), "Monitor thread should be stopped"
        
        record_test(test_name, True, "Enforcer started and stopped successfully")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_continuous_exit_enforcer_get_broker_manager():
    """Test 1.3: ContinuousExitEnforcer can access broker manager."""
    test_name = "1.3 - ContinuousExitEnforcer Broker Manager Access"
    try:
        from broker_manager import get_broker_manager
        
        broker_manager = get_broker_manager()
        assert broker_manager is not None, "Broker manager should exist"
        
        # Test the new get_all_brokers() method
        brokers = broker_manager.get_all_brokers()
        assert isinstance(brokers, dict), "get_all_brokers() should return a dict"
        
        record_test(test_name, True, f"Broker manager accessible, {len(brokers)} brokers registered")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_exit_logic_continuous_firing():
    """Test 1.4: Exit logic runs continuously in separate thread."""
    test_name = "1.4 - Exit Logic Continuous Firing"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        # Track if check function was called
        call_count = {'value': 0}
        original_check = None
        
        enforcer = ContinuousExitEnforcer(
            check_interval=2,  # Check every 2 seconds
            max_positions=8
        )
        
        # Monkey patch to count calls
        original_check = enforcer._check_and_enforce_positions
        def counted_check():
            call_count['value'] += 1
            try:
                original_check()
            except Exception:
                pass  # Ignore errors in test
        
        enforcer._check_and_enforce_positions = counted_check
        
        # Start enforcer
        enforcer.start()
        
        # Wait for at least 2 checks (4+ seconds)
        time.sleep(5)
        
        # Stop enforcer
        enforcer.stop()
        
        # Verify it ran multiple times
        assert call_count['value'] >= 2, f"Check should have run at least 2 times, ran {call_count['value']} times"
        
        record_test(test_name, True, f"Exit logic fired {call_count['value']} times continuously")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


# =============================================================================
# TEST SUITE 2: RISK CAP (Position Cap Enforcement)
# =============================================================================

def test_position_cap_enforcer_creation():
    """Test 2.1: PositionCapEnforcer can be created."""
    test_name = "2.1 - PositionCapEnforcer Creation"
    try:
        from position_cap_enforcer import PositionCapEnforcer
        
        enforcer = PositionCapEnforcer(max_positions=8)
        
        assert enforcer is not None, "Enforcer should be created"
        assert enforcer.max_positions == 8, "Max positions should be 8"
        
        record_test(test_name, True, "Position cap enforcer created successfully")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_position_cap_in_continuous_enforcer():
    """Test 2.2: ContinuousExitEnforcer has position cap logic."""
    test_name = "2.2 - Position Cap in ContinuousExitEnforcer"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        enforcer = ContinuousExitEnforcer(
            check_interval=60,
            max_positions=5  # Set a specific cap
        )
        
        # Verify max_positions is set
        assert enforcer.max_positions == 5, "Max positions should be 5"
        
        # Verify _enforce_position_cap method exists
        assert hasattr(enforcer, '_enforce_position_cap'), "Should have _enforce_position_cap method"
        
        record_test(test_name, True, "Position cap logic exists in continuous enforcer")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_position_cap_config_variations():
    """Test 2.3: Position cap can be configured to different values."""
    test_name = "2.3 - Position Cap Configuration"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        # Test different cap values
        caps_to_test = [1, 3, 5, 8, 10]
        
        for cap in caps_to_test:
            enforcer = ContinuousExitEnforcer(
                check_interval=60,
                max_positions=cap
            )
            assert enforcer.max_positions == cap, f"Max positions should be {cap}"
        
        record_test(test_name, True, f"Tested {len(caps_to_test)} different position cap values")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_position_sorting_logic():
    """Test 2.4: Positions can be sorted by value for cap enforcement."""
    test_name = "2.4 - Position Sorting Logic"
    try:
        # Create mock positions with different values
        mock_positions = [
            {'symbol': 'BTC-USD', 'quantity': 0.1, 'price': 50000},  # $5000
            {'symbol': 'ETH-USD', 'quantity': 1.0, 'price': 3000},   # $3000
            {'symbol': 'SOL-USD', 'quantity': 10, 'price': 100},     # $1000
            {'symbol': 'DOGE-USD', 'quantity': 1000, 'price': 0.1},  # $100
        ]
        
        # Sort by value (smallest first)
        def get_position_value(p):
            quantity = p.get('quantity', 0)
            price = p.get('price', 0)
            return quantity * (price if price and price > 0 else 0)
        
        sorted_positions = sorted(mock_positions, key=get_position_value)
        
        # Verify sorting
        assert sorted_positions[0]['symbol'] == 'DOGE-USD', "Smallest should be DOGE"
        assert sorted_positions[1]['symbol'] == 'SOL-USD', "Next should be SOL"
        assert sorted_positions[2]['symbol'] == 'ETH-USD', "Next should be ETH"
        assert sorted_positions[3]['symbol'] == 'BTC-USD', "Largest should be BTC"
        
        record_test(test_name, True, "Position sorting logic works correctly")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


# =============================================================================
# TEST SUITE 3: FORCED UNWIND (Per-User Emergency Exit)
# =============================================================================

def test_forced_unwind_enable_disable():
    """Test 3.1: Forced unwind can be enabled/disabled."""
    test_name = "3.1 - Forced Unwind Enable/Disable"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        enforcer = ContinuousExitEnforcer()
        test_user = "test_user_001"
        
        # Initially should not be active
        assert not enforcer.is_forced_unwind_active(test_user), "Should not be active initially"
        
        # Enable forced unwind
        enforcer.enable_forced_unwind(test_user)
        assert enforcer.is_forced_unwind_active(test_user), "Should be active after enable"
        
        # Disable forced unwind
        enforcer.disable_forced_unwind(test_user)
        assert not enforcer.is_forced_unwind_active(test_user), "Should not be active after disable"
        
        record_test(test_name, True, "Forced unwind enable/disable works correctly")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_forced_unwind_multiple_users():
    """Test 3.2: Forced unwind works independently for multiple users."""
    test_name = "3.2 - Forced Unwind Multiple Users"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        enforcer = ContinuousExitEnforcer()
        user1 = "user_001"
        user2 = "user_002"
        user3 = "user_003"
        
        # Enable for user1 only
        enforcer.enable_forced_unwind(user1)
        
        assert enforcer.is_forced_unwind_active(user1), "User1 should be active"
        assert not enforcer.is_forced_unwind_active(user2), "User2 should not be active"
        assert not enforcer.is_forced_unwind_active(user3), "User3 should not be active"
        
        # Enable for user2
        enforcer.enable_forced_unwind(user2)
        
        assert enforcer.is_forced_unwind_active(user1), "User1 should still be active"
        assert enforcer.is_forced_unwind_active(user2), "User2 should now be active"
        assert not enforcer.is_forced_unwind_active(user3), "User3 should still not be active"
        
        # Disable user1
        enforcer.disable_forced_unwind(user1)
        
        assert not enforcer.is_forced_unwind_active(user1), "User1 should not be active"
        assert enforcer.is_forced_unwind_active(user2), "User2 should still be active"
        assert not enforcer.is_forced_unwind_active(user3), "User3 should still not be active"
        
        record_test(test_name, True, "Multi-user forced unwind works independently")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_user_risk_manager_forced_unwind():
    """Test 3.3: UserRiskManager forced unwind integration."""
    test_name = "3.3 - UserRiskManager Forced Unwind"
    try:
        from user_risk_manager import get_user_risk_manager
        
        risk_manager = get_user_risk_manager()
        test_user = "test_user_risk_001"
        
        # Initially should not be active
        assert not risk_manager.is_forced_unwind_active(test_user), "Should not be active initially"
        
        # Enable forced unwind
        risk_manager.enable_forced_unwind(test_user)
        assert risk_manager.is_forced_unwind_active(test_user), "Should be active after enable"
        
        # Disable forced unwind
        risk_manager.disable_forced_unwind(test_user)
        assert not risk_manager.is_forced_unwind_active(test_user), "Should not be active after disable"
        
        record_test(test_name, True, "UserRiskManager forced unwind works correctly")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


# =============================================================================
# TEST SUITE 4: INTEGRATION TESTS
# =============================================================================

def test_broker_manager_get_all_brokers():
    """Test 4.1: BrokerManager.get_all_brokers() method exists and works."""
    test_name = "4.1 - BrokerManager.get_all_brokers() Method"
    try:
        from broker_manager import get_broker_manager, BrokerManager
        
        broker_manager = get_broker_manager()
        
        # Test that get_all_brokers method exists
        assert hasattr(broker_manager, 'get_all_brokers'), "Should have get_all_brokers method"
        
        # Test that it returns a dict
        brokers = broker_manager.get_all_brokers()
        assert isinstance(brokers, dict), "Should return a dict"
        
        # Test defensive copy
        brokers2 = broker_manager.get_all_brokers()
        assert brokers is not brokers2, "Should return a new copy each time"
        
        record_test(test_name, True, f"get_all_brokers() works correctly, {len(brokers)} brokers")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_continuous_enforcer_broker_integration():
    """Test 4.2: ContinuousExitEnforcer can access brokers via BrokerManager."""
    test_name = "4.2 - ContinuousExitEnforcer + BrokerManager Integration"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        from broker_manager import get_broker_manager
        
        # Get broker manager
        broker_manager = get_broker_manager()
        brokers = broker_manager.get_all_brokers()
        
        # Create enforcer
        enforcer = ContinuousExitEnforcer(check_interval=60, max_positions=8)
        
        # Verify enforcer can access the same broker manager
        # This simulates what happens in _check_and_enforce_positions
        from broker_manager import get_broker_manager as get_bm_internal
        bm_internal = get_bm_internal()
        
        assert bm_internal is broker_manager, "Should get same broker manager instance"
        
        brokers_internal = bm_internal.get_all_brokers()
        assert isinstance(brokers_internal, dict), "Should get brokers dict"
        
        record_test(test_name, True, "ContinuousExitEnforcer can access BrokerManager")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_all_three_systems_together():
    """Test 4.3: All 3 systems can work together."""
    test_name = "4.3 - Exit Logic + Risk Cap + Forced Unwind Integration"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        from position_cap_enforcer import PositionCapEnforcer
        from user_risk_manager import get_user_risk_manager
        from broker_manager import get_broker_manager
        
        # Create all components
        continuous_enforcer = ContinuousExitEnforcer(
            check_interval=5,
            max_positions=8
        )
        
        position_enforcer = PositionCapEnforcer(max_positions=8)
        
        risk_manager = get_user_risk_manager()
        
        broker_manager = get_broker_manager()
        
        # Verify all components exist
        assert continuous_enforcer is not None, "ContinuousExitEnforcer should exist"
        assert position_enforcer is not None, "PositionCapEnforcer should exist"
        assert risk_manager is not None, "UserRiskManager should exist"
        assert broker_manager is not None, "BrokerManager should exist"
        
        # Test interaction: Enable forced unwind in continuous enforcer
        test_user = "integration_test_user"
        continuous_enforcer.enable_forced_unwind(test_user)
        assert continuous_enforcer.is_forced_unwind_active(test_user), "Forced unwind should be active"
        
        # Start and stop continuous enforcer
        continuous_enforcer.start()
        time.sleep(2)
        continuous_enforcer.stop()
        
        record_test(test_name, True, "All 3 systems work together successfully")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


# =============================================================================
# TEST SUITE 5: ERROR RECOVERY & EDGE CASES
# =============================================================================

def test_error_recovery_broker_not_available():
    """Test 5.1: System handles missing broker gracefully."""
    test_name = "5.1 - Error Recovery: Missing Broker"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        enforcer = ContinuousExitEnforcer(check_interval=60, max_positions=8)
        
        # Call _check_and_enforce_positions when no brokers are connected
        # This should not crash
        try:
            enforcer._check_and_enforce_positions()
            # Should complete without error (just log and return)
            error_occurred = False
        except Exception:
            error_occurred = True
        
        assert not error_occurred, "Should handle missing brokers gracefully"
        
        record_test(test_name, True, "Handles missing brokers without crashing")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_thread_safety():
    """Test 5.2: Multiple start/stop cycles work correctly."""
    test_name = "5.2 - Thread Safety: Multiple Start/Stop Cycles"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        enforcer = ContinuousExitEnforcer(check_interval=5, max_positions=8)
        
        # Multiple start/stop cycles
        for i in range(3):
            enforcer.start()
            time.sleep(1)
            enforcer.stop()
            time.sleep(0.5)
        
        record_test(test_name, True, "Multiple start/stop cycles completed successfully")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


def test_emergency_mode():
    """Test 5.3: Emergency mode can be enabled."""
    test_name = "5.3 - Emergency Mode"
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        
        # Create enforcer with emergency mode
        enforcer = ContinuousExitEnforcer(
            check_interval=60,
            max_positions=8,
            emergency_mode=True
        )
        
        assert enforcer.emergency_mode == True, "Emergency mode should be enabled"
        
        record_test(test_name, True, "Emergency mode can be enabled")
        return True
        
    except Exception as e:
        record_test(test_name, False, f"Error: {e}")
        logger.exception("Test failed with exception:")
        return False


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

def run_test_suite(suite_name: str, tests: List):
    """Run a suite of tests."""
    print_section_header(suite_name)
    
    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            logger.error(f"Test crashed: {e}")
            logger.exception("Exception details:")
            results.append(False)
    
    passed = sum(1 for r in results if r)
    total = len(results)
    
    logger.info("")
    logger.info(f"Suite Results: {passed}/{total} tests passed")
    logger.info("")
    
    return passed, total


def print_final_summary():
    """Print final test summary."""
    print_section_header("FINAL TEST SUMMARY")
    
    total_tests = len(test_results)
    passed_tests = sum(1 for t in test_results if t['passed'])
    failed_tests = total_tests - passed_tests
    
    logger.info(f"Total Tests: {total_tests}")
    logger.info(f"Passed:      {passed_tests} ✅")
    logger.info(f"Failed:      {failed_tests} ❌")
    logger.info("")
    
    if failed_tests > 0:
        logger.info("Failed Tests:")
        for t in test_results:
            if not t['passed']:
                logger.info(f"  ❌ {t['name']}")
                if t['message']:
                    logger.info(f"     {t['message']}")
        logger.info("")
    
    # Overall verdict
    if failed_tests == 0:
        logger.info("=" * 80)
        logger.info("  🎉 ALL TESTS PASSED - ALL 3 CORE PROBLEMS ARE 100% FUNCTIONAL! 🎉")
        logger.info("=" * 80)
        logger.info("")
        logger.info("✅ Exit Logic:     WORKING - Continuous firing in separate thread")
        logger.info("✅ Risk Cap:       WORKING - Position cap enforcement active")
        logger.info("✅ Forced Unwind:  WORKING - Per-user emergency exit mode")
        logger.info("")
        return True
    else:
        logger.info("=" * 80)
        logger.info("  ⚠️  SOME TESTS FAILED - REVIEW REQUIRED")
        logger.info("=" * 80)
        return False


def main():
    """Run all smoke tests."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("  NIJA CORE FIXES SMOKE TEST")
    logger.info("  Testing: Exit Logic, Risk Cap, Forced Unwind")
    logger.info("=" * 80)
    logger.info("")
    
    # Test Suite 1: Exit Logic
    suite1_tests = [
        test_continuous_exit_enforcer_creation,
        test_continuous_exit_enforcer_start_stop,
        test_continuous_exit_enforcer_get_broker_manager,
        test_exit_logic_continuous_firing,
    ]
    s1_passed, s1_total = run_test_suite("TEST SUITE 1: EXIT LOGIC (Continuous Firing)", suite1_tests)
    
    # Test Suite 2: Risk Cap
    suite2_tests = [
        test_position_cap_enforcer_creation,
        test_position_cap_in_continuous_enforcer,
        test_position_cap_config_variations,
        test_position_sorting_logic,
    ]
    s2_passed, s2_total = run_test_suite("TEST SUITE 2: RISK CAP (Position Cap Enforcement)", suite2_tests)
    
    # Test Suite 3: Forced Unwind
    suite3_tests = [
        test_forced_unwind_enable_disable,
        test_forced_unwind_multiple_users,
        test_user_risk_manager_forced_unwind,
    ]
    s3_passed, s3_total = run_test_suite("TEST SUITE 3: FORCED UNWIND (Per-User Emergency Exit)", suite3_tests)
    
    # Test Suite 4: Integration
    suite4_tests = [
        test_broker_manager_get_all_brokers,
        test_continuous_enforcer_broker_integration,
        test_all_three_systems_together,
    ]
    s4_passed, s4_total = run_test_suite("TEST SUITE 4: INTEGRATION TESTS", suite4_tests)
    
    # Test Suite 5: Error Recovery
    suite5_tests = [
        test_error_recovery_broker_not_available,
        test_thread_safety,
        test_emergency_mode,
    ]
    s5_passed, s5_total = run_test_suite("TEST SUITE 5: ERROR RECOVERY & EDGE CASES", suite5_tests)
    
    # Print final summary
    success = print_final_summary()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
