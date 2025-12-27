#!/usr/bin/env python3
"""
Check current positions and identify dust positions
"""

import os
import sys
from coinbase.rest import RESTClient

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def check_dust_positions():
    """Check all current positions and identify dust"""
    
    print("\n" + "="*70)
    print("📊 DUST POSITION ANALYSIS")
    print("="*70 + "\n")
    
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ Missing API credentials")
        return
    
    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        print("📡 Fetching accounts...")
        accounts_response = client.get_accounts()
        accounts = accounts_response.get('accounts', [])
        
        print(f"✅ Found {len(accounts)} accounts\n")
        
        # Track positions by value
        positions = []
        total_usd = 0.0
        
        for account in accounts:
            currency = account.get('currency', '')
            balance_value = account.get('available_balance', {}).get('value', '0')
            balance = float(balance_value)
            
            if balance <= 0:
                continue
            
            if currency == 'USD':
                total_usd = balance
                print(f"💵 USD Balance: ${balance:.2f}\n")
            else:
                # Crypto position - get current value
                symbol = f"{currency}-USD"
                try:
                    product = client.get_product(symbol)
                    price = float(product.price)
                    usd_value = balance * price
                    
                    positions.append({
                        'currency': currency,
                        'symbol': symbol,
                        'balance': balance,
                        'price': price,
                        'usd_value': usd_value
                    })
                except Exception as e:
                    print(f"⚠️ Could not get price for {symbol}: {e}")
                    positions.append({
                        'currency': currency,
                        'symbol': symbol,
                        'balance': balance,
                        'price': 0,
                        'usd_value': 0
                    })
        
        # Sort positions by USD value
        positions.sort(key=lambda x: x['usd_value'], reverse=True)
        
        print(f"{'='*70}")
        print(f"📊 POSITION BREAKDOWN (by value)")
        print(f"{'='*70}\n")
        
        # Define dust thresholds for analysis
        thresholds = {
            'dust_001': 0.001,
            'dust_01': 0.01,
            'dust_05': 0.50,
            'dust_1': 1.00,
            'dust_5': 5.00
        }
        
        winning_positions = []
        dust_positions = []
        
        for i, pos in enumerate(positions, 1):
            status = ""
            if pos['usd_value'] >= 5.00:
                status = "✅ WINNING"
                winning_positions.append(pos)
            elif pos['usd_value'] >= 1.00:
                status = "⚠️ SMALL"
            else:
                status = "🗑️ DUST"
                dust_positions.append(pos)
            
            print(f"{i:2d}. {pos['currency']:8s} ${pos['usd_value']:10.4f}  |  {pos['balance']:12.8f} @ ${pos['price']:10.4f}  {status}")
        
        print(f"\n{'='*70}")
        print(f"📈 SUMMARY")
        print(f"{'='*70}")
        print(f"💵 USD Cash:         ${total_usd:.2f}")
        print(f"💰 Total Positions:  {len(positions)}")
        print(f"✅ Winning (≥$5):    {len(winning_positions)}")
        print(f"🗑️ Dust (<$1):       {len(dust_positions)}")
        print(f"\n{'='*70}")
        print(f"🎯 DUST THRESHOLD ANALYSIS")
        print(f"{'='*70}")
        
        for name, threshold in thresholds.items():
            count_below = sum(1 for p in positions if p['usd_value'] < threshold)
            count_above = len(positions) - count_below
            print(f"  ${threshold:6.3f}: {count_below:2d} below, {count_above:2d} above (would keep {count_above} positions)")
        
        print(f"\n{'='*70}")
        print(f"💡 RECOMMENDATION")
        print(f"{'='*70}")
        
        if len(dust_positions) > 0:
            print(f"\n🗑️ {len(dust_positions)} DUST POSITIONS TO CLOSE:")
            for pos in dust_positions:
                print(f"   - {pos['symbol']}: ${pos['usd_value']:.4f}")
            
            # Calculate positions that count toward the limit (>= $1.00)
            positions_above_threshold = sum(1 for p in positions if p['usd_value'] >= 1.00)
            available_slots = max(0, 8 - positions_above_threshold)
            
            print(f"\n💡 Closing these would free up {len(dust_positions)} position slots")
            print(f"   Currently using {positions_above_threshold} of 8 slots (positions ≥ $1.00)")
            print(f"   After cleanup: {available_slots} slots available for new winning trades")
        else:
            print(f"\n✅ No dust positions found!")
        
        print(f"\n{'='*70}\n")
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    check_dust_positions()
