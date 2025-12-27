#!/usr/bin/env python3
"""
NIJA Position Tracker Status Check
Shows current tracked positions with entry prices and profit/loss
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from position_tracker import PositionTracker
from broker_manager import CoinbaseBroker
from trading_strategy import PROFIT_TARGETS, STOP_LOSS_THRESHOLD, STOP_LOSS_WARNING

def main():
    print("="*70)
    print("NIJA POSITION TRACKER STATUS")
    print("="*70)
    print()
    
    # Initialize position tracker
    tracker = PositionTracker(storage_file="positions.json")
    
    tracked_positions = tracker.get_all_positions()
    
    if not tracked_positions:
        print("✅ No tracked positions (clean slate)")
        print()
        return
    
    print(f"📊 {len(tracked_positions)} tracked position(s):")
    print()
    
    # Initialize broker to get current prices
    broker = CoinbaseBroker()
    if broker.connect():
        print("Connected to Coinbase API for current prices...")
        print()
    
    total_pnl = 0.0
    
    for symbol in tracked_positions:
        position = tracker.get_position(symbol)
        
        if position:
            entry_price = position['entry_price']
            quantity = position['quantity']
            size_usd = position['size_usd']
            entry_time = position['first_entry_time']
            
            print(f"Symbol: {symbol}")
            print(f"  Entry Price:  ${entry_price:.2f}")
            print(f"  Quantity:     {quantity:.8f}")
            print(f"  Entry Value:  ${size_usd:.2f}")
            print(f"  Entry Time:   {entry_time}")
            
            # Get current P&L
            if broker.connected:
                try:
                    current_price = broker.get_current_price(symbol)
                    pnl_data = tracker.calculate_pnl(symbol, current_price)
                    
                    if pnl_data:
                        pnl_dollars = pnl_data['pnl_dollars']
                        pnl_percent = pnl_data['pnl_percent']
                        current_value = pnl_data['current_value']
                        
                        status_emoji = "🟢" if pnl_dollars > 0 else "🔴" if pnl_dollars < 0 else "⚪"
                        
                        print(f"  Current Price: ${current_price:.2f}")
                        print(f"  Current Value: ${current_value:.2f}")
                        print(f"  P&L: {status_emoji} ${pnl_dollars:+.2f} ({pnl_percent:+.2f}%)")
                        
                        total_pnl += pnl_dollars
                        
                        # Show profit target status using shared configuration
                        for target_pct, reason in PROFIT_TARGETS:
                            if pnl_percent >= target_pct:
                                print(f"  🎯 {reason.upper()} HIT - SHOULD SELL!")
                                break
                        else:
                            # No profit target hit, check stop loss
                            if pnl_percent <= STOP_LOSS_THRESHOLD:
                                print(f"  🛑 STOP LOSS {STOP_LOSS_THRESHOLD}% HIT - SHOULD SELL!")
                            elif pnl_percent <= STOP_LOSS_WARNING:
                                print(f"  ⚠️ Approaching stop loss ({STOP_LOSS_WARNING}%)")
                except Exception as e:
                    print(f"  ⚠️ Could not get current price: {e}")
            
            print()
    
    if broker.connected and total_pnl != 0:
        print("="*70)
        print(f"Total P&L: ${total_pnl:+.2f}")
        print("="*70)
    print()

if __name__ == "__main__":
    main()
