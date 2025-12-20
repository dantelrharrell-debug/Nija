#!/usr/bin/env python3
"""
SIMPLE ANSWER: Is NIJA selling? Yes or No?
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')

print("\n" + "="*80)
print("❓ IS NIJA SELLING? - SIMPLE ANSWER")
print("="*80 + "\n")

try:
    from coinbase.rest import RESTClient
    
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    
    # Check recent orders
    filled = client.list_orders(order_status='FILLED', limit=50)
    orders = getattr(filled, 'orders', [])
    
    sells = [o for o in orders if getattr(o, 'side', '') == 'SELL']
    buys = [o for o in orders if getattr(o, 'side', '') == 'BUY']
    
    print(f"Recent Trading Activity (Last 50 orders):")
    print(f"  BUY orders:  {len(buys)}")
    print(f"  SELL orders: {len(sells)}\n")
    
    if len(sells) > 0:
        print("✅ YES - NIJA IS SELLING!")
        print(f"\n   Latest sell:")
        latest = sells[0]
        product = getattr(latest, 'product_id', 'Unknown')
        value = getattr(latest, 'filled_value', '0')
        time = getattr(latest, 'completion_time', 'Unknown')
        print(f"   {product} - ${value} @ {time}")
        
        if len(buys) > 0:
            buy_total = sum(float(getattr(o, 'filled_value', '0')) for o in buys)
            sell_total = sum(float(getattr(o, 'filled_value', '0')) for o in sells)
            profit = sell_total - buy_total
            print(f"\n   Profit/Loss: ${profit:+.2f}")
    else:
        print("❌ NO - NIJA IS NOT SELLING!")
        print(f"\n   Bought {len(buys)} positions but sold 0")
        print(f"\n   Possible reasons:")
        print(f"   1. Bot is not running on Railway")
        print(f"   2. Positions haven't hit +6% target yet")
        print(f"   3. Bot crashed after buying")
    
    # Check current balance
    accounts = client.get_accounts()
    acc_list = getattr(accounts, 'accounts', [])
    
    total_cash = 0
    for acc in acc_list:
        curr = getattr(acc, 'currency', None)
        avail = getattr(acc, 'available_balance', None)
        if curr in ['USD', 'USDC'] and avail:
            total_cash += float(getattr(avail, 'value', '0'))
    
    print(f"\n💰 Current Cash Balance: ${total_cash:.2f}")
    
    if total_cash == 0 and len(buys) > 0:
        print(f"\n🚨 CRITICAL: Bought crypto but have $0 cash!")
        print(f"   Money is missing - check Coinbase transaction history")
    
    print(f"\n" + "="*80)
    print("📋 WHAT TO DO:")
    print("="*80 + "\n")
    
    if len(sells) == 0:
        print("1. Check Railway: https://railway.app")
        print("   → Is the bot running?")
        print("   → When was last log entry?")
        print("\n2. If bot not running:")
        print("   → Deploy it now")
        print("   → It must run 24/7 to sell positions")
        print("\n3. If bot is running:")
        print("   → Wait for positions to hit +6%")
        print("   → Can take 30min - several hours")
        
    if total_cash == 0 and len(buys) > 0:
        print("\n🚨 URGENT: Find the missing money!")
        print("   Run: python3 emergency_money_check.py")
        print("   Check: https://www.coinbase.com/transactions")
    
    print("\n" + "="*80 + "\n")
    
except Exception as e:
    print(f"❌ Error: {e}\n")
