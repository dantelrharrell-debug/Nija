#!/usr/bin/env python3
"""
Integration test to verify Kraken permission error logging behavior.
This simulates what happens when multiple users have permission errors.
"""

import sys
import os
import logging
import io
import threading
from unittest.mock import Mock, patch, MagicMock

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import KrakenBroker, AccountType

def test_permission_error_logging():
    """
    Test that permission error details are logged only once,
    then subsequent errors get brief reference messages.
    """
    print("\n" + "="*80)
    print("Integration Test: Kraken Permission Error Logging Behavior")
    print("="*80)
    
    # Reset class-level state
    KrakenBroker._permission_error_details_logged = False
    KrakenBroker._permission_failed_accounts.clear()
    
    # Capture log output
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setFormatter(logging.Formatter('%(levelname)s | %(message)s'))
    
    logger = logging.getLogger('nija.broker')
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    
    # Mock krakenex and pykrakenapi at the module level where they're imported
    with patch('krakenex.API') as mock_api_class, \
         patch('pykrakenapi.KrakenAPI') as mock_kraken_api_class:
        
        # Setup mock API to return permission error
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        mock_kraken_api_class.return_value = Mock()
        
        # Simulate permission error response
        permission_error_response = {
            'error': ['EGeneral:Permission denied'],
            'result': {}
        }
        mock_api.query_private.return_value = permission_error_response
        
        print("\n1. First user (test_user_alice) attempts connection...")
        print("   Expected: Full detailed permission error instructions")
        print("-"*80)
        
        # First user connection attempt
        broker1 = KrakenBroker(account_type=AccountType.USER, user_id="test_user_alice")
        result1 = broker1.connect()
        
        log_output_1 = log_capture.getvalue()
        log_capture.truncate(0)
        log_capture.seek(0)
        
        # Check that detailed instructions were logged
        has_detailed_instructions_1 = "To fix this issue:" in log_output_1
        has_enable_permissions_1 = "Enable these permissions:" in log_output_1
        has_query_funds_1 = "Query Funds" in log_output_1
        
        print(f"   Connection result: {result1}")
        print(f"   ✅ Has 'To fix this issue:': {has_detailed_instructions_1}")
        print(f"   ✅ Has 'Enable these permissions:': {has_enable_permissions_1}")
        print(f"   ✅ Has 'Query Funds': {has_query_funds_1}")
        print(f"   Flag after first user: {KrakenBroker._permission_error_details_logged}")
        
        print("\n2. Second user (test_user_bob) attempts connection...")
        print("   Expected: Brief reference message ONLY, not full instructions")
        print("-"*80)
        
        # Second user connection attempt
        broker2 = KrakenBroker(account_type=AccountType.USER, user_id="test_user_bob")
        result2 = broker2.connect()
        
        log_output_2 = log_capture.getvalue()
        log_capture.truncate(0)
        log_capture.seek(0)
        
        # Check that detailed instructions were NOT logged again
        has_detailed_instructions_2 = "To fix this issue:" in log_output_2
        has_enable_permissions_2 = "Enable these permissions:" in log_output_2
        has_reference_message_2 = "see above for fix instructions" in log_output_2
        
        print(f"   Connection result: {result2}")
        print(f"   ✅ Has 'To fix this issue:': {has_detailed_instructions_2} (should be False)")
        print(f"   ✅ Has 'Enable these permissions:': {has_enable_permissions_2} (should be False)")
        print(f"   ✅ Has reference message: {has_reference_message_2} (should be True)")
        print(f"   Flag after second user: {KrakenBroker._permission_error_details_logged}")
        
        print("\n3. Third user (test_user_charlie) attempts connection...")
        print("   Expected: Brief reference message ONLY (same as second user)")
        print("-"*80)
        
        # Third user connection attempt
        broker3 = KrakenBroker(account_type=AccountType.USER, user_id="test_user_charlie")
        result3 = broker3.connect()
        
        log_output_3 = log_capture.getvalue()
        
        # Check that detailed instructions were NOT logged again
        has_detailed_instructions_3 = "To fix this issue:" in log_output_3
        has_reference_message_3 = "see above for fix instructions" in log_output_3
        
        print(f"   Connection result: {result3}")
        print(f"   ✅ Has 'To fix this issue:': {has_detailed_instructions_3} (should be False)")
        print(f"   ✅ Has reference message: {has_reference_message_3} (should be True)")
        print(f"   Flag after third user: {KrakenBroker._permission_error_details_logged}")
    
    # Clean up
    logger.removeHandler(handler)
    
    # Verify results
    print("\n" + "="*80)
    print("TEST RESULTS:")
    print("="*80)
    
    all_passed = True
    
    # Test 1: First user should get detailed instructions
    test1_passed = has_detailed_instructions_1 and has_enable_permissions_1 and has_query_funds_1
    print(f"✅ Test 1 - First user gets detailed instructions: {'PASS' if test1_passed else 'FAIL'}")
    all_passed = all_passed and test1_passed
    
    # Test 2: Second user should NOT get detailed instructions
    test2_passed = not has_detailed_instructions_2 and not has_enable_permissions_2 and has_reference_message_2
    print(f"✅ Test 2 - Second user gets brief message only: {'PASS' if test2_passed else 'FAIL'}")
    all_passed = all_passed and test2_passed
    
    # Test 3: Third user should NOT get detailed instructions
    test3_passed = not has_detailed_instructions_3 and has_reference_message_3
    print(f"✅ Test 3 - Third user gets brief message only: {'PASS' if test3_passed else 'FAIL'}")
    all_passed = all_passed and test3_passed
    
    # Test 4: Flag should be set and persist
    test4_passed = KrakenBroker._permission_error_details_logged == True
    print(f"✅ Test 4 - Flag persists correctly: {'PASS' if test4_passed else 'FAIL'}")
    all_passed = all_passed and test4_passed
    
    print("="*80)
    if all_passed:
        print("✅ ALL TESTS PASSED - Log spam prevention is working correctly!")
    else:
        print("❌ SOME TESTS FAILED - Review output above")
    print("="*80 + "\n")
    
    return all_passed

if __name__ == "__main__":
    success = test_permission_error_logging()
    sys.exit(0 if success else 1)
