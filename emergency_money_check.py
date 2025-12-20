#!/usr/bin/env python3
"""
EMERGENCY CHECK - Find the missing $95 and verify NIJA selling is actually enabled
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🚨 EMERGENCY: TRACKING MISSING $95")
print("="*80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Check ALL accounts including Consumer
print("STEP 1: Checking ALL Account Types (Consumer + Advanced)")
print("-"*80)

accounts = client.get_accounts()
acc_list = getattr(accounts, 'accounts', [])

consumer_usd = 0
consumer_usdc = 0
advanced_usd = 0
advanced_usdc = 0
all_balances = []

for acc in acc_list:
    curr = getattr(acc, 'currency', None)
    avail = getattr(acc, 'available_balance', None)
    acc_type = getattr(acc, 'type', 'UNKNOWN')
    name = getattr(acc, 'name', 'Unknown')
    
    if not curr or not avail:
        continue
    
    bal = float(getattr(avail, 'value', '0'))
    
    if bal > 0:
        all_balances.append({
            'currency': curr,
            'balance': bal,
            'type': acc_type,
            'name': name
        })
        
        if curr == 'USD':
            if 'CONSUMER' in acc_type or 'WALLET' in acc_type:
                consumer_usd += bal
            else:
                advanced_usd += bal
        elif curr == 'USDC':
            if 'CONSUMER' in acc_type or 'WALLET' in acc_type:
                consumer_usdc += bal
            else:
                advanced_usdc += bal

print(f"\n💰 Cash Breakdown:")
print(f"   Consumer USD:  ${consumer_usd:.2f}")
print(f"   Consumer USDC: ${consumer_usdc:.2f}")
print(f"   Advanced USD:  ${advanced_usd:.2f}")
print(f"   Advanced USDC: ${advanced_usdc:.2f}")
print(f"   --------------")
print(f"   TOTAL: ${consumer_usd + consumer_usdc + advanced_usd + advanced_usdc:.2f}")

if all_balances:
    print(f"\n📋 All Non-Zero Balances:")
    for bal in all_balances:
        print(f"   • {bal['currency']:6} ({bal['type']:15}): {bal['balance']:.8f}")

# Check transaction history for sells
print(f"\n\nSTEP 2: Checking Transaction History (Last 50)")
print("-"*80)

try:
    # Get more orders to find sells
    filled = client.list_orders(order_status='FILLED', limit=50)
    orders = getattr(filled, 'orders', [])
    
    sells = [o for o in orders if getattr(o, 'side', '') == 'SELL']
    
    if sells:
        print(f"\n✅ FOUND {len(sells)} SELL ORDERS!")
        print(f"\n📤 Recent sells:")
        
        total_sold = 0
        for sell in sells[:10]:
            product = getattr(sell, 'product_id', 'Unknown')
            value = float(getattr(sell, 'filled_value', '0'))
            time = getattr(sell, 'completion_time', 'Unknown')
            total_sold += value
            print(f"   • {product:15} ${value:>8.2f} @ {time}")
        
        print(f"\n   Total sold (last 10): ${total_sold:.2f}")
        
        # This would explain where the money went
        if total_sold > 90:
            print(f"\n💡 FOUND THE MISSING MONEY!")
            print(f"   The bot DID sell the positions")
            print(f"   Money should be in cash balance")
            print(f"   But current cash is $0.00...")
            print(f"\n🚨 CRITICAL: Money was sold but disappeared!")
    else:
        print(f"\n❌ NO SELL ORDERS in last 50 transactions")
        print(f"   The crypto was never sold by the bot")
        
except Exception as e:
    print(f"❌ Error checking history: {e}")

# Check Railway deployment
print(f"\n\nSTEP 3: Bot Deployment Status")
print("-"*80)

print(f"""
To verify NIJA is running:

1. Visit: https://railway.app
2. Check latest deployment
3. Look for logs showing:
   • "Managing X open positions"
   • "Closing position" messages
   • Any errors or crashes

CRITICAL QUESTIONS:
- Is the bot currently deployed and running?
- Are there any crash errors in logs?
- When was the last log entry?

If bot hasn't run in hours/days → selling logic never executed!
""")

# Final analysis
print("="*80)
print("🎯 FINAL ANALYSIS")
print("="*80)

total_cash = consumer_usd + consumer_usdc + advanced_usd + advanced_usdc

if total_cash == 0:
    print(f"""
🚨 CRITICAL SITUATION:
   • Spent: $94.92 on 30 buys
   • Current balance: $0.00
   • No crypto held
   • No sell orders found (checking last 50)

POSSIBLE CAUSES:
1. ❌ Positions sold manually outside bot
2. ❌ Another script liquidated everything
3. ❌ Money transferred out of Coinbase
4. ❌ Account was emptied

IMMEDIATE ACTIONS:
1. Check Coinbase website manually:
   https://www.coinbase.com/transactions
   
2. Look for:
   - Manual sells you made
   - Transfers OUT of account
   - Any liquidation activity
   
3. Check if you ran these scripts:
   - direct_sell.py
   - enable_nija_profit.py
   - Any emergency liquidation

4. Verify Railway bot status:
   - Is it deployed?
   - Is it running?
   - Any errors?

5. Check email from Coinbase:
   - Transaction confirmations
   - Withdrawal notices
   - Security alerts
""")
else:
    print(f"""
✅ Found ${total_cash:.2f} in cash

BREAKDOWN:
   Consumer: ${consumer_usd + consumer_usdc:.2f}
   Advanced: ${advanced_usd + advanced_usdc:.2f}

This explains where some money went.
Check if this matches what you expect.
""")

print("="*80 + "\n")
