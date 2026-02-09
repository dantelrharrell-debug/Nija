#!/usr/bin/env python3
"""
Deployment Verification Script
===============================

Verifies that the get_all_brokers() method fix has been deployed correctly.

This script should be run after deploying the fix to ensure the AttributeError is resolved.

Expected behavior:
- BrokerManager should have get_all_brokers() method
- Method should return a dictionary
- continuous_exit_enforcer should be able to call it without errors
"""

import sys
import os

# Add bot directory to path
bot_dir = os.path.join(os.path.dirname(__file__), 'bot')
sys.path.insert(0, bot_dir)

def main():
    print("=" * 80)
    print("  DEPLOYMENT VERIFICATION: get_all_brokers() Fix")
    print("=" * 80)
    print()
    
    # Test 1: Import broker_manager
    print("Test 1: Importing broker_manager...")
    try:
        from broker_manager import get_broker_manager, BrokerManager
        print("  ✅ Successfully imported broker_manager")
    except Exception as e:
        print(f"  ❌ FAILED to import broker_manager: {e}")
        return False
    
    # Test 2: Get broker manager instance
    print("\nTest 2: Getting broker manager instance...")
    try:
        broker_manager = get_broker_manager()
        print(f"  ✅ Got broker manager: {type(broker_manager).__name__}")
    except Exception as e:
        print(f"  ❌ FAILED to get broker manager: {e}")
        return False
    
    # Test 3: Check for get_all_brokers method
    print("\nTest 3: Checking for get_all_brokers() method...")
    if not hasattr(broker_manager, 'get_all_brokers'):
        print("  ❌ CRITICAL: BrokerManager does NOT have get_all_brokers() method!")
        print("  ⚠️  The fix has NOT been deployed yet.")
        print("\n  ACTION REQUIRED:")
        print("  1. Ensure broker_manager.py has been updated with the get_all_brokers() method")
        print("  2. Restart the NIJA bot application")
        print("  3. Re-run this verification script")
        return False
    else:
        print("  ✅ BrokerManager HAS get_all_brokers() method")
    
    # Test 4: Call the method
    print("\nTest 4: Calling get_all_brokers()...")
    try:
        brokers = broker_manager.get_all_brokers()
        print(f"  ✅ Successfully called get_all_brokers()")
        print(f"  ✅ Returned type: {type(brokers).__name__}")
        print(f"  ✅ Broker count: {len(brokers)}")
    except AttributeError as e:
        print(f"  ❌ FAILED with AttributeError: {e}")
        print("  ⚠️  The method exists but cannot be called - check implementation")
        return False
    except Exception as e:
        print(f"  ❌ FAILED with unexpected error: {e}")
        return False
    
    # Test 5: Verify it returns a dictionary
    print("\nTest 5: Verifying return type...")
    if not isinstance(brokers, dict):
        print(f"  ❌ FAILED: Expected dict, got {type(brokers).__name__}")
        return False
    else:
        print("  ✅ Returns a dictionary as expected")
    
    # Test 6: Import continuous_exit_enforcer
    print("\nTest 6: Importing continuous_exit_enforcer...")
    try:
        from continuous_exit_enforcer import ContinuousExitEnforcer
        print("  ✅ Successfully imported continuous_exit_enforcer")
    except Exception as e:
        print(f"  ❌ FAILED to import continuous_exit_enforcer: {e}")
        return False
    
    # Test 7: Simulate the exact error scenario
    print("\nTest 7: Simulating the production error scenario...")
    try:
        enforcer = ContinuousExitEnforcer(check_interval=60, max_positions=8)
        
        # Call the internal method that was failing
        enforcer._check_and_enforce_positions()
        
        print("  ✅ _check_and_enforce_positions() executed without AttributeError")
    except AttributeError as e:
        print(f"  ❌ STILL GETTING AttributeError: {e}")
        print("  ⚠️  The deployment is NOT complete")
        return False
    except Exception as e:
        # Other exceptions are OK (e.g., no brokers connected)
        print(f"  ✅ No AttributeError (other errors are expected: {type(e).__name__})")
    
    # All tests passed
    print()
    print("=" * 80)
    print("  ✅ DEPLOYMENT VERIFICATION SUCCESSFUL")
    print("=" * 80)
    print()
    print("The get_all_brokers() fix has been deployed correctly.")
    print("The AttributeError should no longer occur in production.")
    print()
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
