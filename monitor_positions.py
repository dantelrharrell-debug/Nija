#!/usr/bin/env python3
"""
Monitor active position management and track exits
Shows real-time status of 9 positions being managed by NIJA
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

def get_positions():
    """Load current tracked positions"""
    pos_file = Path("data/open_positions.json")
    if not pos_file.exists():
        return {}
    
    try:
        with open(pos_file, 'r') as f:
            data = json.load(f)
        return data.get('positions', {})
    except:
        return {}

def get_log_tail():
    """Get last lines from bot log"""
    log_file = Path("nija.log")
    if not log_file.exists():
        return []
    
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
        return lines[-50:]  # Last 50 lines
    except:
        return []

def main():
    print("\n" + "="*100)
    print("📊 NIJA POSITION MANAGEMENT MONITOR")
    print("="*100)
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Check positions
    positions = get_positions()
    
    if not positions:
        print("❌ No positions tracked yet")
        print("   Waiting for bot to load positions...\n")
    else:
        print(f"✅ Tracking {len(positions)} positions:\n")
        
        for symbol, pos in sorted(positions.items()):
            side = pos.get('side', 'BUY')
            entry = pos.get('entry_price', 0)
            size = pos.get('size', 0)
            sl = pos.get('stop_loss', 0)
            tp = pos.get('take_profit', 0)
            status = pos.get('status', 'OPEN')
            
            status_emoji = "🟢" if status == "OPEN" else "⚠️ "
            
            print(f"{status_emoji} {symbol}")
            print(f"   Entry: ${entry:.2f} × {size:.8f}")
            print(f"   Stops: SL=${sl:.2f} | TP=${tp:.2f}")
            print(f"   Status: {status}")
            print()
    
    # Show recent log activity
    print("="*100)
    print("📋 RECENT BOT ACTIVITY (Last exits/trades):")
    print("="*100 + "\n")
    
    log_lines = get_log_tail()
    
    # Filter for important lines
    important_keywords = [
        'Exit', 'CLOSE', 'SELL', 'Stop loss', 'Take profit',
        'Trailing stop', 'Managing', 'open position', 'closed',
        '✅', '🔄', '🎯'
    ]
    
    exit_count = 0
    for line in log_lines:
        if any(kw in line for kw in important_keywords):
            print(line.strip())
            exit_count += 1
            if exit_count >= 20:
                break
    
    if exit_count == 0:
        print("(No recent exits logged)")
    
    print("\n" + "="*100)
    print("💡 WHAT TO EXPECT:")
    print("="*100)
    print("""
When bot runs:
  1. Loads all 9 positions from data/open_positions.json
  2. Every 2.5 minutes, checks current prices
  3. Compares prices to stop loss and take profit levels
  4. When condition met: CLOSES position and logs exit
  5. Freed capital becomes available for new trades

Monitor the log with:
  tail -f nija.log | grep -E 'Exit|CLOSE|profit|loss'
    """)
    print("="*100 + "\n")

if __name__ == '__main__':
    while True:
        main()
        print("\nRefreshing in 5 seconds... (Ctrl+C to stop)\n")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n✅ Monitor stopped\n")
            break
