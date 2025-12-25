#!/usr/bin/env python3
"""
Quick balance check to diagnose where funds are located
"""
import os
import sys
sys.path.insert(0, '/workspaces/Nija')

from bot.broker_manager import CoinbaseBroker
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

def main():
    print("\n" + "="*70)
    print("🔍 NIJA BALANCE DIAGNOSTIC")
    print("="*70 + "\n")
    
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return
    
    print("\n✅ Connected to Coinbase API\n")
    
    # Get balances
    balance_info = broker.get_account_balance()
    
    print("\n" + "="*70)
    print("📊 BALANCE RESULTS:")
    print("="*70)
    print(f"Consumer USD (v2 API):        ${balance_info.get('consumer_usd', 0):.2f} [NOT TRADABLE]")
    print(f"Consumer USDC (v2 API):       ${balance_info.get('consumer_usdc', 0):.2f} [NOT TRADABLE]")
    print(f"Advanced Trade USD (v3 API):  ${balance_info.get('usd', 0):.2f} [TRADABLE ✅]")
    print(f"Advanced Trade USDC (v3 API): ${balance_info.get('usdc', 0):.2f} [TRADABLE ✅]")
    print()
    print(f"🎯 TRADING BALANCE: ${balance_info.get('trading_balance', 0):.2f}")
    print("="*70)
    
    trading_balance = balance_info.get('trading_balance', 0)
    consumer_total = balance_info.get('consumer_usd', 0) + balance_info.get('consumer_usdc', 0)
    
    if trading_balance >= 5.0:
        print("\n✅ SUCCESS! You have sufficient funds in Advanced Trade.")
        print("   The bot should start trading on the next iteration (within 15 seconds).")
    elif consumer_total > 0:
        print("\n❌ ISSUE: Funds are still in Consumer wallet!")
        print(f"   You have ${consumer_total:.2f} in Consumer but ${trading_balance:.2f} in Advanced Trade")
        print("\n   Possible reasons:")
        print("   1. Transfer hasn't completed yet (wait 30 seconds and re-check)")
        print("   2. You transferred to wrong account type")
        print("   3. Transfer failed - check Coinbase app/website")
        print("\n   ⚠️  Make sure you transferred to 'Advanced Trade' not just moved between Consumer wallets")
    else:
        print("\n❌ ISSUE: No funds detected in either location!")
        print("   Check your Coinbase account balance on the website")
    
    print()

if __name__ == "__main__":
    main()
