#!/usr/bin/env python3
"""
Check ACTUAL Coinbase balance across all accounts
Shows where funds are located (Consumer vs Advanced Trade)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker

def main():
    print("=" * 80)
    print("COINBASE BALANCE CHECK - ALL ACCOUNTS")
    print("=" * 80)
    print()
    
    broker = CoinbaseBroker()
    
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        print("   Check API credentials in Railway environment variables")
        return
    
    print("✅ Connected to Coinbase")
    print()
    
    # Get balance with full diagnostics
    balance_data = broker.get_account_balance()
    
    print()
    print("=" * 80)
    print("BALANCE SUMMARY")
    print("=" * 80)
    print()
    print(f"Advanced Trade USD:  ${balance_data.get('usd', 0):,.2f}")
    print(f"Advanced Trade USDC: ${balance_data.get('usdc', 0):,.2f}")
    print(f"Trading Balance:     ${balance_data.get('trading_balance', 0):,.2f} ✅ (Bot can use this)")
    print()
    print(f"Consumer USD:        ${balance_data.get('consumer_usd', 0):,.2f}")
    print(f"Consumer USDC:       ${balance_data.get('consumer_usdc', 0):,.2f}")
    print()
    
    crypto = balance_data.get('crypto', {})
    if crypto:
        print("Crypto Holdings:")
        for currency, amount in crypto.items():
            print(f"  {currency}: {amount:.8f}")
    else:
        print("Crypto Holdings: None")
    
    print()
    print("=" * 80)
    print("DIAGNOSIS")
    print("=" * 80)
    print()
    
    trading_balance = balance_data.get('trading_balance', 0)
    consumer_total = balance_data.get('consumer_usd', 0) + balance_data.get('consumer_usdc', 0)
    
    if trading_balance > 10:
        print("✅ GOOD: Sufficient trading balance")
        print(f"   Bot can trade with ${trading_balance:,.2f}")
    elif trading_balance > 0:
        print("⚠️  WARNING: Low trading balance")
        print(f"   Balance: ${trading_balance:,.2f}")
        print("   Recommended: Deposit $50-100 for better position sizing")
    else:
        print("❌ CRITICAL: No trading balance")
        print("   Bot cannot trade with $0")
        print()
        
        if consumer_total > 0:
            print("💡 FUNDS FOUND IN CONSUMER WALLET:")
            print(f"   Consumer has ${consumer_total:,.2f}")
            print()
            print("   TO FIX:")
            print("   1. Go to: https://www.coinbase.com/advanced-portfolio")
            print("   2. Click 'Deposit' → 'From Coinbase'")
            print(f"   3. Transfer ${consumer_total:,.2f} to Advanced Trade")
            print("   4. Instant transfer, no fees")
            print("   5. Bot will auto-detect and resume trading")
        else:
            print("💡 NO FUNDS FOUND ANYWHERE:")
            print("   Need to deposit funds to Coinbase")
            print()
            print("   RECOMMENDED:")
            print("   • Deposit $100-200 USD or USDC")
            print("   • To: Advanced Trade portfolio")
            print("   • Via: https://www.coinbase.com/advanced-portfolio")
    
    print()
    print("=" * 80)

if __name__ == "__main__":
    main()
