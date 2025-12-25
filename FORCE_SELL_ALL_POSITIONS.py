#!/usr/bin/env python3
"""
EMERGENCY POSITION LIQUIDATION
Forces the bot to sell ALL crypto holdings immediately
"""

import sys
import os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("🚨 EMERGENCY LIQUIDATION - SELL ALL CRYPTO POSITIONS")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get all accounts
print("🔍 Fetching all crypto holdings...")
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

crypto_to_sell = []
total_value = 0

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    
    if not curr or not avail_obj:
        continue
    
    if curr in ['USD', 'USDC']:
        continue  # Skip cash
    
    amount = float(getattr(avail_obj, 'value', 0))
    
    if amount > 0:
        crypto_to_sell.append({
            'currency': curr,
            'amount': amount,
            'symbol': f"{curr}-USD"
        })

if not crypto_to_sell:
    print("\n✅ No crypto positions found - all is cash")
    print("=" * 80)
    sys.exit(0)

print(f"\n📊 Found {len(crypto_to_sell)} crypto positions to liquidate:\n")
for crypto in crypto_to_sell:
    print(f"  • {crypto['currency']}: {crypto['amount']}")

print("\n" + "=" * 80)
print("⚠️  STARTING LIQUIDATION - SELLING ALL POSITIONS...")
print("=" * 80 + "\n")

sold = 0
failed = 0

for crypto in crypto_to_sell:
    symbol = crypto['symbol']
    currency = crypto['currency']
    amount = crypto['amount']
    
    try:
        print(f"📤 Selling {amount:.8f} {currency}...")
        
        # Place market sell order
        order = client.market_order_sell(
            product_id=symbol,
            base_size=str(amount)
        )
        
        if order and hasattr(order, 'success') and getattr(order, 'success', False):
            print(f"  ✅ SOLD {currency}")
            sold += 1
        else:
            error = getattr(order, 'error_response', 'Unknown error') if order else 'No response'
            print(f"  ❌ FAILED to sell {currency}: {error}")
            failed += 1
            
    except Exception as e:
        print(f"  ❌ ERROR selling {currency}: {e}")
        failed += 1

print("\n" + "=" * 80)
print("📊 LIQUIDATION SUMMARY:")
print("=" * 80)
print(f"✅ Successfully sold: {sold} positions")
print(f"❌ Failed to sell: {failed} positions")
print("=" * 80)

# Clear saved positions file
positions_files = [
    "/usr/src/app/data/open_positions.json",
    "./data/open_positions.json"
]

for filepath in positions_files:
    if os.path.exists(filepath):
        print(f"\n🗑️  Clearing saved positions: {filepath}")
        import json
        with open(filepath, 'w') as f:
            json.dump({}, f)
        print("  ✅ Cleared")

print("\n✅ Liquidation complete - bot will restart with clean state")
print("=" * 80)
