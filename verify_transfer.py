#!/usr/bin/env python3
"""
Quick script to verify funds transferred to Advanced Trade
Run this AFTER you transfer funds via Coinbase website
"""
import sys
sys.path.append('/workspaces/Nija/bot')
from broker_manager import CoinbaseBroker

broker = CoinbaseBroker()
balance_info = broker.get_account_balance()

print("\n" + "="*70)
print("💰 TRANSFER VERIFICATION")
print("="*70)
print(f"Advanced Trade USD:  ${balance_info['usd']:.2f}")
print(f"Advanced Trade USDC: ${balance_info['usdc']:.2f}")
print(f"Trading Balance:     ${balance_info['trading_balance']:.2f}")
print("="*70)

if balance_info['trading_balance'] >= 5.0:
    print("✅ SUCCESS! You have sufficient funds to trade!")
    print("   The bot will start executing trades on next scan cycle.")
else:
    print("❌ Still insufficient funds in Advanced Trade")
    print(f"   Consumer USD: ${balance_info['consumer_usd']:.2f}")
    print(f"   Consumer USDC: ${balance_info['consumer_usdc']:.2f}")
    print("\n   Transfer still needed. Go to:")
    print("   https://www.coinbase.com/advanced-portfolio")
print("="*70 + "\n")
