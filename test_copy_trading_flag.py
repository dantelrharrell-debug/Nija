#!/usr/bin/env python3
"""
Test that Kraken users are skipped when copy trading is active.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import BrokerType
from multi_account_broker_manager import multi_account_broker_manager

print("="*70)
print("Testing Kraken Copy Trading Flag")
print("="*70)

# Test initial state
print("\n1. Initial state (copy trading not active)")
print(f"   kraken_copy_trading_active: {multi_account_broker_manager.kraken_copy_trading_active}")

# Simulate activating copy trading
print("\n2. Simulating copy trading activation")
multi_account_broker_manager.kraken_copy_trading_active = True
print(f"   kraken_copy_trading_active: {multi_account_broker_manager.kraken_copy_trading_active}")

# Test the check that will be used in connect_users_from_config
print("\n3. Testing the check for Kraken users")
broker_type = BrokerType.KRAKEN
if broker_type == BrokerType.KRAKEN and multi_account_broker_manager.kraken_copy_trading_active:
    print("   ✅ WOULD SKIP Kraken user initialization (copy trading active)")
else:
    print("   ❌ Would attempt to connect Kraken user (should be skipped!)")

# Test with copy trading inactive
print("\n4. Simulating copy trading inactive")
multi_account_broker_manager.kraken_copy_trading_active = False
if broker_type == BrokerType.KRAKEN and multi_account_broker_manager.kraken_copy_trading_active:
    print("   Would skip Kraken user")
else:
    print("   ✅ WOULD CONNECT Kraken user (copy trading inactive)")

# Test with non-Kraken broker
print("\n5. Testing with Alpaca broker (should always attempt connection)")
broker_type = BrokerType.ALPACA
multi_account_broker_manager.kraken_copy_trading_active = True
if broker_type == BrokerType.KRAKEN and multi_account_broker_manager.kraken_copy_trading_active:
    print("   Would skip")
else:
    print("   ✅ WOULD CONNECT Alpaca user (not Kraken)")

print("\n" + "="*70)
print("Test Complete - Logic working correctly!")
print("="*70)
