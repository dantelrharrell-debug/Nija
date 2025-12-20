#!/usr/bin/env python3
"""
Test API key permissions and capabilities
"""
import os
import sys
from pathlib import Path
from coinbase.rest import RESTClient

# Load .env
dotenv_path = Path('.env')
if dotenv_path.exists():
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                if not os.getenv(key.strip()):
                    os.environ[key.strip()] = val.strip()

api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

if not api_key or not api_secret:
    print("❌ Missing credentials")
    sys.exit(1)

if '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

print("\n" + "="*80)
print("🔍 TESTING API KEY CAPABILITIES")
print("="*80)

print(f"\n🔑 API Key: {api_key[:50]}...")

try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    # Test 1: Can we list portfolios?
    print("\n1️⃣ Testing: Get Portfolios...")
    try:
        portfolios_resp = client.get_portfolios()
        portfolios = getattr(portfolios_resp, 'portfolios', [])
        print(f"   ✅ SUCCESS - Found {len(portfolios)} portfolios")
        for p in portfolios:
            print(f"      📁 {p.name} (UUID: {p.uuid})")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        print(f"   → Missing: Portfolio read permission")
    
    # Test 2: Can we list accounts (without portfolio filter)?
    print("\n2️⃣ Testing: Get Accounts (no portfolio filter)...")
    try:
        accounts_resp = client.get_accounts()
        accounts = getattr(accounts_resp, 'accounts', [])
        print(f"   ✅ SUCCESS - Found {len(accounts)} accounts")
        
        for acc in accounts[:5]:  # Show first 5
            currency = getattr(acc, 'currency', 'N/A')
            balance = getattr(acc, 'available_balance', None)
            if balance:
                amount = float(getattr(balance, 'value', 0))
                if amount > 0.001:
                    print(f"      💵 {currency}: {amount}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
    
    # Test 3: Can we get accounts for specific portfolio?
    print("\n3️⃣ Testing: Get Accounts by Portfolio UUID...")
    if portfolios:
        for portfolio in portfolios:
            pf_name = portfolio.name
            pf_uuid = portfolio.uuid
            
            print(f"\n   Testing portfolio: {pf_name}")
            try:
                acc_resp = client.get_accounts(portfolio_uuid=pf_uuid)
                accs = getattr(acc_resp, 'accounts', [])
                print(f"      ✅ SUCCESS - Found {len(accs)} accounts in {pf_name}")
                
                found_balance = False
                for acc in accs:
                    currency = getattr(acc, 'currency', 'N/A')
                    bal_obj = getattr(acc, 'available_balance', None)
                    if bal_obj:
                        amount = float(getattr(bal_obj, 'value', 0))
                        if amount > 0.001:
                            found_balance = True
                            print(f"         💰 {currency}: {amount}")
                
                if not found_balance:
                    print(f"         (no balances)")
                    
            except Exception as e:
                print(f"      ❌ FAILED: {e}")
                print(f"      → Missing: Portfolio-specific access")
    
    # Test 4: Alternative - list_accounts method
    print("\n4️⃣ Testing: list_accounts() method...")
    try:
        if hasattr(client, 'list_accounts'):
            accounts_resp = client.list_accounts()
            accounts = getattr(accounts_resp, 'accounts', [])
            print(f"   ✅ SUCCESS - Found {len(accounts)} accounts")
            
            for acc in accounts:
                currency = getattr(acc, 'currency', 'N/A')
                bal_obj = getattr(acc, 'available_balance', None)
                if bal_obj:
                    amount = float(getattr(bal_obj, 'value', 0))
                    if amount > 0.001:
                        print(f"      💰 {currency}: {amount}")
        else:
            print(f"   ⚠️  Method not available")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
    
    print("\n" + "="*80)
    print("📊 DIAGNOSIS")
    print("="*80)
    
    print("\nIf you see $156.97 anywhere above:")
    print("   ✅ API key works! Update bot to use the working method")
    
    print("\nIf all tests passed but show $0.00:")
    print("   ⚠️  Possible causes:")
    print("   1. Funds are in a DIFFERENT Coinbase account")
    print("   2. API key is from different account than web UI")
    print("   3. Funds are in Coinbase Wallet (not Exchange)")
    print("   4. Delay in API sync (try again in a few minutes)")
    
    print("\nIf tests FAILED:")
    print("   ❌ API permissions are NOT correct")
    print("   → Need to recreate API key with proper scopes")
    
    print("\n" + "="*80 + "\n")

except Exception as e:
    print(f"\n❌ CRITICAL ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
