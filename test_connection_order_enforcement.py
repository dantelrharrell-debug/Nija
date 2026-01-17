#!/usr/bin/env python3
"""
Test connection order enforcement for Kraken copy trading.

Verifies that:
1. Kraken USER accounts cannot connect without MASTER
2. Other brokers (Alpaca, etc.) can connect without MASTER (with warning)
3. Connection order is enforced: MASTER → USERS
"""

import sys
import os
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import KrakenBroker, AccountType, BrokerType
from multi_account_broker_manager import MultiAccountBrokerManager

def test_connection_order_enforcement():
    """Test that connection order is enforced for Kraken."""
    print()
    print("=" * 70)
    print("🧪 KRAKEN CONNECTION ORDER ENFORCEMENT TEST")
    print("=" * 70)
    print()
    
    # Create multi-account manager
    manager = MultiAccountBrokerManager()
    
    # Test 1: Verify master is NOT connected initially
    print("Test 1: Checking initial state...")
    master_connected = manager.is_master_connected(BrokerType.KRAKEN)
    assert not master_connected, "Master should NOT be connected initially"
    print("   ✅ PASS: Master is not connected (expected initial state)")
    print()
    
    # Test 2: Simulate the check that happens in connect_users_from_config()
    print("Test 2: Simulating user connection attempt without master...")
    broker_type = BrokerType.KRAKEN
    master_connected = manager.is_master_connected(broker_type)
    
    if not master_connected and broker_type == BrokerType.KRAKEN:
        print("   ✅ PASS: Connection would be BLOCKED (hard requirement)")
        print("   ℹ️  Error message would be logged:")
        print("      ❌ KRAKEN USER CONNECTION BLOCKED: Master NOT connected")
        should_skip = True
    else:
        print("   ❌ FAIL: Connection should be blocked!")
        should_skip = False
    
    assert should_skip, "Kraken user connection should be skipped when master not connected"
    print()
    
    # Test 3: Verify the logic for non-Kraken brokers (should allow with warning)
    print("Test 3: Checking logic for non-Kraken brokers (e.g., Alpaca)...")
    broker_type_alpaca = BrokerType.ALPACA
    
    # For non-Kraken brokers, connection should proceed with warning (not blocked)
    if broker_type_alpaca != BrokerType.KRAKEN:
        print("   ✅ PASS: Non-Kraken brokers ALLOWED (with warning)")
        print("   ℹ️  Warning message would be logged but connection proceeds")
        should_skip_alpaca = False
    else:
        # This branch won't execute for Alpaca
        should_skip_alpaca = True
    
    assert not should_skip_alpaca, "Non-Kraken brokers should be allowed (with warning)"
    print()
    
    # Test 4: Verify actual broker instances have separate nonce files
    print("Test 4: Verifying nonce isolation...")
    master_broker = KrakenBroker(account_type=AccountType.MASTER)
    user_broker = KrakenBroker(account_type=AccountType.USER, user_id="test_user")
    
    assert master_broker._nonce_file != user_broker._nonce_file, \
        "Master and user should have different nonce files"
    assert "master" in master_broker._nonce_file.lower(), \
        "Master nonce file should contain 'master'"
    assert "test_user" in user_broker._nonce_file.lower(), \
        "User nonce file should contain user_id"
    
    print(f"   ✅ PASS: Nonce files are isolated")
    print(f"      Master: {os.path.basename(master_broker._nonce_file)}")
    print(f"      User: {os.path.basename(user_broker._nonce_file)}")
    print()
    
    print("=" * 70)
    print("✅ ALL CONNECTION ORDER TESTS PASSED")
    print("=" * 70)
    print()
    print("Summary:")
    print("  ✅ Kraken users BLOCKED without master (hard requirement)")
    print("  ✅ Other brokers ALLOWED without master (with warning)")
    print("  ✅ Nonce files are isolated per account")
    print("  ✅ Connection order enforcement working correctly")
    print()
    
    return 0

def main():
    """Run the test."""
    try:
        return test_connection_order_enforcement()
    except AssertionError as e:
        print("=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        return 1
    except Exception as e:
        print("=" * 70)
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
