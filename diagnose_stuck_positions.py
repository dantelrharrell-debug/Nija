#!/usr/bin/env python3
"""
Diagnose why positions are stuck and not closing
Checks current prices vs. stop/TP levels and logs
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
    print("🔍 NIJA STUCK POSITION DIAGNOSTIC")
    print("="*80)
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
    
    # Load positions
    positions_file = 'data/open_positions.json'
    if not os.path.exists(positions_file):
        print(f"❌ No positions file found at {positions_file}")
        return
    
    with open(positions_file, 'r') as f:
        data = json.load(f)
    
    positions = data.get('positions', {})
    if not positions:
        print("✅ No open positions")
        return
    
    print(f"📊 Found {len(positions)} open positions\n")
    
    # Connect to Coinbase
    print("🔌 Connecting to Coinbase...")
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return
    print("✅ Connected\n")
    
    should_exit = []
    
    for symbol, pos in positions.items():
        print("─" * 80)
        print(f"Symbol: {symbol}")
        
        entry_price = pos.get('entry_price', 0)
        stop_loss = pos.get('stop_loss', 0)
        take_profit = pos.get('take_profit', 0)
        trailing_stop = pos.get('trailing_stop', stop_loss)
        side = pos.get('side', 'BUY')
        size_usd = pos.get('size_usd', 0)
        entry_time = pos.get('entry_time', 'unknown')
        
        # Get current price
        try:
            product = broker.client.get_product(symbol)
            current_price = float(product.price)
        except Exception as e:
            print(f"❌ Failed to get price: {e}")
            continue
        
        # Calculate P&L
        if side == 'BUY':
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            unrealized_pnl = (current_price - entry_price) * (size_usd / entry_price)
        else:
            pnl_pct = ((entry_price - current_price) / entry_price) * 100
            unrealized_pnl = (entry_price - current_price) * (size_usd / entry_price)
        
        print(f"  Side: {side}")
        print(f"  Entry: ${entry_price:.4f} @ {entry_time}")
        print(f"  Current: ${current_price:.4f}")
        print(f"  P&L: {pnl_pct:+.2f}% (${unrealized_pnl:+.2f})")
        print(f"  Size: ${size_usd:.2f}")
        print(f"\n  Levels:")
        print(f"    Stop Loss:     ${stop_loss:.4f}")
        print(f"    Trailing Stop: ${trailing_stop:.4f}")
        print(f"    Take Profit:   ${take_profit:.4f}")
        
        # Check exit conditions
        exit_reason = None
        
        if side == 'BUY':
            if current_price <= stop_loss:
                exit_reason = f"🔴 STOP LOSS HIT (${current_price:.4f} <= ${stop_loss:.4f})"
            elif current_price <= trailing_stop:
                exit_reason = f"🟠 TRAILING STOP HIT (${current_price:.4f} <= ${trailing_stop:.4f})"
            elif current_price >= take_profit:
                exit_reason = f"🟢 TAKE PROFIT HIT (${current_price:.4f} >= ${take_profit:.4f})"
        else:  # SELL
            if current_price >= stop_loss:
                exit_reason = f"🔴 STOP LOSS HIT (${current_price:.4f} >= ${stop_loss:.4f})"
            elif current_price >= trailing_stop:
                exit_reason = f"🟠 TRAILING STOP HIT (${current_price:.4f} >= ${trailing_stop:.4f})"
            elif current_price <= take_profit:
                exit_reason = f"🟢 TAKE PROFIT HIT (${current_price:.4f} <= ${take_profit:.4f})"
        
        if exit_reason:
            print(f"\n  ⚠️  STATUS: {exit_reason}")
            print(f"  ❌ POSITION SHOULD HAVE CLOSED!")
            should_exit.append({
                'symbol': symbol,
                'reason': exit_reason,
                'pnl_pct': pnl_pct,
                'pnl_usd': unrealized_pnl
            })
        else:
            print(f"\n  ✅ STATUS: Position OK (no exit conditions met)")
        
        print()
    
    print("="*80)
    print("📋 SUMMARY")
    print("="*80)
    
    if should_exit:
        print(f"\n🚨 {len(should_exit)} POSITIONS SHOULD HAVE EXITED:\n")
        total_stuck_pnl = sum(p['pnl_usd'] for p in should_exit)
        
        for pos in should_exit:
            print(f"  • {pos['symbol']}: {pos['reason']}")
            print(f"    P&L: {pos['pnl_pct']:+.2f}% (${pos['pnl_usd']:+.2f})")
            print()
        
        print(f"Total P&L in stuck positions: ${total_stuck_pnl:+.2f}\n")
        
        print("🔍 POSSIBLE CAUSES:")
        print("  1. Exit checks not running frequently enough")
        print("  2. Broker API errors preventing SELL orders")
        print("  3. Precision/size errors causing order rejections")
        print("  4. manage_open_positions() not being called in main loop")
        print("  5. Position file out of sync with actual holdings")
        print("\n📋 CHECK RECENT LOGS:")
        print("  tail -100 nija.log | grep -E 'Exit|SELL|ERROR|precision|INSUFFICIENT'")
        
    else:
        print("\n✅ All positions are within their management zones")
        print("   No exit conditions currently met")
    
    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
