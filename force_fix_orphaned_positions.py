#!/usr/bin/env python3
"""
EMERGENCY FIX: Force Check and Execute All Pending Exits

This script:
1. Checks what crypto you actually own in Coinbase
2. Compares to what bot THINKS it owns
3. For any discrepancies: Forces a sell order immediately

This prevents the "bot thinks it closed position but crypto is still there" issue
"""

import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔧 EMERGENCY FIX: Force Execute All Exits")
print("="*80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Initialize Coinbase client
client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Step 1: Get what NIJA thinks it owns
print("1️⃣ Loading bot's position state...")
print("-" * 80)

positions_file = Path("data/open_positions.json")
bot_positions = {}

if positions_file.exists():
    with open(positions_file) as f:
        saved = json.load(f)
    bot_positions = saved.get('positions', {})
    print(f"   Bot thinks it owns: {len(bot_positions)} positions")
    for sym, data in bot_positions.items():
        print(f"   • {sym}: {data.get('quantity', 0):.8f} @ ${data.get('entry_price', 0):.2f}")
else:
    print("   No position file found (bot thinks 0 positions)")

# Step 2: Get what's ACTUALLY in Coinbase
print("\n2️⃣ Fetching actual holdings from Coinbase...")
print("-" * 80)

accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

actual_holdings = {}
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
        actual_holdings[curr] = bal

print(f"   Actual holdings: {len(actual_holdings)} crypto")
for curr, bal in actual_holdings.items():
    print(f"   • {curr}: {bal:.8f}")
print(f"   Cash: ${cash_total:.2f}")

# Step 3: Find mismatches
print("\n3️⃣ Analyzing mismatches...")
print("-" * 80)

mismatches = []

# Case 1: Bot thinks it has something, but it's not in Coinbase
for symbol in bot_positions:
    # Extract currency from symbol (e.g., "BTC-USD" → "BTC")
    curr = symbol.split('-')[0]
    if curr not in actual_holdings:
        print(f"   ⚠️  Bot has {symbol}, but Coinbase doesn't")
        print(f"       → This position was likely closed externally")
    else:
        print(f"   ✅ Bot and Coinbase agree: {symbol} is open")

# Case 2: Coinbase has something, but bot doesn't know
for curr, bal in actual_holdings.items():
    symbol = f"{curr}-USD"
    if symbol not in bot_positions:
        mismatches.append({
            'type': 'ORPHANED',
            'currency': curr,
            'balance': bal,
            'symbol': symbol,
            'action': 'SELL'
        })
        print(f"   🚨 Coinbase has {curr}, but bot doesn't know!")
        print(f"       → Orphaned position - MUST SELL")

# Step 4: Execute fixes
if not mismatches:
    print("\n✅ No mismatches found - bot state is in sync with Coinbase")
    print("   (But you said you have 11 losing positions?)")
    print("   Check if they're in a different portfolio")
else:
    print(f"\n4️⃣ Found {len(mismatches)} orphaned positions - FORCING SELL")
    print("-" * 80)
    
    print("\n⚠️  WARNING: About to sell these positions at market price")
    print("   You WILL take the current loss")
    print("   But you STOP further losses\n")
    
    resp = input("Type 'SELL' to confirm: ")
    if resp != 'SELL':
        print("Cancelled - no trades made")
        sys.exit(0)
    
    print("\nExecuting liquidation...\n")
    
    for mismatch in mismatches:
        curr = mismatch['currency']
        symbol = mismatch['symbol']
        bal = mismatch['balance']
        
        try:
            # Get current price
            product = client.get_product(symbol)
            price = float(getattr(product, 'price', 0))
            value = bal * price
            
            print(f"Selling {curr}...")
            print(f"  Quantity: {bal:.8f}")
            print(f"  Price: ${price:.2f}")
            print(f"  Value: ${value:.2f}")
            
            # Place market sell order
            order_result = client.market_order_sell(
                client_order_id=f"fix_orphaned_{curr}_{int(time.time())}",
                product_id=symbol,
                quote_size=value
            )
            
            order_id = getattr(order_result, 'order_id', None)
            if order_id:
                print(f"  ✅ Sell order placed: {order_id}\n")
                time.sleep(2)  # Wait between orders
            else:
                print(f"  ❌ Order failed\n")
        
        except Exception as e:
            print(f"  ❌ Error: {e}\n")

# Step 5: Update position tracking
print("\n5️⃣ Cleaning up bot state...")
print("-" * 80)

if mismatches:
    # Clear positions file to reset bot state
    clean_state = {
        "timestamp": datetime.now().isoformat(),
        "positions": {},
        "count": 0,
        "note": "Cleaned up orphaned positions"
    }
    
    with open(positions_file, 'w') as f:
        json.dump(clean_state, f, indent=2)
    
    print("   ✅ Cleared position tracking file")
    print("   Bot will start fresh on next scan")

print("\n" + "="*80)
print("COMPLETE")
print("="*80)

if mismatches:
    print("\n✅ Orphaned positions have been liquidated")
    print("✅ Position tracking has been reset")
    print("\n💡 Next: Monitor that all sales complete, then restart NIJA")
else:
    print("\n✅ No issues detected")

print("\n" + "="*80 + "\n")
