#!/usr/bin/env python3
"""
Quick diagnostic to see exactly what's failing
"""

import os
import sys
from dotenv import load_dotenv

print("="*80)
print("DIAGNOSTIC CHECK")
print("="*80)

# Check environment loading
print("\n1. Loading .env file...")
load_dotenv()
print("   ✅ .env loaded")

# Check credentials
print("\n2. Checking credentials...")
api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

if api_key:
    print(f"   ✅ COINBASE_API_KEY found ({len(api_key)} chars)")
else:
    print("   ❌ COINBASE_API_KEY missing")
    sys.exit(1)

if api_secret:
    print(f"   ✅ COINBASE_API_SECRET found ({len(api_secret)} chars)")
    if "BEGIN EC PRIVATE KEY" in api_secret:
        print("   ✅ PEM format detected")
else:
    print("   ❌ COINBASE_API_SECRET missing")
    sys.exit(1)

# Check Python path
print("\n3. Checking Python path...")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
print(f"   ✅ Added bot directory to path")

# Try importing broker
print("\n4. Importing CoinbaseBroker...")
try:
    from broker_manager import CoinbaseBroker
    print("   ✅ Import successful")
except ImportError as e:
    print(f"   ❌ Import failed: {e}")
    sys.exit(1)

# Try creating broker instance
print("\n5. Creating broker instance...")
try:
    broker = CoinbaseBroker()
    print("   ✅ Instance created")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

# Try connecting
print("\n6. Connecting to Coinbase...")
try:
    if broker.connect():
        print("   ✅ Connected successfully!")
    else:
        print("   ❌ Connection returned False")
        sys.exit(1)
except Exception as e:
    print(f"   ❌ Connection failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Try getting accounts
print("\n7. Testing API - Getting accounts...")
try:
    accounts = broker.client.get_accounts()
    num_accounts = len(accounts.get('accounts', []))
    print(f"   ✅ Got {num_accounts} accounts")
except Exception as e:
    print(f"   ❌ API call failed: {e}")
    sys.exit(1)

# Count crypto holdings
print("\n8. Counting crypto holdings...")
try:
    crypto_count = 0
    for account in accounts['accounts']:
        currency = account.get('currency')
        available_balance = account.get('available_balance', {})
        value = float(available_balance.get('value', 0))
        
        if currency and currency not in ['USD', 'USDC'] and value > 0:
            crypto_count += 1
            print(f"   - {currency}: {value}")
    
    print(f"\n   ✅ Found {crypto_count} crypto positions")
    
    if crypto_count == 0:
        print("\n   ⚠️  WARNING: No crypto holdings found!")
        print("   This means either:")
        print("   1. All positions were already sold")
        print("   2. Holdings are in a different portfolio/account")
        print("   3. API credentials are for wrong account")
except Exception as e:
    print(f"   ❌ Failed to count holdings: {e}")
    sys.exit(1)

print("\n" + "="*80)
print("✅ ALL CHECKS PASSED")
print("="*80)
print("\nThe emergency sync script should work.")
print("If it's still failing, the issue is likely:")
print("  - Position file permissions")
print("  - Or the actual sync/save logic")
print("\n")
