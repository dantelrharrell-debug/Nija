#!/usr/bin/env python3
"""
Check saved positions file and compare with actual Coinbase holdings
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
print("🔍 POSITION FILE vs ACTUAL HOLDINGS COMPARISON")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Check saved positions file
print("📁 Checking saved positions file...")
positions_files = [
    "/usr/src/app/data/open_positions.json",
    "./data/open_positions.json"
]

saved_positions = {}
for filepath in positions_files:
    if os.path.exists(filepath):
        print(f"✅ Found: {filepath}")
        with open(filepath, 'r') as f:
            saved_positions = json.load(f)
        break
else:
    print("❌ No saved positions file found")

if saved_positions:
    print(f"\n📊 Bot thinks it has {len(saved_positions)} open positions:")
    for symbol, pos in saved_positions.items():
        entry = pos.get('entry_price', 0)
        quantity = pos.get('quantity', 0)
        timestamp = pos.get('timestamp', 'unknown')
        print(f"  • {symbol}: {quantity} @ ${entry:.4f} (opened: {timestamp})")
else:
    print("\n✅ Bot tracking file is empty (no tracked positions)")

# Get actual Coinbase holdings
print("\n" + "=" * 80)
print("🏦 Checking ACTUAL Coinbase holdings...")
print("=" * 80)

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

actual_crypto = {}
for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    
    if not curr or not avail_obj or curr in ['USD', 'USDC']:
        continue
    
    amount = float(getattr(avail_obj, 'value', 0))
    if amount > 0:
        actual_crypto[curr] = amount

if actual_crypto:
    print(f"\n📊 Actually holding {len(actual_crypto)} crypto positions:")
    for curr, amount in actual_crypto.items():
        print(f"  • {curr}: {amount:.8f}")
else:
    print("\n✅ No actual crypto holdings (all cash)")

# Comparison
print("\n" + "=" * 80)
print("🔍 DIAGNOSIS:")
print("=" * 80)

if saved_positions and not actual_crypto:
    print("\n⚠️  MISMATCH DETECTED:")
    print("   Bot thinks it has positions, but Coinbase shows no crypto!")
    print("   This means positions were:")
    print("   1. Manually closed outside the bot, OR")
    print("   2. Liquidated automatically, OR")
    print("   3. In Consumer wallet (not visible to Advanced Trade API)")
    print("\n✅ SOLUTION: Clear the position tracking file")
    
elif not saved_positions and actual_crypto:
    print("\n⚠️  MISMATCH DETECTED:")
    print("   Coinbase has crypto, but bot isn't tracking it!")
    print("   This means:")
    print("   1. Positions were bought manually (not by bot), OR")
    print("   2. Bot crashed and lost tracking file, OR")
    print("   3. Crypto is in Consumer wallet (bot can't manage it)")
    print("\n⚠️  Bot will NOT sell these - they're not tracked")
    
elif saved_positions and actual_crypto:
    # Check if they match
    saved_symbols = set(saved_positions.keys())
    actual_symbols = set(f"{curr}-USD" for curr in actual_crypto.keys())
    
    if saved_symbols == actual_symbols:
        print("\n✅ PERFECT MATCH:")
        print("   Bot tracking file matches actual Coinbase holdings")
        print("   Bot SHOULD be managing these positions normally")
    else:
        print("\n⚠️  PARTIAL MISMATCH:")
        only_in_saved = saved_symbols - actual_symbols
        only_in_actual = actual_symbols - saved_symbols
        
        if only_in_saved:
            print(f"\n   Bot tracking but NOT in Coinbase: {only_in_saved}")
        if only_in_actual:
            print(f"\n   In Coinbase but NOT tracked: {only_in_actual}")
else:
    print("\n✅ ALL CLEAR:")
    print("   No tracked positions, no actual holdings")
    print("   Bot is ready to trade fresh")

print("\n" + "=" * 80)
