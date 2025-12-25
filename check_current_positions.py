#!/usr/bin/env python3
"""
Check current positions and NIJA's selling activity
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔍 NIJA POSITION & SELLING CHECK")
print("="*80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get accounts
print("📊 Fetching account positions...")
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

positions = []
usd_balance = 0
usdc_balance = 0

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    acc_type = getattr(acc, 'type', 'UNKNOWN')
    
    if not curr or not avail_obj:
        continue
    
    bal = float(getattr(avail_obj, 'value', '0'))
    
    if curr == 'USD':
        usd_balance += bal
    elif curr == 'USDC':
        usdc_balance += bal
    elif bal > 0 and curr not in ['USDT']:
        positions.append({
            'currency': curr,
            'balance': bal,
            'type': acc_type
        })

print(f"\n💰 CASH BALANCE:")
print(f"   USD:  ${usd_balance:.2f}")
print(f"   USDC: ${usdc_balance:.2f}")
print(f"   TOTAL: ${usd_balance + usdc_balance:.2f}")

print(f"\n📦 CRYPTO POSITIONS: {len(positions)}")
print("="*80)

total_value = 0
for i, pos in enumerate(positions, 1):
    curr = pos['currency']
    bal = pos['balance']
    acc_type = pos['type']
    
    try:
        product = client.get_product(f"{curr}-USD")
        price = float(getattr(product, 'price', 0))
        value = bal * price
        total_value += value
        
        print(f"\n{i}. {curr} ({acc_type})")
        print(f"   Amount: {bal:.8f}")
        print(f"   Price:  ${price:.4f}")
        print(f"   Value:  ${value:.2f}")
        
        pos['price'] = price
        pos['value'] = value
    except Exception as e:
        print(f"\n{i}. {curr} ({acc_type})")
        print(f"   Amount: {bal:.8f}")
        print(f"   Error getting price: {e}")

print("\n" + "="*80)
print(f"💎 TOTAL CRYPTO VALUE: ${total_value:.2f}")
print(f"💰 TOTAL PORTFOLIO: ${total_value + usd_balance + usdc_balance:.2f}")
print("="*80)

# Check open orders (selling activity)
print(f"\n📤 CHECKING OPEN ORDERS (SELL ACTIVITY)...")
print("="*80)

try:
    open_orders = client.list_orders(order_status='OPEN')
    orders = getattr(open_orders, 'orders', [])
    
    if orders:
        print(f"\n✅ Found {len(orders)} open order(s):")
        for order in orders:
            product_id = getattr(order, 'product_id', 'Unknown')
            side = getattr(order, 'side', 'Unknown')
            order_type = getattr(order, 'order_type', 'Unknown')
            status = getattr(order, 'status', 'Unknown')
            created = getattr(order, 'created_time', 'Unknown')
            
            print(f"\n  • {product_id}")
            print(f"    Side: {side} | Type: {order_type} | Status: {status}")
            print(f"    Created: {created}")
            
            if side == 'SELL':
                print(f"    ✅ NIJA IS TRYING TO SELL THIS")
    else:
        print("\n❌ NO OPEN ORDERS")
        print("   NIJA is NOT currently trying to sell anything")
except Exception as e:
    print(f"\n❌ Error fetching orders: {e}")

# Check recent filled orders
print(f"\n📝 CHECKING RECENT FILLED ORDERS (LAST 10)...")
print("="*80)

try:
    filled_orders = client.list_orders(order_status='FILLED', limit=10)
    orders = getattr(filled_orders, 'orders', [])
    
    if orders:
        sell_count = 0
        buy_count = 0
        
        print(f"\n✅ Found {len(orders)} recent filled order(s):\n")
        for order in orders[:10]:
            product_id = getattr(order, 'product_id', 'Unknown')
            side = getattr(order, 'side', 'Unknown')
            filled_time = getattr(order, 'completion_time', 'Unknown')
            filled_value = getattr(order, 'filled_value', '0')
            
            if side == 'SELL':
                sell_count += 1
                emoji = "📤"
            else:
                buy_count += 1
                emoji = "📥"
            
            print(f"{emoji} {side:4} {product_id:15} ${filled_value:>8} @ {filled_time}")
        
        print(f"\n📊 RECENT ACTIVITY:")
        print(f"   BUY orders:  {buy_count}")
        print(f"   SELL orders: {sell_count}")
        
        if sell_count == 0:
            print(f"\n⚠️  WARNING: No recent SELL orders!")
            print(f"   NIJA may not be selling positions properly")
    else:
        print("\n❌ No filled orders found")
except Exception as e:
    print(f"\n❌ Error fetching filled orders: {e}")

print("\n" + "="*80)
print("🎯 ANALYSIS:")
print("="*80)

if len(positions) > 8:
    print(f"\n⚠️  You have {len(positions)} positions but NIJA is configured for max 8")
    print(f"   Possible reasons:")
    print(f"   1. These are old positions from Consumer wallet (not managed by NIJA)")
    print(f"   2. Positions opened before limit was set")
    print(f"   3. NIJA should sell down to 8 positions soon")
    
    consumer_positions = [p for p in positions if 'CONSUMER' in p['type'] or 'WALLET' in p['type']]
    if consumer_positions:
        print(f"\n   ℹ️  {len(consumer_positions)} positions are in Consumer wallet")
        print(f"      These are NOT managed by NIJA's trading bot")
        print(f"      NIJA can only manage Advanced Trade positions")

if len(positions) == 8:
    print(f"\n✅ Exactly 8 positions - matches NIJA's max_concurrent_positions setting")

if len(positions) < 8:
    print(f"\n✅ {len(positions)} positions - below NIJA's limit of 8")
    print(f"   NIJA can open {8 - len(positions)} more position(s)")

print("\n" + "="*80)
print("💡 RECOMMENDATIONS:")
print("="*80)

if total_value + usd_balance + usdc_balance < 50:
    print("\n⚠️  Low capital: Portfolio value < $50")
    print("   Consider transferring more funds to Advanced Trade")
    print("   https://www.coinbase.com/advanced-portfolio")
elif usd_balance + usdc_balance < 10:
    print("\n⚠️  Low cash reserves: < $10 available")
    print("   NIJA may not be able to open new positions")
    print("   Consider selling some crypto to free up cash")
else:
    print(f"\n✅ Adequate capital: ${usd_balance + usdc_balance:.2f} cash available")
    print(f"   NIJA can continue trading")

print("="*80 + "\n")
