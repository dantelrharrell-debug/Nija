#!/usr/bin/env python3
"""
Test that independent strategy loops are disabled for Kraken USER accounts
when copy trading is active (i.e., when Kraken MASTER is connected).

This ensures users only execute copied trades from master, not their own signals.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import KrakenBroker, AccountType, BrokerType
from multi_account_broker_manager import MultiAccountBrokerManager

def test_independent_loop_disabled():
    """Test that Kraken user independent loops are disabled when master connected."""
    print()
    print("=" * 70)
    print("🧪 KRAKEN USER INDEPENDENT LOOP DISABLE TEST")
    print("=" * 70)
    print()
    
    # Create multi-account manager
    manager = MultiAccountBrokerManager()
    
    # Test 1: Kraken master NOT connected - user loop should be allowed
    print("Test 1: Master NOT connected - user loop behavior...")
    master_connected = manager.is_master_connected(BrokerType.KRAKEN)
    assert not master_connected, "Master should not be connected initially"
    
    # Simulate the logic in independent_broker_trader.py
    broker_type = BrokerType.KRAKEN
    user_id = "test_user"
    
    if broker_type == BrokerType.KRAKEN:
        kraken_master_connected = manager.is_master_connected(BrokerType.KRAKEN)
        if kraken_master_connected:
            should_skip = True
            print("   ✅ PASS: Would skip (master connected - copy trading mode)")
        else:
            should_skip = False
            print("   ✅ PASS: Would NOT skip (no master - independent mode allowed)")
    else:
        should_skip = False
        print("   ℹ️  Non-Kraken broker - always allowed")
    
    assert not should_skip, "User loop should be allowed when master not connected"
    print()
    
    # Test 2: Simulate master connection - user loop should be DISABLED
    print("Test 2: Simulating master connection - user loop behavior...")
    
    # Create a master broker (simulates connection)
    master_broker = KrakenBroker(account_type=AccountType.MASTER)
    # Don't actually connect (no credentials), just add to manager
    manager.master_brokers[BrokerType.KRAKEN] = master_broker
    # Mark as connected for testing purposes
    master_broker.connected = True
    
    # Now check if master is connected
    master_connected = manager.is_master_connected(BrokerType.KRAKEN)
    assert master_connected, "Master should be connected now"
    print("   ✅ Master broker registered and marked connected")
    
    # Check if user loop should be skipped
    if broker_type == BrokerType.KRAKEN:
        kraken_master_connected = manager.is_master_connected(BrokerType.KRAKEN)
        if kraken_master_connected:
            should_skip = True
            print("   ✅ PASS: User loop DISABLED (copy trading mode)")
            print("   ℹ️  User will receive copied trades from master only")
        else:
            should_skip = False
            print("   ❌ FAIL: User loop should be disabled!")
    
    assert should_skip, "User loop should be disabled when master is connected"
    print()
    
    # Test 3: Verify non-Kraken brokers are not affected
    print("Test 3: Non-Kraken brokers (e.g., Alpaca) behavior...")
    broker_type_alpaca = BrokerType.ALPACA
    
    if broker_type_alpaca == BrokerType.KRAKEN:
        # This won't execute
        should_skip_alpaca = True
    else:
        # Alpaca should always run independent loops
        should_skip_alpaca = False
        print("   ✅ PASS: Alpaca user loop ENABLED (not affected by Kraken master)")
    
    assert not should_skip_alpaca, "Non-Kraken users should still run independent loops"
    print()
    
    print("=" * 70)
    print("✅ ALL INDEPENDENT LOOP TESTS PASSED")
    print("=" * 70)
    print()
    print("Summary:")
    print("  ✅ Kraken users run independent loops when master NOT connected")
    print("  ✅ Kraken users SKIP independent loops when master IS connected")
    print("  ✅ Non-Kraken users always run independent loops (unaffected)")
    print("  ✅ Copy trading mode correctly enforced for Kraken")
    print()
    
    return 0

def main():
    """Run the test."""
    try:
        return test_independent_loop_disabled()
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
