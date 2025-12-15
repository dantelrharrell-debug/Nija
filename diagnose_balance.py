#!/usr/bin/env python3
"""
Diagnose Coinbase Balance Detection Issue
Checks all portfolios, all accounts, and raw API responses
"""

import os
import sys
from dotenv import load_dotenv
from coinbase.rest import RESTClient

# Load credentials
load_dotenv()
api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

if not api_key or not api_secret:
    print("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET")
    sys.exit(1)

# Normalize PEM newlines
if '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

print("=" * 80)
print("🔍 COINBASE BALANCE DIAGNOSTICS")
print("=" * 80)

try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    print("✅ Connected to Coinbase Advanced Trade API\n")
    
    # 1. Check default accounts list
    print("📋 DEFAULT ACCOUNTS (via get_accounts):")
    print("-" * 80)
    try:
        accounts_resp = client.get_accounts()
        accounts = getattr(accounts_resp, 'accounts', [])
        print(f"Total accounts: {len(accounts)}\n")
        
        if len(accounts) == 0:
            print("⚠️ WARNING: API returned ZERO accounts!")
            print("   This means either:")
            print("   1. Your API key doesn't have permission to view accounts")
            print("   2. All funds are in a non-default portfolio")
            print("   3. The account is empty\n")
        
        for i, account in enumerate(accounts, 1):
            currency = getattr(account, 'currency', 'UNKNOWN')
            name = getattr(account, 'name', 'UNKNOWN')
            uuid = getattr(account, 'uuid', 'UNKNOWN')
            platform = getattr(account, 'platform', 'UNKNOWN')
            available = float(getattr(getattr(account, 'available_balance', None), 'value', 0) or 0)
            held = float(getattr(getattr(account, 'hold', None), 'value', 0) or 0)
            
            print(f"{i}. {currency}")
            print(f"   UUID:      {uuid}")
            print(f"   Name:      {name}")
            print(f"   Platform:  {platform}")
            print(f"   Available: {available:.8f}")
            print(f"   Held:      {held:.8f}")
            print()
            
    except Exception as e:
        print(f"❌ Error fetching accounts: {e}\n")
    
    # 2. Try list_accounts (alternative method)
    print("\n📋 ALTERNATE METHOD (via list_accounts if available):")
    print("-" * 80)
    try:
        if hasattr(client, 'list_accounts'):
            list_resp = client.list_accounts()
            list_accounts = getattr(list_resp, 'accounts', [])
            print(f"Total accounts: {len(list_accounts)}")
            for account in list_accounts:
                currency = getattr(account, 'currency', 'UNKNOWN')
                available = float(getattr(getattr(account, 'available_balance', None), 'value', 0) or 0)
                if available > 0:
                    print(f"   {currency}: ${available:.2f}")
        else:
            print("   list_accounts method not available")
    except Exception as e:
        print(f"   Error: {e}")
    
    # 3. Check portfolios (if available)
    print("\n\n📁 PORTFOLIOS:")
    print("-" * 80)
    try:
        if hasattr(client, 'get_portfolios'):
            portfolios_resp = client.get_portfolios()
            portfolios = getattr(portfolios_resp, 'portfolios', [])
            print(f"Total portfolios: {len(portfolios)}\n")
            
            for i, portfolio in enumerate(portfolios, 1):
                name = getattr(portfolio, 'name', 'UNKNOWN')
                uuid = getattr(portfolio, 'uuid', 'UNKNOWN')
                portfolio_type = getattr(portfolio, 'type', 'UNKNOWN')
                print(f"{i}. {name}")
                print(f"   UUID: {uuid}")
                print(f"   Type: {portfolio_type}")
                print()
        else:
            print("   get_portfolios method not available in SDK")
            print("   (This is normal for coinbase-advanced-py)")
    except Exception as e:
        print(f"   Error: {e}")
    
    # 4. Check if we can list products (to verify API key permissions)
    print("\n\n🔐 API KEY PERMISSIONS CHECK:")
    print("-" * 80)
    try:
        products = client.get_products(limit=5)
        product_list = getattr(products, 'products', [])
        print(f"✅ Can read market data: {len(product_list)} products accessible")
        print(f"   Sample: {[p.product_id for p in product_list[:3]]}")
    except Exception as e:
        print(f"❌ Cannot read market data: {e}")
    
    print("\n" + "=" * 80)
    print("💡 TROUBLESHOOTING TIPS:")
    print("=" * 80)
    print("1. If you see 0 accounts, your funds may be in Coinbase.com (not Advanced Trade)")
    print("   → Go to https://www.coinbase.com/settings/advanced-trade")
    print("   → Click 'Deposit' and move USD/USDC from Coinbase to Advanced Trade")
    print("")
    print("2. If accounts show but balance is 0, verify you have USD or USDC")
    print("   → Some crypto balances don't count as trading balance")
    print("")
    print("3. If API errors occur, check your API key permissions:")
    print("   → Go to https://portal.cloud.coinbase.com/access/api")
    print("   → Verify 'View' and 'Trade' permissions are enabled")
    print("=" * 80)
    
except Exception as e:
    print(f"❌ Fatal error: {e}")
    import traceback
    traceback.print_exc()
