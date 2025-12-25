#!/usr/bin/env python3
"""
Help locate your $26.30 and transfer it to Advanced Trade
"""
import sys
sys.path.append('/workspaces/Nija/bot')
from broker_manager import CoinbaseBroker

print("\n" + "="*70)
print("🔍 LOCATING YOUR $26.30")
print("="*70)

broker = CoinbaseBroker()
balance_info = broker.get_account_balance()

print("\n📊 CURRENT BALANCE BREAKDOWN:")
print(f"   Consumer/Primary USD:  ${balance_info['consumer_usd']:.2f}")
print(f"   Consumer/Primary USDC: ${balance_info['consumer_usdc']:.2f}")
print(f"   Advanced Trade USD:    ${balance_info['usd']:.2f}")
print(f"   Advanced Trade USDC:   ${balance_info['usdc']:.2f}")

consumer_total = balance_info['consumer_usd'] + balance_info['consumer_usdc']
advanced_total = balance_info['trading_balance']

print("\n" + "="*70)
print("💡 WHAT YOU NEED TO KNOW:")
print("="*70)
print(f"✅ Your $26.30 is likely in 'Primary' (Consumer) wallet")
print(f"✅ Current Consumer total: ${consumer_total:.2f}")
print(f"❌ Advanced Trade total: ${advanced_total:.2f}")
print(f"❌ Bot can ONLY trade with Advanced Trade funds")

print("\n" + "="*70)
print("🔧 HOW TO TRANSFER - STEP BY STEP:")
print("="*70)
print("1. Open browser to: https://www.coinbase.com/advanced-portfolio")
print("2. You should see 'Advanced Trade Portfolio' page")
print("3. Look for 'Deposit' or 'Transfer' button")
print("4. Select 'From Coinbase' (NOT from bank)")
print("5. Choose USD or USDC")
print(f"6. Enter amount: ${consumer_total:.2f} (all of it)")
print("7. Confirm transfer (instant, no fees)")
print("8. Wait 5 seconds, then run: python3 verify_transfer.py")

print("\n" + "="*70)
print("🚨 IMPORTANT:")
print("="*70)
print("• 'Primary' = 'Consumer' = 'Retail' wallet (same thing)")
print("• These names all mean the SAME wallet that API can't use")
print("• You MUST move to 'Advanced Trade' for bot to trade")
print("• Transfer is instant and free")
print("="*70 + "\n")

if advanced_total >= 5.0:
    print("✅ You already have funds in Advanced Trade!")
    print("   Bot should be trading now.\n")
else:
    print("⏳ Waiting for you to complete the transfer...")
    print("   Run verify_transfer.py after transferring\n")
