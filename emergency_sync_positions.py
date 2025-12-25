#!/usr/bin/env python3
"""
EMERGENCY: Force-sync Coinbase holdings into position tracking
This fixes the critical bug where bot has 0 positions but Coinbase has 8
"""

import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker

load_dotenv()

def main():
    print("\n" + "="*80)
    print("🚨 EMERGENCY POSITION SYNC")
    print("="*80)
    print("Problem: Bot thinks it has 0 positions, but Coinbase shows 8")
    print("Solution: Force-sync actual holdings into position tracker\n")
    
    # Connect to Coinbase
    print("🔌 Connecting to Coinbase...")
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return 1
    print("✅ Connected\n")
    
    # Get actual holdings
    print("📊 Fetching actual Coinbase holdings...")
    try:
        accounts = broker.client.get_accounts()
        crypto_holdings = {}
        
        for account in accounts['accounts']:
            currency = account.get('currency')
            available_balance = account.get('available_balance', {})
            value = float(available_balance.get('value', 0))
            
            if currency and currency not in ['USD', 'USDC'] and value > 0:
                crypto_holdings[currency] = value
        
        print(f"✅ Found {len(crypto_holdings)} crypto positions:\n")
        
        for currency, amount in crypto_holdings.items():
            print(f"   {currency}: {amount}")
        
    except Exception as e:
        print(f"❌ Failed to get holdings: {e}")
        return 1
    
    if not crypto_holdings:
        print("\n✅ No crypto holdings found - nothing to sync")
        return 0
    
    # Build position records
    print(f"\n📝 Creating position records...")
    positions = {}
    total_value_usd = 0
    
    for currency, amount in crypto_holdings.items():
        symbol = f"{currency}-USD"
        
        try:
            # Get current price
            product = broker.client.get_product(symbol)
            current_price = float(product.price)
            value_usd = amount * current_price
            total_value_usd += value_usd
            
            # Calculate simple stop/TP levels (3% stop, 5% TP)
            stop_loss = current_price * 0.97
            take_profit = current_price * 1.05
            
            positions[symbol] = {
                'symbol': symbol,
                'side': 'BUY',
                'entry_price': current_price,  # Use current as entry (we don't know real entry)
                'current_price': current_price,
                'size_usd': value_usd,
                'crypto_quantity': amount,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'trailing_stop': stop_loss,
                'highest_price': current_price,
                'tp_stepped': False,
                'entry_time': datetime.utcnow().isoformat(),
                'timestamp': datetime.utcnow().isoformat(),
                'synced_from_coinbase': True,
                'note': 'Emergency sync - positions were orphaned'
            }
            
            print(f"   ✅ {symbol}: ${value_usd:.2f} ({amount} {currency} @ ${current_price:.4f})")
            
        except Exception as e:
            print(f"   ⚠️  {symbol}: Failed to get price ({e})")
            continue
    
    print(f"\n💰 Total position value: ${total_value_usd:,.2f}")
    print(f"📊 Positions created: {len(positions)}")
    
    # Save to file
    positions_file = 'data/open_positions.json'
    os.makedirs('data', exist_ok=True)
    
    position_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'positions': positions,
        'count': len(positions)
    }
    
    print(f"\n💾 Saving positions to {positions_file}...")
    with open(positions_file, 'w') as f:
        json.dump(position_data, f, indent=2)
    
    print("✅ Positions file updated!")
    
    print("\n" + "="*80)
    print("✅ SYNC COMPLETE")
    print("="*80)
    print(f"\nSynced {len(positions)} positions worth ${total_value_usd:,.2f}")
    print("\n⚠️  IMPORTANT: You MUST restart the bot for changes to take effect:")
    print("   1. Stop the current bot (Ctrl+C or kill process)")
    print("   2. Restart: bash start.sh")
    print("\n📊 After restart, bot will:")
    print("   - Load all 8 positions from file")
    print("   - Start monitoring for stop loss / take profit")
    print("   - Close positions when exit conditions are met")
    print("   - Free up capital for new trades")
    print("\n" + "="*80 + "\n")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
