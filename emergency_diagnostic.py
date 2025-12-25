#!/usr/bin/env python3
"""
Emergency Diagnostic - Find out why balance shows $0.00
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

print("\n" + "="*80)
print("🚨 EMERGENCY DIAGNOSTIC - WHY $0.00?")
print("="*80)

# Check 1: Credentials exist?
print("\n1️⃣  CHECKING CREDENTIALS...")
print("-" * 80)

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

if not api_key or not api_secret:
    print("❌ MISSING CREDENTIALS!")
    print("   Check your .env file")
    sys.exit(1)

print(f"✅ API Key found: {api_key[:10]}...")
print(f"✅ API Secret found: {api_secret[:10]}...")

# Check 2: Can we connect?
print("\n2️⃣  TESTING CONNECTION...")
print("-" * 80)

try:
    from coinbase.rest import RESTClient
    
    client = RESTClient(
        api_key=api_key,
        api_secret=api_secret
    )
    
    print("✅ RESTClient initialized")
    
    # Try to get accounts
    print("\n3️⃣  FETCHING ACCOUNTS...")
    print("-" * 80)
    
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    print(f"✅ Got {len(accounts)} accounts")
    
    # Check 3: Show ALL accounts with balances
    print("\n4️⃣  ACCOUNT DETAILS:")
    print("-" * 80)
    
    has_balance = False
    
    for i, account in enumerate(accounts, 1):
        currency = getattr(account, 'currency', 'UNKNOWN')
        available_obj = getattr(account, 'available_balance', None)
        account_uuid = getattr(account, 'uuid', 'no-uuid')
        account_name = getattr(account, 'name', 'Unknown')
        account_type = getattr(account, 'type', 'UNKNOWN')
        
        if available_obj:
            available = float(getattr(available_obj, 'value', '0'))
            
            if available > 0:
                has_balance = True
                print(f"\n💰 Account #{i}:")
                print(f"   Currency: {currency}")
                print(f"   Balance: {available:.8f}")
                print(f"   Type: {account_type}")
                print(f"   Name: {account_name}")
                print(f"   UUID: {account_uuid}")
    
    if not has_balance:
        print("\n⚠️  NO ACCOUNTS WITH BALANCES FOUND!")
        print("\n📋 All accounts checked:")
        for account in accounts:
            currency = getattr(account, 'currency', 'UNKNOWN')
            account_type = getattr(account, 'type', 'UNKNOWN')
            available_obj = getattr(account, 'available_balance', None)
            available = float(getattr(available_obj, 'value', '0')) if available_obj else 0
            print(f"   • {currency} ({account_type}): {available:.8f}")
    
    # Check 5: Get portfolios
    print("\n5️⃣  CHECKING PORTFOLIOS...")
    print("-" * 80)
    
    try:
        portfolios_resp = client.get_portfolios()
        portfolios = getattr(portfolios_resp, 'portfolios', [])
        print(f"✅ Found {len(portfolios)} portfolios")
        
        for portfolio in portfolios:
            name = getattr(portfolio, 'name', 'Unknown')
            uuid = getattr(portfolio, 'uuid', 'no-uuid')
            portfolio_type = getattr(portfolio, 'type', 'UNKNOWN')
            print(f"   • {name} (Type: {portfolio_type}, UUID: {uuid})")
    except Exception as e:
        print(f"⚠️  Portfolio check failed: {e}")
    
    # Check 6: Try listing products
    print("\n6️⃣  CHECKING MARKET ACCESS...")
    print("-" * 80)
    
    try:
        product = client.get_product("BTC-USD")
        price = float(getattr(product, 'price', 0))
        print(f"✅ Can access market data")
        print(f"   BTC-USD price: ${price:,.2f}")
    except Exception as e:
        print(f"❌ Market access failed: {e}")
    
    print("\n" + "="*80)
    print("🎯 DIAGNOSIS:")
    print("="*80)
    
    if has_balance:
        print("\n✅ API IS WORKING - You have balances")
        print("   Issue: Script might be filtering them out incorrectly")
    else:
        print("\n⚠️  TWO POSSIBILITIES:")
        print("\n   A) API Permissions Issue:")
        print("      Your API key cannot see account balances")
        print("      Solution: Check API key permissions on Coinbase")
        print("      Go to: https://www.coinbase.com/settings/api")
        print("\n   B) Account Actually Empty:")
        print("      All funds have been moved/sold")
        print("      Solution: Check manually on Coinbase website")
        print("      Go to: https://www.coinbase.com/home")
    
    print("\n" + "="*80)
    print("🔧 NEXT STEPS:")
    print("="*80)
    print("\n1. Check Coinbase website manually:")
    print("   https://www.coinbase.com/home")
    print("\n2. Verify what balances you actually have")
    print("\n3. If you have funds but API shows $0.00:")
    print("   → API key needs proper permissions")
    print("   → Regenerate API key with 'View' + 'Trade' permissions")
    print("\n4. If account is actually empty:")
    print("   → Deposit funds to start trading")
    print("="*80 + "\n")
    
except Exception as e:
    print(f"\n❌ CONNECTION FAILED: {e}")
    print("\nPossible causes:")
    print("1. Invalid API credentials")
    print("2. Network connectivity issue")
    print("3. Coinbase API is down")
    print("\nCheck: https://status.coinbase.com/")
