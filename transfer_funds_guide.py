#!/usr/bin/env python3
"""
Quick Transfer Guide - Move your $57.54 to Advanced Trade
"""
import sys
sys.path.append('/workspaces/Nija/bot')
from broker_manager import CoinbaseBroker

print("\n" + "="*80)
print("💰 FUND TRANSFER REQUIRED")
print("="*80)

broker = CoinbaseBroker()
balance_info = broker.get_account_balance()

consumer_usdc = balance_info.get('consumer_usdc', 0.0)
trading_balance = balance_info.get('trading_balance', 0.0)

print(f"\n📊 CURRENT BALANCE:")
print(f"   Consumer USDC:      ${consumer_usdc:.2f}  {'✅ HAS MONEY' if consumer_usdc > 0 else '❌'}")
print(f"   Advanced Trade:     ${trading_balance:.2f}  {'✅ READY' if trading_balance >= 5 else '❌ INSUFFICIENT'}")

if consumer_usdc > 0 and trading_balance < 5:
    print("\n" + "="*80)
    print("🔧 TRANSFER INSTRUCTIONS (5 MINUTES):")
    print("="*80)
    print("\n1. Open your browser to:")
    print("   https://www.coinbase.com/advanced-portfolio")
    print("\n2. Look for 'Deposit' or 'Transfer' button")
    print("\n3. Select:")
    print("   • Source: 'From Coinbase' (NOT from bank)")
    print("   • Asset: USDC")
    print(f"   • Amount: ${consumer_usdc:.2f}")
    print("\n4. Confirm the transfer")
    print("   • No fees")
    print("   • Instant (< 10 seconds)")
    print("   • Same Coinbase account, different portfolio")
    print("\n5. Verify transfer:")
    print("   Run: python3 verify_transfer.py")
    print("\n6. Restart bot:")
    print("   ./start.sh")
    
    print("\n" + "="*80)
    print("❓ WHY IS THIS NECESSARY?")
    print("="*80)
    print("Coinbase Advanced Trade API can ONLY trade from the Advanced Trade portfolio.")
    print("Consumer wallets are a different system. The SDK can't access them for trading.")
    print("This is a Coinbase architecture limitation, not a bot issue.")
    
elif trading_balance >= 5:
    print("\n✅ YOU'RE READY TO TRADE!")
    print(f"   Available: ${trading_balance:.2f}")
    print("\n🚀 Start the bot:")
    print("   ./start.sh")
else:
    print("\n⚠️  INSUFFICIENT FUNDS")
    print(f"   Total balance: ${consumer_usdc + trading_balance:.2f}")
    print("   Minimum needed: $10.00 (for reliable trading)")
    print("\n   Add funds to your Coinbase account, then run this again.")

print("\n" + "="*80)
