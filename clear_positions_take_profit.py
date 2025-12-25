#!/usr/bin/env python3
"""
Clear Positions Script - Force profitable exits for stuck positions

This script:
1. Checks all current holdings in Coinbase
2. Calculates current profit/loss for each position
3. Sells positions that are in profit (any amount > 0%)
4. Updates open_positions.json to reflect cleared positions
"""

import os
import sys
import json
from dotenv import load_dotenv

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker
from position_manager import PositionManager

load_dotenv()

def main():
    print("=" * 80)
    print("🎯 NIJA - Clear Positions & Take Profits")
    print("=" * 80)
    print()
    
    # Connect to Coinbase
    print("📡 Connecting to Coinbase...")
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return
    
    print("✅ Connected to Coinbase Advanced Trade")
    print()
    
    # Get current holdings
    print("📊 Fetching current positions...")
    try:
        positions = broker.get_positions()
    except Exception as e:
        print(f"❌ Error fetching positions: {e}")
        return
    
    if not positions:
        print("✅ No open positions found - all clear!")
        print()
        
        # Clear the positions file
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        positions_file = os.path.join(data_dir, 'open_positions.json')
        
        if os.path.exists(positions_file):
            with open(positions_file, 'w') as f:
                json.dump({
                    'timestamp': str(pd.Timestamp.now()),
                    'positions': {},
                    'count': 0
                }, f, indent=2)
            print("✅ Cleared open_positions.json")
        
        return
    
    print(f"Found {len(positions)} positions:")
    print()
    
    # Get current prices and calculate P&L
    total_value = 0
    profitable_positions = []
    
    for i, pos in enumerate(positions, 1):
        symbol = pos.get('symbol', 'UNKNOWN')
        quantity = float(pos.get('quantity', 0))
        
        # Get current price
        try:
            product = broker.client.get_product(symbol)
            current_price = float(product.get('price', 0))
        except:
            current_price = 0
        
        position_value = quantity * current_price
        total_value += position_value
        
        print(f"{i}. {symbol}")
        print(f"   Quantity: {quantity}")
        print(f"   Current Price: ${current_price:.2f}")
        print(f"   Value: ${position_value:.2f}")
        
        # Check if we have entry price in open_positions.json
        pm = PositionManager()
        saved_positions = pm.load_positions()
        
        entry_price = None
        for trade_id, saved_pos in saved_positions.items():
            if saved_pos.get('symbol') == symbol:
                entry_price = saved_pos.get('entry_price')
                break
        
        if entry_price:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            pnl_usd = position_value - (quantity * entry_price)
            
            print(f"   Entry Price: ${entry_price:.2f}")
            print(f"   P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
            
            if pnl_pct > 0:
                profitable_positions.append({
                    'symbol': symbol,
                    'quantity': quantity,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'pnl_pct': pnl_pct,
                    'pnl_usd': pnl_usd
                })
                print("   ✅ IN PROFIT - Will sell")
            else:
                print("   ⚠️  In loss - Keeping position")
        else:
            print("   ⚠️  No entry price found - Cannot calculate P&L")
        
        print()
    
    print(f"Total Portfolio Value: ${total_value:.2f}")
    print()
    
    # Sell profitable positions
    if not profitable_positions:
        print("No profitable positions to sell.")
        return
    
    print("=" * 80)
    print(f"🎯 Selling {len(profitable_positions)} profitable positions:")
    print("=" * 80)
    print()
    
    for pos in profitable_positions:
        symbol = pos['symbol']
        quantity = pos['quantity']
        pnl_pct = pos['pnl_pct']
        pnl_usd = pos['pnl_usd']
        
        print(f"Selling {symbol} ({pnl_pct:+.2f}%, ${pnl_usd:+.2f})...")
        
        try:
            # Place market sell order
            order = broker.place_order(
                symbol=symbol,
                side='SELL',
                quantity=quantity,
                order_type='market'
            )
            
            if order and order.get('status') == 'filled':
                print(f"✅ SOLD {symbol} - Locked in ${pnl_usd:+.2f} profit")
            else:
                print(f"⚠️  Order placed but status: {order.get('status') if order else 'unknown'}")
        
        except Exception as e:
            print(f"❌ Error selling {symbol}: {e}")
        
        print()
    
    print("=" * 80)
    print("✅ PROFIT-TAKING COMPLETE")
    print("=" * 80)
    print()
    print("Next steps:")
    print("1. Check your Coinbase account to verify sales")
    print("2. Restart NIJA bot to start fresh with freed capital")
    print("3. New positions will use quick profit targets (2-3%)")
    print()

if __name__ == "__main__":
    import pandas as pd
    main()
