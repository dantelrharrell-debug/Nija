#!/usr/bin/env python3
"""Show ALL accounts the API can see - even $0 balances"""
import os
from dotenv import load_dotenv
load_dotenv()

from coinbase.rest import RESTClient

print("="*80)
print("SHOWING ALL COINBASE ACCOUNTS (including $0 balances)")
print("="*80)

try:
    client = RESTClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET")
    )
    
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    print(f"\n✅ Found {len(accounts)} total accounts\n")
    
    # Group by currency
    by_currency = {}
    for account in accounts:
        currency = getattr(account, 'currency', 'UNKNOWN')
        if currency not in by_currency:
            by_currency[currency] = []
        by_currency[currency].append(account)
    
    print(f"📊 Currencies: {', '.join(sorted(by_currency.keys()))}\n")
    
    # Show USD and USDC accounts in detail
    for curr in ['USD', 'USDC']:
        if curr in by_currency:
            print(f"\n{curr} Accounts ({len(by_currency[curr])}):")
            print("-" * 80)
            for acc in by_currency[curr]:
                name = getattr(acc, 'name', 'Unknown')
                acc_type = getattr(acc, 'type', 'Unknown')
                uuid = getattr(acc, 'uuid', 'no-uuid')
                avail_obj = getattr(acc, 'available_balance', None)
                balance = float(getattr(avail_obj, 'value', '0')) if avail_obj else 0
                
                print(f"  • {name:30} | Type: {acc_type:15} | Balance: ${balance:>10.2f}")
                print(f"    UUID: {uuid}")
    
    print("\n" + "="*80)
    print("🔍 DIAGNOSIS:")
    print("="*80)
    print("\nIf you see $0.00 for all USD accounts, it means:")
    print("1. This API key is for a DIFFERENT Coinbase account")
    print("2. OR funds are in Consumer wallet (not accessible via Advanced Trade API)")
    print("3. OR you need to log into Coinbase web and transfer funds to Advanced Trade")
    print("\n🔗 Check here: https://www.coinbase.com/advanced-portfolio")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
