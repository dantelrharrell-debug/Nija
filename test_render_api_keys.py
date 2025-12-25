#!/usr/bin/env python3
"""
Test if Render's API credentials can connect to Coinbase account.
This will show EXACTLY what the API sees.
"""
import os
import sys

# Check if credentials exist
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

print("=" * 70)
print("🔑 RENDER API CREDENTIALS TEST")
print("=" * 70)

if not api_key:
    print("❌ COINBASE_API_KEY not found in environment")
    print("   Set it in Render dashboard → Environment variables")
    sys.exit(1)

if not api_secret:
    print("❌ COINBASE_API_SECRET not found in environment")
    print("   Set it in Render dashboard → Environment variables")
    sys.exit(1)

# Show credential format (not full values for security)
print(f"✅ COINBASE_API_KEY: {api_key[:30]}... ({len(api_key)} chars)")
print(f"✅ COINBASE_API_SECRET: {'[PEM CONTENT]' if '-----BEGIN' in api_secret else '[NOT PEM FORMAT!]'} ({len(api_secret)} chars)")
print()

# Verify format
if not api_key.startswith("organizations/"):
    print("❌ API KEY FORMAT ERROR!")
    print(f"   Your key: {api_key[:50]}")
    print("   Expected: organizations/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/apiKeys/...")
    print()
    print("🔧 FIX: Get correct key from Coinbase Cloud API settings")
    print("   https://cloud.coinbase.com/access/api")
    sys.exit(1)

if "-----BEGIN EC PRIVATE KEY-----" not in api_secret:
    print("❌ API SECRET FORMAT ERROR!")
    print("   Your secret doesn't contain PEM header")
    print("   Expected: -----BEGIN EC PRIVATE KEY-----")
    print()
    print("🔧 FIX: Copy the FULL PEM file content including header/footer")
    sys.exit(1)

print("✅ Credential format looks correct")
print()

# Try to connect
try:
    from coinbase.rest import RESTClient
    
    print("🔗 Attempting to connect to Coinbase API...")
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    print("📡 Calling list_accounts()...")
    accounts_resp = client.list_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    print("=" * 70)
    print(f"📊 API RESPONSE: {len(accounts)} account(s) found")
    print("=" * 70)
    
    if len(accounts) == 0:
        print()
        print("❌ ZERO ACCOUNTS RETURNED!")
        print()
        print("🔍 ROOT CAUSE:")
        print("   Your API credentials are connecting successfully,")
        print("   but they belong to a DIFFERENT Coinbase organization/account")
        print()
        print("   The credentials in Render are NOT for:")
        print("   📧 Dantelrharrell@gmail.com")
        print()
        print("🔧 SOLUTION:")
        print("   1. Log into Coinbase as: Dantelrharrell@gmail.com")
        print("   2. Go to: https://cloud.coinbase.com/access/api")
        print("   3. Create NEW API keys (or verify existing ones)")
        print("   4. Copy the EXACT keys shown")
        print("   5. Update Render environment variables with NEW keys")
        print("   6. Manual deploy on Render")
        print()
        print("⚠️  CRITICAL: You may have multiple Coinbase accounts!")
        print("   Make sure you're logged into the account with $57.54")
        print()
    else:
        print()
        print("✅ ACCOUNTS FOUND! Here's what the API sees:")
        print()
        
        total_usd = 0
        total_usdc = 0
        
        for i, account in enumerate(accounts, 1):
            currency = getattr(account, 'currency', 'UNKNOWN')
            available_obj = getattr(account, 'available_balance', None)
            available = float(getattr(available_obj, 'value', 0) or 0)
            account_type = getattr(account, 'type', 'UNKNOWN')
            account_name = getattr(account, 'name', 'UNKNOWN')
            account_uuid = getattr(account, 'uuid', 'no-uuid')
            
            print(f"   {i}. {currency:6} | ${available:>10.2f} | {account_name:20} | {account_type:12} | {account_uuid[:8]}...")
            
            if currency == "USD":
                total_usd += available
            elif currency == "USDC":
                total_usdc += available
        
        print()
        print("=" * 70)
        print(f"💰 TRADING BALANCE: ${total_usd + total_usdc:.2f}")
        print(f"   USD:  ${total_usd:.2f}")
        print(f"   USDC: ${total_usdc:.2f}")
        print("=" * 70)
        print()
        
        if total_usd + total_usdc > 0:
            print("✅ SUCCESS! API can see your funds.")
            print("   Bot should be trading with this balance.")
        else:
            print("⚠️  API connected, but NO USD/USDC found in Advanced Trade")
            print()
            print("   Funds may be in:")
            print("   • Consumer wallet (not accessible via API)")
            print("   • Different portfolio")
            print()
            print("🔧 Transfer funds to Advanced Trade:")
            print("   https://www.coinbase.com/advanced-portfolio")
    
except Exception as e:
    print()
    print("❌ API CONNECTION FAILED!")
    print(f"   Error: {e}")
    print()
    import traceback
    print("Full traceback:")
    print(traceback.format_exc())
    print()
    print("🔧 Possible causes:")
    print("   • API key/secret mismatch")
    print("   • Invalid PEM format in secret")
    print("   • Expired API credentials")
    print("   • Network connectivity issue")
    sys.exit(1)

print()
print("=" * 70)
print("Test complete!")
print("=" * 70)
