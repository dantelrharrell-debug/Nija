#!/usr/bin/env python3
"""
DIAGNOSTIC: Show what NIJA thinks vs what's actually in Coinbase
This will expose the sync issue causing losses
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Load env
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔍 NIJA POSITION SYNC DIAGNOSTIC")
print("="*80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Initialize Coinbase client
client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# 1. What NIJA THINKS it holds
print("1️⃣ WHAT NIJA THINKS IT HOLDS (from open_positions.json):")
print("-" * 80)
positions_file = Path("data/open_positions.json")
if positions_file.exists():
    with open(positions_file) as f:
        saved = json.load(f)
    nija_positions = saved.get('positions', {})
    print(f"   Saved positions count: {saved.get('count', 0)}")
    if nija_positions:
        for symbol, data in nija_positions.items():
            print(f"   • {symbol}: Entry=${data.get('entry_price'):.2f}, Qty={data.get('quantity'):.8f}")
    else:
        print("   ✅ Bot thinks NO positions are open")
else:
    print("   ❌ No saved positions file")

# 2. What ACTUALLY exists in Coinbase
print("\n2️⃣ ACTUAL HOLDINGS IN COINBASE (real-time):")
print("-" * 80)

try:
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    actual_crypto = []
    cash_total = 0
    
    for acc in accounts:
        curr = getattr(acc, 'currency', None)
        avail = getattr(acc, 'available_balance', None)
        
        if not curr or not avail:
            continue
        
        bal = float(getattr(avail, 'value', '0'))
        
        if bal <= 0:
            continue
        
        if curr in ['USD', 'USDC']:
            cash_total += bal
        else:
            actual_crypto.append({
                'currency': curr,
                'balance': bal,
                'symbol': f"{curr}-USD"
            })
    
    print(f"   💵 Cash (USD/USDC): ${cash_total:.2f}")
    print(f"   🪙 Crypto positions: {len(actual_crypto)}")
    
    if actual_crypto:
        print("\n   Current holdings:")
        total_crypto_value = 0
        
        # Get prices for all positions
        for pos in actual_crypto:
            try:
                product = client.get_product(pos['symbol'])
                price = float(getattr(product, 'price', 0))
                value = pos['balance'] * price
                total_crypto_value += value
                
                print(f"   • {pos['currency']:8s} {pos['balance']:15.8f} @ ${price:10.2f} = ${value:10.2f}")
                pos['price'] = price
                pos['value'] = value
            except Exception as e:
                print(f"   • {pos['currency']:8s} {pos['balance']:15.8f} @ ?????? (price error: {e})")
        
        print(f"\n   Total crypto value: ${total_crypto_value:.2f}")
        print(f"   Total portfolio: ${cash_total + total_crypto_value:.2f}")
    else:
        print("\n   ✅ No actual crypto holdings")
        
except Exception as e:
    print(f"   ❌ Error fetching accounts: {e}")
    actual_crypto = []

# 3. The MISMATCH
print("\n3️⃣ COMPARISON - WHERE'S THE MISMATCH?")
print("-" * 80)

if nija_positions and actual_crypto:
    print(f"   ⚠️  NIJA expects {len(nija_positions)} positions")
    print(f"   ⚠️  But Coinbase has {len(actual_crypto)} positions")
    print(f"\n   THIS IS THE BUG: Bot positions ≠ Actual holdings")
    print(f"   Likely cause: Positions were closed but bot didn't update")
    
elif actual_crypto and not nija_positions:
    print(f"   🚨 CRITICAL MISMATCH:")
    print(f"   ✅ Bot thinks: 0 positions")
    print(f"   ⚠️  Reality: {len(actual_crypto)} holdings in Coinbase!")
    print(f"\n   HOW THIS HAPPENS:")
    print(f"   1. Bot bought and placed sell orders")
    print(f"   2. Orders filled, but bot crashed before recording")
    print(f"   3. Position file shows empty, but crypto still there")
    print(f"\n   🔴 RESULT: Silent losses accumulating!")
    
elif not nija_positions and not actual_crypto:
    print(f"   ✅ Sync OK: Bot has 0, Coinbase has 0")
    print(f"   (But you said you have 11 losing positions?)")
    print(f"   Check if they're in a different portfolio")
else:
    print(f"   ✅ Sync OK")

# 4. Trade history - are sales actually happening?
print("\n4️⃣ RECENT TRADE HISTORY (last 5 trades):")
print("-" * 80)

trade_journal = Path("trade_journal.jsonl")
if trade_journal.exists():
    with open(trade_journal) as f:
        trades = [json.loads(line) for line in f if line.strip()]
    
    # Show last 5
    for trade in trades[-5:]:
        ts = trade.get('timestamp', 'N/A')
        sym = trade.get('symbol', 'N/A')
        side = trade.get('side', 'N/A')
        price = trade.get('price', 0)
        size = trade.get('size_usd', 0)
        print(f"   {ts} | {side:4s} {sym:8s} @ ${price:.2f} (${size:.0f})")
else:
    print("   ❌ No trade history")

# 5. Check if sells are failing silently
print("\n5️⃣ CHECKING OPEN/FAILED ORDERS:")
print("-" * 80)

try:
    open_orders = client.list_orders(order_status='OPEN')
    orders = getattr(open_orders, 'orders', [])
    
    if orders:
        print(f"   ⚠️  {len(orders)} OPEN orders (haven't filled yet!):")
        for order in orders[:10]:  # Show first 10
            prod = getattr(order, 'product_id', 'N/A')
            side = getattr(order, 'side', 'N/A')
            size = getattr(order, 'size', 'N/A')
            price = getattr(order, 'price', 'N/A')
            print(f"   • {side:4s} {prod:8s} {size} @ ${price}")
    else:
        print("   ✅ No open orders")
except Exception as e:
    print(f"   ⚠️  Error checking orders: {e}")

print("\n" + "="*80)
print("📋 SUMMARY")
print("="*80)

if actual_crypto and not nija_positions:
    print("\n🚨 PRIMARY ISSUE:")
    print("   Your crypto IS in Coinbase, but bot doesn't know about it")
    print("   This means positions opened, but bot state got out of sync")
    print("\n💡 SOLUTION:")
    print("   1. Manually check what these coins are worth now")
    print("   2. If underwater: Sell immediately to stop losses")
    print("   3. Restart bot with fresh position tracking")
else:
    print("\n✅ No immediate position mismatch detected")

print("\n" + "="*80)
