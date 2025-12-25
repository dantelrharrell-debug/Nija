#!/usr/bin/env python3
"""
EMERGENCY POSITION CHECK
Checks if you have open crypto positions that bot should be selling
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_integration import BrokerIntegration

def main():
    print("=" * 70)
    print("🚨 EMERGENCY POSITION CHECK")
    print("=" * 70)
    
    broker = BrokerIntegration()
    
    # Get all positions
    print("\n🔍 Fetching all crypto positions from Coinbase...")
    positions = broker.get_open_positions()
    
    print(f"\n📊 Total positions found: {len(positions)}")
    
    if positions:
        print("\n🔥 ACTIVE POSITIONS DETECTED:")
        print("-" * 70)
        total_value = 0
        for pos in positions:
            symbol = pos.get('symbol', 'UNKNOWN')
            quantity = pos.get('quantity', 0)
            entry = pos.get('entry_price', 0)
            current = pos.get('current_price', 0)
            value = pos.get('current_value', 0)
            pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0
            
            print(f"  • {symbol}")
            print(f"    Quantity: {quantity}")
            print(f"    Entry: ${entry:.4f}")
            print(f"    Current: ${current:.4f}")
            print(f"    Value: ${value:.2f}")
            print(f"    P&L: {pnl_pct:+.2f}%")
            print()
            total_value += value
        
        print(f"💰 Total position value: ${total_value:.2f}")
        print("\n⚠️  CRITICAL: Bot should be managing these positions!")
    else:
        print("\n✅ No open positions found")
    
    # Check balances
    print("\n" + "=" * 70)
    print("💵 ACCOUNT BALANCES:")
    print("=" * 70)
    balance = broker.get_account_balance()
    print(f"Advanced Trade USD/USDC: ${balance.get('trading_balance', 0):.2f}")
    print(f"Consumer USDC: ${balance.get('consumer_usdc', 0):.2f}")
    print(f"Consumer USD: ${balance.get('consumer_usd', 0):.2f}")
    
    crypto = balance.get('crypto', {})
    if crypto:
        print("\nCrypto balances:")
        for coin, amount in crypto.items():
            print(f"  • {coin}: {amount}")
    
    # Check saved positions file
    print("\n" + "=" * 70)
    print("📁 SAVED POSITIONS FILE CHECK:")
    print("=" * 70)
    positions_file = "/usr/src/app/data/open_positions.json"
    local_file = "./data/open_positions.json"
    
    for filepath in [positions_file, local_file]:
        if os.path.exists(filepath):
            print(f"\n✅ Found: {filepath}")
            import json
            with open(filepath, 'r') as f:
                saved = json.load(f)
                print(f"Saved positions: {len(saved)}")
                if saved:
                    for symbol, data in saved.items():
                        print(f"  • {symbol}: ${data.get('entry_price', 0):.2f}")
            break
    else:
        print("\n❌ No saved positions file found")
    
    print("\n" + "=" * 70)
    print("🎯 DIAGNOSIS:")
    print("=" * 70)
    
    if positions:
        print("❌ You have ACTIVE POSITIONS that bot is NOT selling!")
        print("   Problem: Bot is not detecting/managing these positions")
        print("   Action needed: Fix position detection logic")
    elif crypto:
        print("⚠️  You have crypto but no tracked positions")
        print("   These may be in Consumer wallet (not manageable via API)")
    else:
        print("✅ No positions to manage")
    
    print("=" * 70)

if __name__ == "__main__":
    main()
