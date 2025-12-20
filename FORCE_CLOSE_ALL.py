#!/usr/bin/env python3
"""
FORCE CLOSE ALL POSITIONS - Emergency liquidation
Bypasses bot logic and directly sells ALL crypto
"""

import sys
import os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient
from dotenv import load_dotenv
import json

load_dotenv()

print("=" * 80)
print("🚨 EMERGENCY FORCE CLOSE - SELLING EVERYTHING NOW")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Step 1: Get all crypto holdings
print("1️⃣ Scanning for crypto holdings...")
print("-" * 80)

accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

crypto_holdings = []

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    
    if not curr or not avail_obj or curr in ['USD', 'USDC']:
        continue
    
    amount = float(getattr(avail_obj, 'value', 0))
    
    if amount > 0:
        crypto_holdings.append({
            'currency': curr,
            'amount': amount,
            'symbol': f"{curr}-USD"
        })

if not crypto_holdings:
    print("\n✅ No crypto found - checking bot's position tracking file...")
    
    # Check saved positions
    positions_file = "/usr/src/app/data/open_positions.json"
    local_file = "./data/open_positions.json"
    
    for filepath in [positions_file, local_file]:
        if os.path.exists(filepath):
            print(f"\n📁 Found position file: {filepath}")
            with open(filepath, 'r') as f:
                saved_pos = json.load(f)
            
            if saved_pos:
                print(f"\n⚠️ Bot has {len(saved_pos)} tracked positions:")
                for symbol, pos in saved_pos.items():
                    print(f"  • {symbol}: Entry ${pos.get('entry_price', 0):.2f}")
                
                print("\n🚨 POSITIONS EXIST IN FILE BUT NO CRYPTO IN ACCOUNT!")
                print("   This means crypto was sold manually or withdrawn.")
                print("\n   Clearing position file...")
                
                with open(filepath, 'w') as f:
                    json.dump({}, f)
                print("  ✅ Position file cleared")
            else:
                print(f"  ✅ Position file is empty")
            break
    else:
        print("  ❌ No position file found")
    
    print("\n" + "=" * 80)
    print("✅ NO ACTION NEEDED - No crypto to sell")
    print("=" * 80)
    sys.exit(0)

# Step 2: Sell everything
print(f"\n2️⃣ Found {len(crypto_holdings)} crypto position(s) - SELLING NOW:")
print("-" * 80)

for crypto in crypto_holdings:
    print(f"\n  {crypto['currency']}: {crypto['amount']:.8f}")

print("\n" + "=" * 80)
print("⚠️  EXECUTING MARKET SELLS...")
print("=" * 80)

sold = 0
failed = 0
results = []

for crypto in crypto_holdings:
    symbol = crypto['symbol']
    currency = crypto['currency']
    amount = crypto['amount']
    
    print(f"\n📤 Selling {amount:.8f} {currency}...")
    
    try:
        # Place market sell order using base_size
        order = client.market_order_sell(
            product_id=symbol,
            base_size=str(amount)
        )
        
        # Check response
        if order:
            success = getattr(order, 'success', False)
            order_id = getattr(order, 'order_id', 'N/A')
            
            if success or order_id != 'N/A':
                print(f"  ✅ SOLD {currency} (Order ID: {order_id})")
                sold += 1
                results.append(f"✅ {currency}")
            else:
                error = getattr(order, 'error_response', None)
                failure = getattr(order, 'failure_reason', 'Unknown')
                print(f"  ❌ FAILED: {failure or error}")
                failed += 1
                results.append(f"❌ {currency}: {failure or error}")
        else:
            print(f"  ❌ FAILED: No response from API")
            failed += 1
            results.append(f"❌ {currency}: No response")
            
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        failed += 1
        results.append(f"❌ {currency}: {str(e)}")

# Step 3: Clear bot's position tracking
print("\n" + "=" * 80)
print("3️⃣ Clearing bot's position tracking file...")
print("-" * 80)

positions_files = [
    "/usr/src/app/data/open_positions.json",
    "./data/open_positions.json"
]

for filepath in positions_files:
    if os.path.exists(filepath):
        with open(filepath, 'w') as f:
            json.dump({}, f)
        print(f"  ✅ Cleared: {filepath}")

# Summary
print("\n" + "=" * 80)
print("📊 FINAL RESULTS")
print("=" * 80)
print(f"\n✅ Successfully sold: {sold}/{len(crypto_holdings)}")
print(f"❌ Failed to sell: {failed}/{len(crypto_holdings)}")

if results:
    print("\nDetailed results:")
    for result in results:
        print(f"  {result}")

if sold > 0:
    print("\n💰 Proceeds should now be in your Coinbase account as USD/USDC")
    print("   Transfer to Advanced Trade: https://www.coinbase.com/advanced-portfolio")

if failed > 0:
    print("\n⚠️ Some sells failed - check Coinbase manually:")
    print("   https://www.coinbase.com")

print("\n" + "=" * 80)
