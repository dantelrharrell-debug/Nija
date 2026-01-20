#!/usr/bin/env python3
"""
Check Coinbase Positions - Diagnostic Script
============================================

This script checks what positions currently exist in Coinbase
and displays their current P&L status.

Usage:
    python3 check_coinbase_positions.py
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / "bot"))

from broker_manager import CoinbaseBroker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("check_positions")


def main():
    """Check current Coinbase positions and their P&L."""
    print("=" * 80)
    print("📊 COINBASE POSITION CHECK")
    print("=" * 80)
    print()
    
    # Connect to Coinbase
    print("Connecting to Coinbase...")
    broker = CoinbaseBroker()
    
    if not broker.connect():
        print("❌ Failed to connect to Coinbase!")
        print("Check your API credentials in .env file")
        return
    
    print("✅ Connected to Coinbase")
    print()
    
    # Get account balance
    try:
        balance = broker.get_usd_balance()
        print(f"💰 Available USD Balance: ${balance:.2f}")
        print()
    except Exception as e:
        print(f"⚠️  Could not get balance: {e}")
        print()
    
    # Get positions
    print("Fetching positions from Coinbase API...")
    positions = broker.get_positions()
    
    if not positions:
        print("✅ No positions found!")
        print("Account is clear - no holdings")
        print()
        return
    
    print(f"Found {len(positions)} position(s)")
    print()
    print("=" * 80)
    
    # Analyze positions
    total_value = 0
    losing_count = 0
    profitable_count = 0
    unknown_count = 0
    
    losing_value = 0
    profitable_value = 0
    
    for i, pos in enumerate(positions, 1):
        symbol = pos.get('symbol', 'UNKNOWN')
        quantity = pos.get('quantity', 0)
        current_price = pos.get('current_price', 0)
        entry_price = pos.get('entry_price', 0)
        value_usd = pos.get('value_usd', 0)
        
        print(f"{i}. {symbol}")
        print(f"   Quantity: {quantity:.8f}")
        print(f"   Current Price: ${current_price:.4f}")
        
        total_value += value_usd
        
        # Calculate P&L if we have entry price
        if entry_price and entry_price > 0:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            pnl_usd = value_usd * (pnl_pct / 100)
            
            print(f"   Entry Price: ${entry_price:.4f}")
            print(f"   Current Value: ${value_usd:.2f}")
            print(f"   P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
            
            if pnl_pct < 0:
                print(f"   Status: 📉 LOSING")
                losing_count += 1
                losing_value += value_usd
            elif pnl_pct > 0:
                print(f"   Status: 📈 PROFITABLE")
                profitable_count += 1
                profitable_value += value_usd
            else:
                print(f"   Status: ⚖️  BREAKEVEN")
                unknown_count += 1
        else:
            print(f"   Current Value: ${value_usd:.2f}")
            print(f"   P&L: ❓ Unknown (no entry price)")
            print(f"   Status: ⚠️  NO ENTRY PRICE TRACKED")
            unknown_count += 1
        
        print()
    
    # Summary
    print("=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    print()
    print(f"Total Positions: {len(positions)}")
    print(f"  📉 Losing: {losing_count} (${losing_value:.2f})")
    print(f"  📈 Profitable: {profitable_count} (${profitable_value:.2f})")
    print(f"  ❓ Unknown: {unknown_count}")
    print()
    print(f"Total Portfolio Value: ${total_value:.2f}")
    print()
    
    # Recommendations
    if losing_count > 0:
        print("⚠️  RECOMMENDATION:")
        print(f"   You have {losing_count} losing position(s) worth ${losing_value:.2f}")
        print()
        print("   To sell ONLY losing positions:")
        print("   python3 sell_losing_positions_now.py")
        print()
        print("   To sell ALL positions:")
        print("   python3 emergency_sell_all_positions.py")
        print()
    elif profitable_count > 0:
        print("✅ GOOD NEWS:")
        print(f"   All {profitable_count} position(s) are profitable!")
        print("   No action needed unless you want to take profits.")
        print()
    else:
        print("ℹ️  All positions status unknown (no entry price tracked)")
        print("   This usually means positions were imported/synced")
        print("   Consider liquidating if you're unsure about them.")
        print()
    
    print("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("Interrupted by user (Ctrl+C)")
        print()
    except Exception as e:
        print()
        print(f"❌ Error: {e}")
        print()
        import traceback
        traceback.print_exc()
