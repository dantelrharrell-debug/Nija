#!/usr/bin/env python3
"""
Test script to verify that user credential detection works correctly.

This tests the fix for the issue where users without credentials were
showing "Connection failed" instead of "NOT CONFIGURED".
"""

import os
import sys

# Add bot directory to path
bot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot')
sys.path.insert(0, bot_dir)

from multi_account_broker_manager import MultiAccountBrokerManager
from broker_manager import BrokerType


def test_credential_detection():
    """Test that user_has_credentials returns correct values."""
    print("=" * 70)
    print("TESTING USER CREDENTIAL DETECTION")
    print("=" * 70)
    
    # Create a manager
    manager = MultiAccountBrokerManager()
    
    # Test case 1: Try to add Kraken broker for daivon_frazier (no credentials)
    print("\n📋 Test 1: Adding Kraken broker for daivon_frazier (no credentials)")
    broker = manager.add_user_broker("daivon_frazier", BrokerType.KRAKEN)
    
    if broker:
        print(f"   Broker created: ✅")
        print(f"   Broker connected: {broker.connected}")
        print(f"   Credentials configured: {broker.credentials_configured if hasattr(broker, 'credentials_configured') else 'N/A'}")
    else:
        print(f"   Broker created: ❌")
    
    has_creds = manager.user_has_credentials("daivon_frazier", BrokerType.KRAKEN)
    print(f"   user_has_credentials returns: {has_creds}")
    
    if not has_creds:
        print("   ✅ PASS: Correctly detected NO credentials")
    else:
        print("   ❌ FAIL: Incorrectly reported credentials exist")
    
    # Test case 2: Try to add Kraken broker for tania_gilbert (no credentials)
    print("\n📋 Test 2: Adding Kraken broker for tania_gilbert (no credentials)")
    broker = manager.add_user_broker("tania_gilbert", BrokerType.KRAKEN)
    
    if broker:
        print(f"   Broker created: ✅")
        print(f"   Broker connected: {broker.connected}")
        print(f"   Credentials configured: {broker.credentials_configured if hasattr(broker, 'credentials_configured') else 'N/A'}")
    else:
        print(f"   Broker created: ❌")
    
    has_creds = manager.user_has_credentials("tania_gilbert", BrokerType.KRAKEN)
    print(f"   user_has_credentials returns: {has_creds}")
    
    if not has_creds:
        print("   ✅ PASS: Correctly detected NO credentials")
    else:
        print("   ❌ FAIL: Incorrectly reported credentials exist")
    
    # Test case 3: Try to add Alpaca broker for tania_gilbert (no credentials)
    print("\n📋 Test 3: Adding Alpaca broker for tania_gilbert (no credentials)")
    broker = manager.add_user_broker("tania_gilbert", BrokerType.ALPACA)
    
    if broker:
        print(f"   Broker created: ✅")
        print(f"   Broker connected: {broker.connected}")
        print(f"   Credentials configured: {broker.credentials_configured if hasattr(broker, 'credentials_configured') else 'N/A'}")
    else:
        print(f"   Broker created: ❌")
    
    has_creds = manager.user_has_credentials("tania_gilbert", BrokerType.ALPACA)
    print(f"   user_has_credentials returns: {has_creds}")
    
    if not has_creds:
        print("   ✅ PASS: Correctly detected NO credentials")
    else:
        print("   ❌ FAIL: Incorrectly reported credentials exist")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    test_credential_detection()
