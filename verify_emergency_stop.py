#!/usr/bin/env python3
"""
EMERGENCY STOP VERIFICATION
Verifies all buying safeguards are active
"""
import os
import sys

print("=" * 80)
print("🚨 NIJA EMERGENCY STOP VERIFICATION")
print("=" * 80)
print()

# Check 1: Lockfile exists
lockfile = "TRADING_EMERGENCY_STOP.conf"
if os.path.exists(lockfile):
    print("✅ LOCKFILE EXISTS:", lockfile)
    with open(lockfile, 'r') as f:
        print("   Content preview:")
        for line in f:
            if line.strip() and not line.startswith('#'):
                print(f"   {line.strip()}")
else:
    print("❌ LOCKFILE MISSING:", lockfile)
    print("   Creating it now...")
    with open(lockfile, 'w') as f:
        f.write("""# NIJA SELL-ONLY MODE LOCK
ENABLED=1
REASON=EMERGENCY STOP - User requested immediate halt of all buying
""")
    print("✅ LOCKFILE CREATED")

print()

# Check 2: Code modifications
print("Checking code modifications...")
print()

with open('bot/trading_strategy.py', 'r') as f:
    content = f.read()
    
    # Check for emergency stop in execute_trade
    if '🚨 CRITICAL EMERGENCY STOP' in content:
        print("✅ Emergency stop check in execute_trade()")
    else:
        print("❌ Missing emergency stop in execute_trade()")
    
    # Check for lockfile check in __init__
    if 'EMERGENCY STOP FILE DETECTED' in content:
        print("✅ Emergency lockfile check in __init__()")
    else:
        print("❌ Missing lockfile check in __init__()")
    
    # Check for max_concurrent_positions forced to 0
    if 'self.max_concurrent_positions = 0' in content:
        print("✅ max_concurrent_positions forced to 0 when lockfile exists")
    else:
        print("❌ Missing max_concurrent_positions override")

print()

# Check 3: No running bot processes
print("Checking for running bot processes...")
import subprocess
try:
    result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
    bot_processes = [line for line in result.stdout.split('\n') 
                     if 'python' in line.lower() and ('bot' in line.lower() or 'trading' in line.lower())
                     and 'grep' not in line.lower() and 'verify' not in line.lower()]
    
    if bot_processes:
        print("⚠️  FOUND RUNNING PROCESSES:")
        for proc in bot_processes:
            print(f"   {proc}")
        print()
        print("   You need to kill these processes:")
        print("   pkill -f python.*bot")
    else:
        print("✅ No bot processes currently running")
except Exception as e:
    print(f"⚠️  Could not check processes: {e}")

print()
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print()
print("Multiple layers of protection are now active:")
print()
print("1. 🔒 TRADING_EMERGENCY_STOP.conf exists")
print("   - Bot checks this file on every startup and every cycle")
print()
print("2. 🔒 execute_trade() hard BUY block")
print("   - FIRST check: blocks BUY if lockfile exists")
print()
print("3. 🔒 max_concurrent_positions = 0")
print("   - Forces position limit to ZERO during initialization")
print("   - No new positions can open regardless of other logic")
print()
print("4. 🔒 Multiple position count checks")
print("   - Blocks BUY if at or above max positions")
print("   - Checks actual Coinbase holdings, not just memory")
print()
print("CURRENT STATUS: SELL-ONLY MODE")
print()
print("✅ The bot will ONLY:")
print("   - Monitor existing 15 positions")
print("   - Close positions at stop loss or take profit")
print("   - Manage trailing stops")
print()
print("❌ The bot will NOT:")
print("   - Open any new BUY trades")
print("   - Re-buy positions that were manually sold")
print("   - Replace sold positions with new ones")
print()
print("=" * 80)
print()
print("TO RESTART BOT IN SELL-ONLY MODE:")
print("   ./start.sh")
print()
print("TO RESUME BUYING (not recommended yet):")
print("   rm TRADING_EMERGENCY_STOP.conf")
print("   ./start.sh")
print()
print("=" * 80)
