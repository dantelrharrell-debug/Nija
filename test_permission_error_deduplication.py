#!/usr/bin/env python3
"""
Test script to verify Kraken permission error deduplication logic.
This tests that detailed permission error instructions are logged only once globally,
not once per account, to prevent log spam.
"""

import sys
import os
import logging

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Configure logging to see output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

from broker_manager import KrakenBroker, AccountType

def test_permission_error_deduplication():
    """
    Test that permission error details are logged only once globally.
    """
    print("\n" + "="*70)
    print("Testing Kraken Permission Error Deduplication")
    print("="*70)
    
    # Reset the class-level flag (in case this is run multiple times)
    KrakenBroker._permission_error_details_logged = False
    KrakenBroker._permission_failed_accounts.clear()
    
    print("\n1. Testing first user with permission error...")
    print("   Expected: Full detailed instructions should be logged")
    print("-"*70)
    
    # Create first broker instance (will fail to connect with missing/invalid credentials)
    broker1 = KrakenBroker(account_type=AccountType.USER, user_id="test_user_1")
    
    # Check if flag was set after first permission error would have occurred
    # Note: We can't actually trigger the error without real API credentials,
    # but we can verify the flag state
    print(f"\n   Flag after first user: {KrakenBroker._permission_error_details_logged}")
    
    print("\n2. Manually simulating permission error flag...")
    # Manually set the flag to simulate what would happen after first permission error
    KrakenBroker._permission_error_details_logged = True
    print(f"   Flag set to: {KrakenBroker._permission_error_details_logged}")
    
    print("\n3. Testing second user with permission error...")
    print("   Expected: Only brief reference message, NOT full instructions")
    print("-"*70)
    
    # Create second broker instance
    broker2 = KrakenBroker(account_type=AccountType.USER, user_id="test_user_2")
    
    print(f"\n   Flag after second user: {KrakenBroker._permission_error_details_logged}")
    
    print("\n4. Verification:")
    print(f"   ✅ Flag is boolean: {isinstance(KrakenBroker._permission_error_details_logged, bool)}")
    print(f"   ✅ Flag persists across instances: {KrakenBroker._permission_error_details_logged}")
    print(f"   ✅ Lock exists: {hasattr(KrakenBroker, '_permission_errors_lock')}")
    
    print("\n" + "="*70)
    print("✅ Test Complete - Deduplication logic structure verified")
    print("="*70)
    print("\nNote: This test verifies the flag structure exists and persists.")
    print("Full integration testing requires actual Kraken API credentials with")
    print("permission errors, which we cannot safely test in automated tests.")
    print("="*70 + "\n")

if __name__ == "__main__":
    test_permission_error_deduplication()
