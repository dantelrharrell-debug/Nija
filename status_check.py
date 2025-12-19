#!/usr/bin/env python3
"""
Quick status check - what's the current state?
"""
import os

print("\n" + "="*80)
print("📊 CURRENT STATUS CHECK")
print("="*80)

# Check if emergency stop is active
if os.path.exists('EMERGENCY_STOP'):
    print("\n✅ EMERGENCY_STOP file exists - Bot is DISABLED")
else:
    print("\n⚠️  EMERGENCY_STOP file NOT found - Bot could still run")

# Check if bot settings were updated
if os.path.exists('bot/trading_strategy.py'):
    with open('bot/trading_strategy.py', 'r') as f:
        content = f.read()
    
    if 'coinbase_minimum_with_fees = 10.00' in content:
        print("✅ Bot settings UPDATED - Minimum position: $10")
    elif 'coinbase_minimum_with_fees = 5.50' in content:
        print("⚠️  Bot settings NOT updated - Still accepting $5 positions")
    
    if 'TRADE_COOLDOWN_SECONDS = 30' in content:
        print("✅ Trade cooldown ACTIVE - 30 seconds between trades")
    else:
        print("⚠️  No trade cooldown - Rapid-fire trades possible")

print("\n" + "="*80)
print("📋 WHAT YOU SHOULD DO NOW")
print("="*80)

print("\n1. CHECK YOUR HOLDINGS:")
print("   python3 show_holdings.py")
print("   → See what crypto you own (~$59 value)")

print("\n2. DECIDE ON YOUR CRYPTO:")
print("   Option A: Sell all → python3 sell_all_positions.py")
print("   Option B: Hold and hope prices recover")

print("\n3. STOP THE BOT (if not done):")
print("   python3 emergency_stop.py")
print("   → Type 'yes' to confirm")

print("\n4. WHEN READY TO TRADE AGAIN:")
print("   • Deposit $50-100 (NOT $5)")
print("   • Delete EMERGENCY_STOP file")
print("   • Restart bot")
print("   • Monitor first 10 trades")

print("\n" + "="*80)
print("💡 REMEMBER: $5 deposits = guaranteed losses (fees too high)")
print("="*80 + "\n")
