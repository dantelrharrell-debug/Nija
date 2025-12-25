#!/usr/bin/env python3
"""
Check if NIJA is currently trading and if it's selling positions correctly
"""
import os
import sys
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🤖 NIJA BOT TRADING & SELLING STATUS CHECK")
print("="*80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Initialize Coinbase client
client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# 1. Check current positions
print("="*80)
print("📊 CURRENT POSITIONS")
print("="*80 + "\n")

accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

crypto_positions = []
usd_balance = 0

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    
    if not curr or not avail_obj:
        continue
    
    bal = float(getattr(avail_obj, 'value', '0'))
    
    if curr in ['USD', 'USDC']:
        usd_balance += bal
    elif bal > 0:
        crypto_positions.append({'currency': curr, 'balance': bal})

print(f"💰 Cash: ${usd_balance:.2f}")
print(f"🪙 Open Crypto Positions: {len(crypto_positions)}\n")

if crypto_positions:
    for pos in crypto_positions:
        print(f"   {pos['currency']:8s}: {pos['balance']:.8f}")
    print()

# 2. Check recent orders (last 24 hours of activity)
print("="*80)
print("📈 RECENT TRADING ACTIVITY (LAST 20 ORDERS)")
print("="*80 + "\n")

try:
    # Get recent fills/orders
    orders = client.list_orders(limit=20)
    orders_list = getattr(orders, 'orders', [])
    
    if not orders_list:
        print("❌ No recent orders found\n")
    else:
        buy_count = 0
        sell_count = 0
        
        print(f"Found {len(orders_list)} recent orders:\n")
        
        for order in orders_list[:20]:
            side = getattr(order, 'side', 'UNKNOWN')
            product_id = getattr(order, 'product_id', 'UNKNOWN')
            status = getattr(order, 'status', 'UNKNOWN')
            created = getattr(order, 'created_time', 'UNKNOWN')
            filled_val = getattr(order, 'filled_value', '0')
            
            symbol = "📥" if side == "BUY" else "📤"
            
            print(f"{symbol} {side:4s} {product_id:12s} ${filled_val:>12s} | {status:10s} | {created}")
            
            if side == "BUY":
                buy_count += 1
            elif side == "SELL":
                sell_count += 1
        
        print(f"\n📊 Order Breakdown:")
        print(f"   BUY orders:  {buy_count}")
        print(f"   SELL orders: {sell_count}")
        
        if sell_count == 0:
            print("\n⚠️  WARNING: NO SELL ORDERS DETECTED")
            print("   This suggests the position management fix may not be deployed yet")
            print("   OR bot hasn't hit any exit conditions since fix was applied")
        elif sell_count > 0:
            print(f"\n✅ SELL ORDERS DETECTED: {sell_count}")
            print("   Bot IS executing sell orders!")
            sell_ratio = sell_count / (buy_count + sell_count) * 100
            print(f"   Sell/Total ratio: {sell_ratio:.1f}%")

except Exception as e:
    print(f"❌ Error fetching orders: {e}")

# 3. Check bot's position tracking file
print("\n" + "="*80)
print("📁 BOT POSITION TRACKING FILE")
print("="*80 + "\n")

position_file = "data/open_positions.json"
if os.path.exists(position_file):
    try:
        with open(position_file, 'r') as f:
            positions = json.load(f)
        
        if not positions:
            print("✅ Position file is EMPTY (no tracked positions)")
        else:
            print(f"📊 Bot tracking {len(positions)} position(s):\n")
            for symbol, data in positions.items():
                print(f"   {symbol}:")
                print(f"      Entry: ${data.get('entry_price', 'N/A')}")
                print(f"      Size: {data.get('size', 'N/A')}")
                print(f"      Stop: ${data.get('stop_loss', 'N/A')}")
                print(f"      Take: ${data.get('take_profit', 'N/A')}\n")
    except Exception as e:
        print(f"❌ Error reading position file: {e}")
else:
    print("⚠️  Position file does not exist")
    print(f"   Expected: {position_file}")

# 4. Final Analysis
print("\n" + "="*80)
print("🎯 ANALYSIS: IS NIJA TRADING & SELLING CORRECTLY?")
print("="*80 + "\n")

if len(crypto_positions) == 0 and usd_balance == 0:
    print("❌ CRITICAL: Account is completely empty ($0 cash, 0 positions)")
    print("   Status: Bot CANNOT trade (no capital)")
    print("   Action: Deposit funds to Advanced Trade to enable trading\n")
elif len(crypto_positions) > 0:
    print(f"⚠️  {len(crypto_positions)} crypto position(s) currently open")
    print("   Status: Bot has open positions")
    print("   Check: Are these positions being managed for exits?\n")
elif usd_balance > 0:
    print(f"✅ ${usd_balance:.2f} available cash")
    print("   Status: Bot can open new positions")
    print("   Check: Is bot scanning markets and entering trades?\n")

print("="*80 + "\n")
