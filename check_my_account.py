#!/usr/bin/env python3
"""Quick script to check Coinbase account balances and find funded accounts"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker

def main():
    print("\n" + "="*80)
    print("CHECKING YOUR COINBASE ACCOUNTS")
    print("="*80 + "\n")
    
    # Create and connect broker
    broker = CoinbaseBroker()
    
    print("🔌 Connecting to Coinbase...")
    if not broker.connect():
        print("❌ Connection failed")
        return 1
    
    print("✅ Connected!\n")
    
    # Get balance
    print("💰 Checking account balance...\n")
    balance = broker.get_account_balance()
    
    print("="*80)
    print("BALANCE SUMMARY")
    print("="*80)
    print(f"USD:              ${balance.get('usd', 0):.2f}")
    print(f"USDC:             ${balance.get('usdc', 0):.2f}")
    print(f"Trading Balance:  ${balance.get('trading_balance', 0):.2f}")
    
    # Show crypto holdings
    crypto = balance.get('crypto', {})
    if crypto:
        print(f"\nCrypto Holdings:")
        for currency, amount in crypto.items():
            print(f"  {currency}: {amount:.8f}")
    
    print("\n" + "="*80)
    
    # Check if tradable
    trading_balance = balance.get('trading_balance', 0)
    if trading_balance >= 5.0:
        print("✅ You have sufficient funds for trading!")
        print(f"   Available: ${trading_balance:.2f}")
    else:
        print("⚠️  INSUFFICIENT TRADING BALANCE")
        print(f"   Available: ${trading_balance:.2f}")
        print(f"   Needed:    $5.00 minimum")
        print("\n💡 Your funds might be in a Consumer account")
        print("   Check the logs above for '⚠️ Skipping' messages")
        print("\n   TO FIX:")
        print("   1. Go to: https://www.coinbase.com/advanced-portfolio")
        print("   2. Transfer funds to Advanced Trade portfolio")
    
    print("="*80 + "\n")
    
    # Get detailed inventory
    print("📋 DETAILED ACCOUNT INVENTORY:")
    print("="*80)
    inventory = broker.get_usd_usdc_inventory()
    for line in inventory:
        print(line)
    print("="*80 + "\n")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
