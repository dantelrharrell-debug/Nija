#!/usr/bin/env python3
"""Test Coinbase API connection"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

print("Checking credentials...")
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

if not api_key:
    print("❌ COINBASE_API_KEY not found in .env")
    sys.exit(1)

if not api_secret:
    print("❌ COINBASE_API_SECRET not found in .env")
    sys.exit(1)

print("✅ Credentials loaded")

print("\nTesting Coinbase import...")
try:
    from coinbase.rest import RESTClient
    print("✅ Coinbase library imported")
except ImportError as e:
    print(f"❌ Failed to import Coinbase: {e}")
    print("\n📦 Installing required packages...")
    os.system("pip install coinbase-advanced-py")
    sys.exit(1)

print("\nInitializing Coinbase client...")
try:
    client = RESTClient(
        api_key=api_key,
        api_secret=api_secret
    )
    print("✅ Client initialized")
except Exception as e:
    print(f"❌ Failed to initialize client: {e}")
    sys.exit(1)

print("\nFetching accounts...")
try:
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    print(f"✅ Retrieved {len(accounts)} accounts")
    
    # Show balances
    for acc in accounts:
        curr = getattr(acc, 'currency', None)
        avail = getattr(acc, 'available_balance', None)
        if curr and avail:
            bal = float(getattr(avail, 'value', '0'))
            if bal > 0:
                print(f"   {curr}: {bal}")
                
except Exception as e:
    print(f"❌ Failed to fetch accounts: {e}")
    print(f"\nError details: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✅ All checks passed!")
