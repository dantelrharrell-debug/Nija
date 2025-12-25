#!/usr/bin/env python3
"""
Add existing crypto positions to NIJA's tracking file
so the bot can manage stops/takes for them
"""
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔧 IMPORT EXISTING POSITIONS INTO NIJA TRACKING")
print("="*80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Initialize Coinbase
client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get current crypto holdings
print("📊 Scanning for crypto positions...\n")
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

crypto_positions = []
for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    
    if not curr or not avail_obj:
        continue
    
    bal = float(getattr(avail_obj, 'value', '0'))
    
    if curr not in ['USD', 'USDC', 'USDT'] and bal > 0:
        crypto_positions.append({
            'currency': curr,
            'balance': bal
        })

if not crypto_positions:
    print("❌ No crypto positions found")
    print("   Either you already sold everything, or they're in a different account\n")
    sys.exit(0)

print(f"✅ Found {len(crypto_positions)} crypto position(s):\n")

# Get current prices and create tracking entries
tracked_positions = {}

for pos in crypto_positions:
    curr = pos['currency']
    bal = pos['balance']
    symbol = f"{curr}-USD"
    
    try:
        # Get current price
        product = client.get_product(symbol)
        price = float(getattr(product, 'price', 0))
        value = bal * price
        
        print(f"   {curr:8s}: {bal:.8f} @ ${price:.4f} = ${value:.2f}")
        
        # Create tracking entry with defensive stops
        # Since we don't know actual entry price, use current price
        # and set wide stops to avoid premature exits
        tracked_positions[symbol] = {
            'symbol': symbol,
            'entry_price': price,
            'entry_time': datetime.now().isoformat(),
            'size': bal,
            'position_value': value,
            'stop_loss': price * 0.95,  # 5% stop loss from current
            'take_profit': price * 1.10,  # 10% take profit from current
            'trailing_stop_pct': 0.03,  # 3% trailing
            'status': 'IMPORTED',
            'notes': 'Imported from existing holdings - stops set from current price'
        }
        
    except Exception as e:
        print(f"   {curr:8s}: {bal:.8f} @ ERROR - Could not get price")

print(f"\n📝 Prepared {len(tracked_positions)} position(s) for tracking\n")

# Load existing position file
position_file = "data/open_positions.json"
os.makedirs("data", exist_ok=True)

existing_data = {"timestamp": datetime.now().isoformat(), "positions": {}, "count": 0}
if os.path.exists(position_file):
    try:
        with open(position_file, 'r') as f:
            existing_data = json.load(f)
            # Handle old format
            if 'positions' not in existing_data:
                existing_data = {"timestamp": datetime.now().isoformat(), "positions": existing_data, "count": len(existing_data)}
    except:
        pass

# Merge with existing (don't overwrite if already tracked)
for symbol, data in tracked_positions.items():
    if symbol not in existing_data.get('positions', {}):
        existing_data['positions'][symbol] = data

existing_data['count'] = len(existing_data['positions'])
existing_data['timestamp'] = datetime.now().isoformat()

# Save updated tracking file
with open(position_file, 'w') as f:
    json.dump(existing_data, f, indent=2)

print("="*80)
print("✅ POSITIONS IMPORTED TO TRACKING FILE")
print("="*80)
print(f"\nFile: {position_file}")
print(f"Total tracked positions: {existing_data['count']}\n")

print("🎯 WHAT HAPPENS NOW:")
print("="*80)
print("✅ NIJA bot will now monitor these positions")
print("✅ Stop losses will trigger at 5% below current price")
print("✅ Take profits will trigger at 10% above current price")
print("✅ Trailing stops active at 3% from peak")
print()
print("⚠️  NOTE: Stops are set from CURRENT price, not your actual entry")
print("   This is conservative - prevents premature exits")
print("   Bot will manage them from here forward\n")

print("="*80 + "\n")
