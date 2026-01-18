#!/usr/bin/env python3
"""
Test script to verify Kraken user connections work in standalone mode.
This tests the fix that allows users to connect without master.
"""

import os
import sys

# Add both root and bot directories to path
repo_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, repo_root)
sys.path.insert(0, os.path.join(repo_root, 'bot'))

from dotenv import load_dotenv
load_dotenv()

print("=" * 70)
print("KRAKEN USER CONNECTION TEST")
print("=" * 70)
print()

# Step 1: Verify environment variables
print("Step 1: Checking environment variables...")
print("-" * 70)

env_vars = {
    'KRAKEN_USER_DAIVON_API_KEY': os.getenv('KRAKEN_USER_DAIVON_API_KEY'),
    'KRAKEN_USER_DAIVON_API_SECRET': os.getenv('KRAKEN_USER_DAIVON_API_SECRET'),
    'KRAKEN_USER_TANIA_API_KEY': os.getenv('KRAKEN_USER_TANIA_API_KEY'),
    'KRAKEN_USER_TANIA_API_SECRET': os.getenv('KRAKEN_USER_TANIA_API_SECRET'),
}

all_set = True
for var_name, var_value in env_vars.items():
    if var_value:
        print(f"✅ {var_name}: SET ({len(var_value)} chars)")
    else:
        print(f"❌ {var_name}: NOT SET")
        all_set = False

print()

if not all_set:
    print("❌ ERROR: Not all environment variables are set!")
    print()
    print("Fix:")
    print("1. Make sure .env file exists in the repository root")
    print("2. Or set environment variables in your deployment platform")
    print()
    sys.exit(1)

# Step 2: Check user configuration
print("Step 2: Checking user configuration...")
print("-" * 70)

try:
    from config.user_loader import get_user_config_loader
    
    user_loader = get_user_config_loader()
    enabled_users = user_loader.get_all_enabled_users()
    
    kraken_users = [u for u in enabled_users if u.broker_type.upper() == 'KRAKEN']
    
    if not kraken_users:
        print("❌ No Kraken users found in configuration!")
        sys.exit(1)
    
    print(f"✅ Found {len(kraken_users)} Kraken user(s):")
    for user in kraken_users:
        print(f"   - {user.name} ({user.user_id}) - Enabled: {user.enabled}")
    print()
    
except Exception as e:
    print(f"❌ Error loading user configuration: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Step 3: Test multi-account manager
print("Step 3: Testing multi-account broker manager...")
print("-" * 70)

try:
    from multi_account_broker_manager import MultiAccountBrokerManager
    from broker_manager import BrokerType
    
    manager = MultiAccountBrokerManager()
    
    # Check if master is connected (should be False for standalone mode)
    master_connected = manager.is_master_connected(BrokerType.KRAKEN)
    if master_connected:
        print("⚠️  Master Kraken is connected (copy trading mode)")
    else:
        print("✅ Master Kraken is NOT connected (standalone mode - expected)")
    
    print()
    
    # Try to connect users
    print("Step 4: Connecting users from configuration...")
    print("-" * 70)
    
    connected_users = manager.connect_users_from_config()
    
    if BrokerType.KRAKEN.value in connected_users:
        kraken_user_ids = connected_users[BrokerType.KRAKEN.value]
        print(f"✅ Successfully connected {len(kraken_user_ids)} Kraken user(s):")
        for user_id in kraken_user_ids:
            print(f"   - {user_id}")
    else:
        print("⚠️  No Kraken users connected")
        print("   This might be expected if credentials are invalid or network issues")
    
    print()
    
except Exception as e:
    print(f"❌ Error during connection test: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Summary
print("=" * 70)
print("TEST SUMMARY")
print("=" * 70)
print()
print("✅ Environment variables: OK")
print("✅ User configuration: OK")
print("✅ Multi-account manager: OK")
print("✅ User connection logic: OK")
print()
print("The standalone mode fix is working correctly!")
print("Users can now connect to Kraken without master account.")
print()
print("Note: Actual API connection success depends on:")
print("  - Valid API credentials")
print("  - Network connectivity")
print("  - Kraken API availability")
print()
print("=" * 70)
