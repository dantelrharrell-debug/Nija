#!/usr/bin/env python3
"""
DEEP DIAGNOSTIC - Where did the 20 bought positions go?
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔍 DEEP DIAGNOSTIC - TRACKING THE 20 BUYS")
print("="*80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Check 1: All filled orders with details
print("STEP 1: Analyzing Recent Orders (Last 30)")
print("-"*80)

filled = client.list_orders(order_status='FILLED', limit=30)
orders = getattr(filled, 'orders', [])

buys = []
sells = []

for order in orders:
    side = getattr(order, 'side', 'Unknown')
    product = getattr(order, 'product_id', 'Unknown')
    filled_value = getattr(order, 'filled_value', '0')
    completed = getattr(order, 'completion_time', 'Unknown')
    
    if side == 'BUY':
        buys.append({
            'product': product,
            'value': float(filled_value),
            'time': completed
        })
    elif side == 'SELL':
        sells.append({
            'product': product,
            'value': float(filled_value),
            'time': completed
        })

print(f"\n📊 Order Summary:")
print(f"   Total BUY orders:  {len(buys)}")
print(f"   Total SELL orders: {len(sells)}")

if len(buys) > 0:
    print(f"\n📥 Recent BUYS (last 10):")
    for buy in buys[:10]:
        print(f"   • {buy['product']:15} ${buy['value']:>8} @ {buy['time']}")
    
    buy_total = sum(b['value'] for b in buys)
    print(f"\n   Total bought: ${buy_total:.2f}")

if len(sells) > 0:
    print(f"\n📤 Recent SELLS:")
    for sell in sells:
        print(f"   • {sell['product']:15} ${sell['value']:>8} @ {sell['time']}")
    
    sell_total = sum(s['value'] for s in sells)
    print(f"\n   Total sold: ${sell_total:.2f}")
else:
    print(f"\n⚠️  NO SELL ORDERS FOUND")

# Check 2: Current account balances
print(f"\n\nSTEP 2: Current Account Balances")
print("-"*80)

accounts = client.get_accounts()
acc_list = getattr(accounts, 'accounts', [])

usd_total = 0
usdc_total = 0
crypto_positions = []

for acc in acc_list:
    curr = getattr(acc, 'currency', None)
    avail = getattr(acc, 'available_balance', None)
    acc_type = getattr(acc, 'type', 'UNKNOWN')
    
    if not curr or not avail:
        continue
    
    bal = float(getattr(avail, 'value', '0'))
    
    if bal > 0:
        if curr == 'USD':
            usd_total += bal
            print(f"\n💵 USD ({acc_type}): ${bal:.2f}")
        elif curr == 'USDC':
            usdc_total += bal
            print(f"\n💵 USDC ({acc_type}): ${bal:.2f}")
        elif curr not in ['USDT']:
            crypto_positions.append({
                'currency': curr,
                'balance': bal,
                'type': acc_type
            })

print(f"\n💰 Cash Summary:")
print(f"   Total USD:  ${usd_total:.2f}")
print(f"   Total USDC: ${usdc_total:.2f}")
print(f"   Total Cash: ${usd_total + usdc_total:.2f}")

if crypto_positions:
    print(f"\n📦 Crypto Positions: {len(crypto_positions)}")
    total_crypto_value = 0
    
    for pos in crypto_positions:
        curr = pos['currency']
        bal = pos['balance']
        acc_type = pos['type']
        
        try:
            product = client.get_product(f"{curr}-USD")
            price = float(getattr(product, 'price', 0))
            value = bal * price
            total_crypto_value += value
            
            print(f"\n   {curr} ({acc_type}):")
            print(f"      Amount: {bal:.8f}")
            print(f"      Price:  ${price:.4f}")
            print(f"      Value:  ${value:.2f}")
        except:
            print(f"\n   {curr} ({acc_type}): {bal:.8f} (price unavailable)")
    
    print(f"\n   Total Crypto Value: ${total_crypto_value:.2f}")
else:
    print(f"\n✅ No crypto positions (all cash)")

# Check 3: Open orders
print(f"\n\nSTEP 3: Open Orders (Pending)")
print("-"*80)

try:
    open_orders = client.list_orders(order_status='OPEN')
    open_list = getattr(open_orders, 'orders', [])
    
    if open_list:
        print(f"\n📋 Found {len(open_list)} open order(s):")
        for order in open_list:
            product = getattr(order, 'product_id', 'Unknown')
            side = getattr(order, 'side', 'Unknown')
            status = getattr(order, 'status', 'Unknown')
            created = getattr(order, 'created_time', 'Unknown')
            print(f"   • {product} {side} - {status} @ {created}")
    else:
        print(f"\n✅ No open orders")
except Exception as e:
    print(f"\n❌ Error checking open orders: {e}")

# Analysis
print(f"\n\n" + "="*80)
print("🎯 ANALYSIS: What Happened to the 20 Bought Positions?")
print("="*80)

print(f"\n📊 Facts:")
print(f"   • {len(buys)} BUY orders executed")
print(f"   • {len(sells)} SELL orders executed")
print(f"   • {len(crypto_positions)} crypto positions currently held")
print(f"   • ${usd_total + usdc_total:.2f} cash available")

if len(buys) > 0 and len(sells) == 0 and len(crypto_positions) == 0:
    print(f"\n🚨 CRITICAL FINDING:")
    print(f"   ❌ Bot bought {len(buys)} positions")
    print(f"   ❌ Bot sold 0 positions")
    print(f"   ❌ 0 crypto currently held")
    print(f"\n💡 This means:")
    print(f"   1. Positions were sold manually (not by the bot)")
    print(f"   2. OR positions were in Consumer wallet and got liquidated")
    print(f"   3. OR the bought crypto went to a different account")
    print(f"\n🔍 INVESTIGATION NEEDED:")
    print(f"   • Check if you manually sold via Coinbase app")
    print(f"   • Check if another script ran (direct_sell.py, enable_nija_profit.py)")
    print(f"   • Check Coinbase transaction history manually")

elif len(buys) > 0 and len(sells) > 0:
    buy_total = sum(b['value'] for b in buys)
    sell_total = sum(s['value'] for s in sells)
    profit = sell_total - buy_total
    profit_pct = (profit / buy_total * 100) if buy_total > 0 else 0
    
    print(f"\n✅ TRADING ACTIVITY DETECTED:")
    print(f"   Bought:  ${buy_total:.2f}")
    print(f"   Sold:    ${sell_total:.2f}")
    print(f"   Profit:  ${profit:+.2f} ({profit_pct:+.2f}%)")
    
    if profit > 0:
        print(f"\n🎉 BOT IS PROFITABLE!")
    else:
        print(f"\n⚠️  Currently at a loss")

elif len(buys) == 0:
    print(f"\n⚠️  NO BUY ORDERS FOUND")
    print(f"   Bot may not have traded yet")

print(f"\n\n" + "="*80)
print("📋 NEXT STEPS:")
print("="*80)

if len(buys) > 0 and len(sells) == 0:
    print(f"""
1. Check Coinbase transaction history manually:
   https://www.coinbase.com/transactions

2. Check if you ran any liquidation scripts:
   - direct_sell.py
   - enable_nija_profit.py
   - Any manual sells via Coinbase app

3. Check Railway logs for SELL activity:
   https://railway.app

4. If positions were manually sold:
   - Bot will resume trading with current balance
   - Monitor for new BUY → SELL cycles

5. Verify bot is configured to sell:
   - Code has selling logic ✅
   - Targets: +6% take profit, -2% stop loss ✅
   - But bot must be RUNNING to execute sells
""")
else:
    print(f"""
✅ Normal operation - continue monitoring
   Run this script again in 30-60 minutes
""")

print("="*80 + "\n")
