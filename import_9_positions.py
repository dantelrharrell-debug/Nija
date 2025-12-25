#!/usr/bin/env python3
"""
CRITICAL FIX: Import your 9 existing positions into NIJA's tracking system
This allows the bot to manage them with stops/takes/trails

Without this, the bot ignores your existing positions because it doesn't know about them
"""

import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker
from nija_apex_strategy_v71 import NIJAApexStrategyV71

def main():
    print("\n" + "="*100)
    print("🔥 CRITICAL FIX: IMPORTING YOUR 9 POSITIONS INTO NIJA TRACKING")
    print("="*100 + "\n")
    
    # Initialize broker
    broker = CoinbaseBroker()
    strategy = NIJAApexStrategyV71()
    
    # Your 9 current holdings (from Coinbase screenshot)
    holdings = {
        'BTC-USD': {'amount': 0.000225, 'entry': 19.73},
        'ETH-USD': {'amount': 0.008643, 'entry': 25.61},
        'DOGE-USD': {'amount': 115.9, 'entry': 14.95},
        'SOL-USD': {'amount': 0.088353, 'entry': 10.96},
        'XRP-USD': {'amount': 5.428797, 'entry': 10.31},
        'LTC-USD': {'amount': 0.128819, 'entry': 9.75},
        'HBAR-USD': {'amount': 88, 'entry': 9.72},
        'BCH-USD': {'amount': 0.016528, 'entry': 9.59},
        'ICP-USD': {'amount': 3.0109, 'entry': 9.23},
    }
    
    # Open position tracking structure
    open_positions = {}
    
    print("📥 IMPORTING POSITIONS INTO NIJA TRACKING:\n")
    print("-"*100)
    
    for symbol, info in holdings.items():
        try:
            # Get current price
            ticker = broker.get_ticker(symbol)
            current_price = float(ticker['price'])
            entry_price = info['entry']
            amount = info['amount']
            entry_value = entry_price * amount
            current_value = current_price * amount
            pnl = current_value - entry_value
            pnl_pct = (pnl / entry_value) * 100 if entry_value > 0 else 0
            
            # Create position tracking entry
            position = {
                'symbol': symbol,
                'side': 'BUY',
                'entry_price': entry_price,
                'current_price': current_price,
                'size': amount,
                'size_usd': entry_value,
                'crypto_quantity': amount,
                'entry_time': datetime.now().isoformat(),
                'stop_loss': entry_price * 0.98,  # 2% below entry
                'take_profit': entry_price * 1.05,  # 5% above entry
                'trailing_stop': entry_price * 0.98,  # Start at same as stop loss
                'trailing_lock_ratio': 0.8,  # Lock in 80% of gains
                'highest_price': current_price,
                'status': 'OPEN',
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'tp_stepped': False
            }
            
            open_positions[symbol] = position
            
            # Print summary
            status_emoji = "✅" if pnl >= 0 else "⚠️"
            print(f"{status_emoji} {symbol}")
            print(f"   Entry: ${entry_price:.2f} × {amount:.8f}")
            print(f"   Current: ${current_price:.2f} | Value: ${current_value:.2f}")
            print(f"   P&L: {pnl_pct:+.2f}% (${pnl:+.2f})")
            print(f"   Stops: SL=${position['stop_loss']:.2f} | TP=${position['take_profit']:.2f}")
            print()
            
        except Exception as e:
            print(f"❌ {symbol}: Error - {e}\n")
            continue
    
    # Save to file where bot expects them
    position_file = os.path.join(os.path.dirname(__file__), 'data', 'open_positions.json')
    os.makedirs(os.path.dirname(position_file), exist_ok=True)
    
    tracking_data = {
        'timestamp': datetime.now().isoformat(),
        'positions': open_positions,
        'count': len(open_positions),
        'imported_at': datetime.now().isoformat(),
        'note': 'Imported existing positions into NIJA tracking system'
    }
    
    with open(position_file, 'w') as f:
        json.dump(tracking_data, f, indent=2)
    
    print("-"*100)
    print("\n✅ POSITIONS IMPORTED\n")
    print(f"📁 File: {position_file}")
    print(f"📊 Positions tracked: {len(open_positions)}\n")
    
    # Summary
    total_entry = sum(pos['size_usd'] for pos in open_positions.values())
    total_current = sum(pos['size_usd'] * (pos['current_price'] / pos['entry_price']) for pos in open_positions.values())
    total_pnl = total_current - total_entry
    
    print(f"💰 PORTFOLIO SUMMARY:")
    print(f"   Entry Value: ${total_entry:.2f}")
    print(f"   Current Value: ${total_current:.2f}")
    print(f"   P&L: {(total_pnl/total_entry)*100:+.2f}% (${total_pnl:+.2f})\n")
    
    if total_pnl >= 0:
        print(f"✅ Portfolio is IN PROFIT")
        print(f"   → Bot will now PROTECT gains with take profits\n")
    else:
        print(f"⚠️  Portfolio is IN LOSS")
        print(f"   → Bot will now PROTECT downside with stop losses\n")
    
    print("="*100)
    print("\n🎯 WHAT HAPPENS NEXT:\n")
    print("1. ✅ Bot now knows about all 9 positions")
    print("2. ✅ manage_open_positions() will check them on every cycle")
    print("3. ✅ Stops will execute if any position drops 2% from entry")
    print("4. ✅ Takes will execute if any position rises 5% from entry")
    print("5. ✅ Trailing stops lock in gains (80% protection)")
    print("6. ✅ Positions that hit stops/takes are CLOSED and removed")
    print("7. ✅ Freed capital available for new profitable trades\n")
    print("="*100 + "\n")

if __name__ == '__main__':
    main()
