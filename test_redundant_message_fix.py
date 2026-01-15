#!/usr/bin/env python3
"""
Test script to verify that redundant user broker connection messages are fixed.
"""

import os
import sys
import logging
import io

def test_no_redundant_messages():
    """Test that user broker connection failures only log ONE user-facing message."""
    print("Testing Fix for Redundant User Broker Connection Messages")
    print("=" * 70)
    
    # Configure logging
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setFormatter(logging.Formatter('%(levelname)s | %(message)s'))
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter('%(levelname)s | %(message)s'))
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)
    root_logger.addHandler(stdout_handler)
    
    # Import broker manager
    try:
        from bot.multi_account_broker_manager import MultiAccountBrokerManager
        from bot.broker_manager import BrokerType
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from bot.multi_account_broker_manager import MultiAccountBrokerManager
        from bot.broker_manager import BrokerType
    
    # Save original env
    original_env = {
        'KRAKEN_USER_TEST_API_KEY': os.environ.get('KRAKEN_USER_TEST_API_KEY'),
        'KRAKEN_USER_TEST_API_SECRET': os.environ.get('KRAKEN_USER_TEST_API_SECRET')
    }
    
    try:
        # Set fake credentials
        os.environ['KRAKEN_USER_TEST_API_KEY'] = 'invalid_key_for_test'
        os.environ['KRAKEN_USER_TEST_API_SECRET'] = 'invalid_secret_for_test'
        
        print("\n1. Creating MultiAccountBrokerManager...")
        manager = MultiAccountBrokerManager()
        
        print("\n2. Attempting to add user broker with invalid credentials...")
        log_capture.truncate(0)
        log_capture.seek(0)
        
        broker = manager.add_user_broker('test_user', BrokerType.KRAKEN)
        log_output = log_capture.getvalue()
        
        print("\n3. Analyzing log output...")
        old_message = "Failed to connect user broker: test_user -> kraken"
        old_count = log_output.count(old_message)
        broker_returned = broker is not None
        
        print(f"\n   Old redundant message count: {old_count} (expected: 0)")
        print(f"   Broker object returned: {broker_returned} (expected: True)")
        
        success = old_count == 0 and broker_returned
        
        print("\n" + "=" * 70)
        if success:
            print("✅ ALL TESTS PASSED")
            return 0
        else:
            print("❌ SOME TESTS FAILED")
            return 1
    
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        root_logger.removeHandler(handler)
        root_logger.removeHandler(stdout_handler)

if __name__ == '__main__':
    sys.exit(test_no_redundant_messages())
