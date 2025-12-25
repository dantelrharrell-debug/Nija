#!/usr/bin/env python3
"""
RAW DUMP - Show EVERYTHING from Coinbase API
"""

import sys
import os
import json
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("🔍 RAW COINBASE API DUMP - SHOWING EVERYTHING")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get ALL accounts
print("📋 Fetching ALL accounts (no filters)...\n")

try:
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    print(f"✅ Retrieved {len(accounts)} account(s)\n")
    print("=" * 80)
    
    for i, acc in enumerate(accounts, 1):
        print(f"\n🏦 ACCOUNT #{i}")
        print("-" * 80)
        
        # Extract all attributes
        curr = getattr(acc, 'currency', 'N/A')
        acc_type = getattr(acc, 'type', 'N/A')
        acc_name = getattr(acc, 'name', 'N/A')
        acc_uuid = getattr(acc, 'uuid', 'N/A')
        
        avail_obj = getattr(acc, 'available_balance', None)
        if avail_obj:
            avail_value = getattr(avail_obj, 'value', '0')
            avail_curr = getattr(avail_obj, 'currency', 'N/A')
        else:
            avail_value = '0'
            avail_curr = 'N/A'
        
        hold_obj = getattr(acc, 'hold', None)
        if hold_obj:
            hold_value = getattr(hold_obj, 'value', '0')
        else:
            hold_value = '0'
        
        print(f"Name:       {acc_name}")
        print(f"Currency:   {curr}")
        print(f"Type:       {acc_type}")
        print(f"UUID:       {acc_uuid}")
        print(f"Available:  {avail_value} {avail_curr}")
        print(f"On Hold:    {hold_value}")
        
        # Show if has balance
        if float(avail_value) > 0:
            print(f"\n💰 HAS BALANCE: {avail_value} {curr}")
        
        if float(hold_value) > 0:
            print(f"⏸️  ON HOLD: {hold_value} {curr}")
        
        print("-" * 80)
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 ACCOUNTS WITH BALANCES")
    print("=" * 80)
    
    has_balance = []
    for acc in accounts:
        curr = getattr(acc, 'currency', 'N/A')
        avail_obj = getattr(acc, 'available_balance', None)
        
        if avail_obj:
            avail_value = float(getattr(avail_obj, 'value', 0))
            if avail_value > 0:
                acc_type = getattr(acc, 'type', 'N/A')
                has_balance.append(f"{curr}: {avail_value} ({acc_type})")
    
    if has_balance:
        for item in has_balance:
            print(f"  • {item}")
    else:
        print("\n❌ NO ACCOUNTS WITH BALANCES FOUND")
        print("\n   This is unusual. Possible causes:")
        print("   1. API permissions don't allow viewing balances")
        print("   2. Funds withdrawn/transferred out")
        print("   3. API credentials are for wrong account")
        print("\n   Check Coinbase web interface:")
        print("   https://www.coinbase.com")
    
    print("=" * 80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
