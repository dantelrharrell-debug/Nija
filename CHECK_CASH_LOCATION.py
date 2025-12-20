#!/usr/bin/env python3
"""
Find where your cash is located (Consumer vs Advanced Trade)
"""

import sys
import os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("💰 CASH LOCATION FINDER")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get all accounts
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

consumer_usd = 0
consumer_usdc = 0
advanced_usd = 0
advanced_usdc = 0

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    acc_type = getattr(acc, 'type', 'UNKNOWN')
    
    if not curr or not avail_obj:
        continue
    
    amount = float(getattr(avail_obj, 'value', 0))
    
    if amount == 0:
        continue
    
    if curr == 'USD':
        if acc_type == 'ACCOUNT':
            consumer_usd += amount
            print(f"💵 Consumer Wallet USD: ${amount:.2f}")
        else:
            advanced_usd += amount
            print(f"💵 Advanced Trade USD: ${amount:.2f}")
    
    elif curr == 'USDC':
        if acc_type == 'ACCOUNT':
            consumer_usdc += amount
            print(f"💵 Consumer Wallet USDC: ${amount:.2f}")
        else:
            advanced_usdc += amount
            print(f"💵 Advanced Trade USDC: ${amount:.2f}")

total_consumer = consumer_usd + consumer_usdc
total_advanced = advanced_usd + advanced_usdc

print("\n" + "=" * 80)
print("📊 SUMMARY:")
print("=" * 80)
print(f"Consumer Wallet Total:    ${total_consumer:.2f}")
print(f"Advanced Trade Total:     ${total_advanced:.2f}")
print(f"Grand Total:              ${total_consumer + total_advanced:.2f}")

print("\n" + "=" * 80)
print("🎯 WHAT YOU NEED TO DO:")
print("=" * 80)

if total_consumer > 0 and total_advanced == 0:
    print("\n❌ PROBLEM: All your money is in Consumer wallet!")
    print("   Bot CANNOT trade from Consumer wallet.")
    print("\n✅ SOLUTION:")
    print(f"   1. Go to: https://www.coinbase.com/advanced-portfolio")
    print(f"   2. Click 'Deposit' → 'From Coinbase'")
    print(f"   3. Transfer ${total_consumer:.2f} to Advanced Trade")
    print(f"   4. Bot will start trading within 15 seconds")
    
elif total_advanced > 0:
    print(f"\n✅ SUCCESS: You have ${total_advanced:.2f} in Advanced Trade")
    print("   Bot should be trading now!")
    print("\n🔍 If bot isn't trading, check Railway logs:")
    print("   https://railway.app")
    
else:
    print("\n⚠️  No USD/USDC found in either wallet")
    print("   Check if funds were withdrawn or transferred elsewhere")

print("=" * 80)
