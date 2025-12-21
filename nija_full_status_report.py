#!/usr/bin/env python3
"""
NIJA STATUS CHECK - Complete Overview
Shows exactly what's happening with your account
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

print("\n" + "="*100)
print(" "*30 + "📊 NIJA COMPLETE STATUS CHECK")
print("="*100)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

# Part 1: Bot State
print("1️⃣ BOT'S SAVED STATE")
print("─" * 100)

positions_file = Path("data/open_positions.json")
bot_state = {}

if positions_file.exists():
    with open(positions_file) as f:
        bot_state = json.load(f)
    
    saved_positions = bot_state.get('positions', {})
    print(f"   Saved positions: {bot_state.get('count', len(saved_positions))}")
    
    if saved_positions:
        print(f"\n   Tracked positions:")
        for symbol, data in saved_positions.items():
            entry = data.get('entry_price', 0)
            qty = data.get('quantity', data.get('crypto_quantity', 0))
            print(f"   • {symbol:10s} Entry=${entry:.2f}, Qty={qty:.8f}")
    else:
        print(f"   ✅ No positions in bot's memory")
else:
    print(f"   ❌ No position file found")

# Part 2: Coinbase Reality
print(f"\n2️⃣ ACTUAL HOLDINGS IN COINBASE")
print("─" * 100)

try:
    from coinbase.rest import RESTClient
    
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    
    accounts = client.get_accounts()
    actual_accounts = getattr(accounts, 'accounts', [])
    
    cash = 0
    crypto = {}
    
    for acc in actual_accounts:
        curr = getattr(acc, 'currency', None)
        avail = getattr(acc, 'available_balance', None)
        
        if not curr or not avail:
            continue
        
        bal = float(getattr(avail, 'value', '0'))
        
        if bal <= 0:
            continue
        
        if curr in ['USD', 'USDC']:
            cash += bal
        else:
            crypto[curr] = bal
    
    print(f"   💵 Cash: ${cash:.2f}")
    
    if crypto:
        print(f"   🪙 Crypto holdings: {len(crypto)} assets\n")
        
        total_value = 0
        for curr, bal in sorted(crypto.items()):
            try:
                product = client.get_product(f"{curr}-USD")
                price = float(getattr(product, 'price', 0))
                value = bal * price
                total_value += value
                pct = (value / (cash + total_value + value)) * 100 if (cash + total_value + value) > 0 else 0
                print(f"   {curr:8s} {bal:15.8f} @ ${price:10.2f} = ${value:10.2f}")
            except:
                print(f"   {curr:8s} {bal:15.8f} @ ?????? (error fetching price)")
        
        print(f"\n   💎 Total crypto: ${total_value:.2f}")
        print(f"   💰 Total portfolio: ${cash + total_value:.2f}")
    else:
        print(f"   ✅ No crypto holdings")
        print(f"\n   💰 Total portfolio: ${cash:.2f}")

except Exception as e:
    print(f"   ❌ Error fetching Coinbase data: {e}")
    print(f"   Check API credentials in .env")

# Part 3: Trade History
print(f"\n3️⃣ RECENT TRADING ACTIVITY")
print("─" * 100)

trade_journal = Path("trade_journal.jsonl")
if trade_journal.exists():
    with open(trade_journal) as f:
        trades = [json.loads(line) for line in f if line.strip()]
    
    print(f"   Total trades: {len(trades)}\n")
    
    # Show last 10
    print("   Last 10 trades:")
    for trade in trades[-10:]:
        ts = trade.get('timestamp', 'N/A')
        sym = trade.get('symbol', 'N/A')
        side = trade.get('side', 'N/A')
        price = trade.get('price', 0)
        size = trade.get('size_usd', 0)
        # Extract date from timestamp
        ts_short = ts.split('T')[0] if 'T' in ts else ts
        print(f"   {ts_short} | {side:4s} {sym:8s} @ ${price:8.2f} (${size:6.0f})")
else:
    print(f"   ❌ No trade history")

# Part 4: Analysis
print(f"\n4️⃣ ANALYSIS & DIAGNOSIS")
print("─" * 100)

if saved_positions and crypto:
    print(f"\n   ⚠️  MISMATCH DETECTED:")
    print(f"   • Bot thinks: {len(saved_positions)} positions")
    print(f"   • Coinbase has: {len(crypto)} holdings")
    print(f"\n   This indicates:")
    print(f"   • Positions were bought successfully")
    print(f"   • Exit orders might have been placed but not confirmed")
    print(f"   • Bot state file wasn't updated after sales")

elif crypto and not saved_positions:
    print(f"\n   🚨 CRITICAL MISMATCH:")
    print(f"   ✅ Bot thinks: 0 positions")
    print(f"   ⚠️  Coinbase has: {len(crypto)} holdings")
    print(f"\n   This means:")
    print(f"   • Positions opened successfully")
    print(f"   • Exit conditions were likely triggered")
    print(f"   • But sales failed or weren't properly tracked")
    print(f"   • Orphaned crypto is now losing money silently")

elif saved_positions and not crypto:
    print(f"\n   ✅ Sync OK (but positions might be phantom):")
    print(f"   • Bot thinks: {len(saved_positions)} positions")
    print(f"   • Coinbase has: 0 holdings")
    print(f"\n   Possible causes:")
    print(f"   • Positions closed and bot state wasn't cleared")
    print(f"   • Phantom positions from earlier error")

elif not saved_positions and not crypto:
    print(f"\n   ✅ CLEAN STATE:")
    print(f"   • Bot: 0 positions")
    print(f"   • Coinbase: 0 holdings")
    print(f"   All funds in cash - ready to trade")

# Part 5: Recommendations
print(f"\n5️⃣ NEXT STEPS")
print("─" * 100)

if crypto:
    print(f"\n   🚨 IMMEDIATE ACTION REQUIRED:")
    print(f"\n   You have {len(crypto)} crypto holdings in Coinbase that are losing money")
    print(f"   The bot has lost control of them (position sync is broken)")
    print(f"\n   ✅ OPTION 1: Emergency Liquidate (RECOMMENDED)")
    print(f"   └─ python3 emergency_sell_all_now.py")
    print(f"   └─ Sells ALL crypto at market price immediately")
    print(f"   └─ Stops all losses from accumulating further")
    print(f"   └─ Accept the current USD loss to prevent worse losses")
    print(f"\n   ✅ OPTION 2: Selective Fix")
    print(f"   └─ python3 force_fix_orphaned_positions.py")
    print(f"   └─ Fixes just the orphaned (bot-unknown) positions")
    print(f"   └─ More surgical but requires more manual review")
    print(f"\n   ✅ OPTION 3: Manual Sell")
    print(f"   └─ Go to https://coinbase.com/advanced-portfolio")
    print(f"   └─ Sell all {len(crypto)} coins manually")
    print(f"   └─ Then run: rm data/open_positions.json")
    
elif saved_positions:
    print(f"\n   ⚠️  BOT HAS PHANTOM POSITIONS")
    print(f"\n   Bot is tracking {len(saved_positions)} positions")
    print(f"   But Coinbase shows no crypto holdings")
    print(f"\n   This means:")
    print(f"   • Sales completed but bot state wasn't cleared")
    print(f"   • OR bot never actually bought them")
    print(f"\n   FIX:")
    print(f"   └─ rm data/open_positions.json  # Clear phantom positions")
else:
    print(f"\n   ✅ ALL CLEAR")
    print(f"\n   No action needed:")
    print(f"   • Bot has no open positions")
    print(f"   • Coinbase shows no crypto")
    print(f"   • You're 100% cash")
    print(f"\n   When ready to trade again:")
    print(f"   • Ensure exits are working (see fixes in IMMEDIATE_ACTION_PLAN.md)")
    print(f"   • Test with $50-100 capital")
    print(f"   • Monitor first few trades carefully")

print("\n" + "="*100 + "\n")

print("📋 Full analysis written to ROOT_CAUSE_ANALYSIS.md")
print("📋 Recovery plan in IMMEDIATE_ACTION_PLAN.md")
print("\n")
