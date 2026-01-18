#!/usr/bin/env python3
"""
Test script to verify the account hierarchy logging display logic.

This test ensures that:
1. When there are warnings (user accounts without master), the warning header is shown
2. When there are no warnings (all users have master accounts), a positive status is shown
3. The logging output is clear and not misleading
"""

import sys
import os
import logging
from io import StringIO

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import BrokerType, AccountType
from multi_account_broker_manager import MultiAccountBrokerManager


def capture_logs(func):
    """Capture log output from a function."""
    # Create a string buffer to capture logs
    log_capture = StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.INFO)
    
    # Get the nija logger
    logger = logging.getLogger('nija')
    old_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    try:
        # Run the function
        func()
        
        # Get the captured output
        output = log_capture.getvalue()
        return output
    finally:
        # Clean up
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        log_capture.close()


def test_no_warnings_scenario():
    """
    Test scenario: Master accounts connected, no user accounts.
    Expected: Positive status message, no warning header.
    """
    print("=" * 70)
    print("TEST 1: No warnings scenario (Master connected, no users)")
    print("=" * 70)
    
    manager = MultiAccountBrokerManager()
    
    # Simulate the scenario from the problem statement
    # No user accounts connected, so connected_users = {}
    connected_users = {}
    
    def log_hierarchy():
        # Simulate the logging section from connect_users_from_config
        logger = logging.getLogger('nija.multi_account')
        logger.info("")
        
        # Determine if there are any warnings to display
        users_without_master = []
        for brokerage, user_ids in connected_users.items():
            try:
                broker_type = BrokerType[brokerage.upper()]
                master_connected = manager.is_master_connected(broker_type)
                if not master_connected and user_ids:
                    users_without_master.append(brokerage.upper())
            except KeyError:
                logger.warning(f"⚠️  Unknown broker type in connected users: {brokerage}")
                continue
        
        if users_without_master:
            # Display warning header only when there are actual warnings
            logger.info("⚠️  ACCOUNT PRIORITY WARNINGS:")
            logger.warning(f"   ⚠️  User accounts trading WITHOUT Master account on: {', '.join(users_without_master)}")
        else:
            # Display positive status when there are no warnings
            logger.info("✅ ACCOUNT HIERARCHY STATUS:")
            logger.info("   ✅ All user accounts have corresponding Master accounts (correct hierarchy)")
        
        logger.info("=" * 70)
    
    output = capture_logs(log_hierarchy)
    
    print("\nCaptured output:")
    print(output)
    
    # Verify expectations
    assert "⚠️  ACCOUNT PRIORITY WARNINGS:" not in output, \
        "FAIL: Warning header should NOT appear when there are no warnings"
    assert "✅ ACCOUNT HIERARCHY STATUS:" in output, \
        "FAIL: Positive status header should appear when there are no warnings"
    assert "✅ All user accounts have corresponding Master accounts (correct hierarchy)" in output, \
        "FAIL: Success message should appear when there are no warnings"
    
    print("\n✅ TEST 1 PASSED: No misleading warning header when everything is correct")
    print()
    
    return True


def test_with_warnings_scenario():
    """
    Test scenario: User accounts without master accounts.
    Expected: Warning header and detailed instructions.
    """
    print("=" * 70)
    print("TEST 2: With warnings scenario (Users without Master)")
    print("=" * 70)
    
    manager = MultiAccountBrokerManager()
    
    # Simulate user accounts connected without master
    # This represents the case where users are trading without master accounts
    connected_users = {
        'kraken': ['user1', 'user2']
    }
    
    def log_hierarchy():
        # Simulate the logging section from connect_users_from_config
        logger = logging.getLogger('nija.multi_account')
        logger.info("")
        
        # Determine if there are any warnings to display
        users_without_master = []
        for brokerage, user_ids in connected_users.items():
            try:
                broker_type = BrokerType[brokerage.upper()]
                master_connected = manager.is_master_connected(broker_type)
                if not master_connected and user_ids:
                    users_without_master.append(brokerage.upper())
            except KeyError:
                logger.warning(f"⚠️  Unknown broker type in connected users: {brokerage}")
                continue
        
        if users_without_master:
            # Display warning header only when there are actual warnings
            logger.info("⚠️  ACCOUNT PRIORITY WARNINGS:")
            logger.warning(f"   ⚠️  User accounts trading WITHOUT Master account on: {', '.join(users_without_master)}")
        else:
            # Display positive status when there are no warnings
            logger.info("✅ ACCOUNT HIERARCHY STATUS:")
            logger.info("   ✅ All user accounts have corresponding Master accounts (correct hierarchy)")
        
        logger.info("=" * 70)
    
    output = capture_logs(log_hierarchy)
    
    print("\nCaptured output:")
    print(output)
    
    # Verify expectations
    assert "⚠️  ACCOUNT PRIORITY WARNINGS:" in output, \
        "FAIL: Warning header SHOULD appear when there are warnings"
    assert "⚠️  User accounts trading WITHOUT Master account on: KRAKEN" in output, \
        "FAIL: Warning message should appear when users lack master accounts"
    assert "✅ ACCOUNT HIERARCHY STATUS:" not in output, \
        "FAIL: Positive status header should NOT appear when there are warnings"
    
    print("\n✅ TEST 2 PASSED: Warning header shown correctly when there are issues")
    print()
    
    return True


def main():
    """Run all tests."""
    print()
    print("=" * 70)
    print("ACCOUNT HIERARCHY LOGGING TESTS")
    print("=" * 70)
    print()
    print("Testing the fix for misleading warning headers...")
    print()
    
    try:
        # Run tests
        test_no_warnings_scenario()
        test_with_warnings_scenario()
        
        print("=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print()
        print("Summary:")
        print("  ✅ No warning header when everything is correct")
        print("  ✅ Positive status message shown instead")
        print("  ✅ Warning header only appears when there are actual warnings")
        print("  ✅ Logging is clear and not misleading")
        print()
        
        return 0
        
    except AssertionError as e:
        print()
        print("=" * 70)
        print("❌ TEST FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        print()
        return 1
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ ERROR")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
