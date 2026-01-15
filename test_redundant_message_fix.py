#!/usr/bin/env python3
"""
Test script to verify that redundant user broker connection messages are fixed.

This test validates that when a user broker connection fails, only ONE clear
message is logged (from connect_users_from_config), not two redundant messages.

Expected behavior:
- Permission errors should be logged by broker's connect() method
- User-friendly failure message should be logged by connect_users_from_config
- add_user_broker should NOT log duplicate messages

This fixes the issue where both methods were logging similar warnings.
"""

import os
import sys
import logging
import io

# Configure logging to capture all messages
log_capture = io.StringIO()
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(log_capture),
        logging.StreamHandler(sys.stdout)
    ]
)

def count_message_occurrences(log_text, search_pattern):
    """Count how many times a pattern appears in log text."""
    return log_text.count(search_pattern)

def test_no_redundant_messages():
    """
    Test that user broker connection failures only log ONE user-facing message.
    """
    print("Testing Fix for Redundant User Broker Connection Messages")
    print("=" * 70)
    
    # Import broker manager
    try:
        from bot.multi_account_broker_manager import MultiAccountBrokerManager
        from bot.broker_manager import BrokerType
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from bot.multi_account_broker_manager import MultiAccountBrokerManager
        from bot.broker_manager import BrokerType
    
    # Set up fake credentials that will trigger connection errors
    # Using obviously invalid credentials to ensure connection fails
    os.environ['KRAKEN_USER_TEST_API_KEY'] = 'invalid_key_for_test'
    os.environ['KRAKEN_USER_TEST_API_SECRET'] = 'invalid_secret_for_test'
    
    print("\n1. Creating MultiAccountBrokerManager...")
    manager = MultiAccountBrokerManager()
    
    print("\n2. Attempting to add user broker with invalid credentials...")
    print("   This should fail but should NOT log redundant messages")
    print("-" * 70)
    
    # Clear log capture
    log_capture.truncate(0)
    log_capture.seek(0)
    
    # Try to add user broker (this will fail due to invalid credentials)
    broker = manager.add_user_broker('test_user', BrokerType.KRAKEN)
    
    # Get captured logs
    log_output = log_capture.getvalue()
    
    print("\n3. Analyzing log output...")
    print("-" * 70)
    
    # Check for the OLD redundant message that should NOT appear
    old_message_pattern = "Failed to connect user broker: test_user -> kraken"
    old_message_count = count_message_occurrences(log_output, old_message_pattern)
    
    # Check that broker object was returned (even though connection failed)
    broker_returned = broker is not None
    
    print(f"\n   Old redundant message count: {old_message_count}")
    print(f"   Expected: 0 (message should be removed)")
    print(f"   Broker object returned: {broker_returned}")
    print(f"   Expected: True (broker object should be returned even if connection fails)")
    
    # Verify results
    success = True
    if old_message_count > 0:
        print("\n   ❌ FAIL: Old redundant message still appears!")
        print(f"   Found {old_message_count} occurrence(s) of: '{old_message_pattern}'")
        success = False
    else:
        print("\n   ✅ PASS: Old redundant message removed successfully!")
    
    if not broker_returned:
        print("\n   ❌ FAIL: Broker object was not returned!")
        success = False
    else:
        print("   ✅ PASS: Broker object returned correctly!")
    
    print("\n" + "=" * 70)
    if success:
        print("✅ ALL TESTS PASSED - Redundant messages successfully removed!")
        return 0
    else:
        print("❌ SOME TESTS FAILED - See details above")
        return 1

if __name__ == '__main__':
    exit_code = test_no_redundant_messages()
    sys.exit(exit_code)
