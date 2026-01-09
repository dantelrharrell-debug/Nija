#!/usr/bin/env python3
"""
Quick Trading Status Check
Determines if NIJA is actively trading right now
"""

import os
import sys
import json
from datetime import datetime

def check_trading_status():
    """Check if NIJA is currently trading"""
    
    print("\n" + "="*70)
    print("🔍 NIJA TRADING STATUS CHECK")
    print("="*70)
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
    print()
    
    # Check for emergency stop
    if os.path.exists('EMERGENCY_STOP'):
        print("❌ STATUS: STOPPED")
        print("   Reason: Emergency stop file exists")
        print("   File: EMERGENCY_STOP")
        print()
        print("To resume trading:")
        print("  rm EMERGENCY_STOP")
        return False
    
    # Check if bot process is running
    try:
        import subprocess
        result = subprocess.run(['pgrep', '-f', 'bot.py'], capture_output=True, text=True)
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            print(f"✅ Bot process running (PID: {', '.join(pids)})")
        else:
            print("❌ Bot process NOT running")
            print("   No bot.py process found")
            return False
    except Exception as e:
        print(f"⚠️  Could not check process status: {e}")
    
    print()
    
    # Check for recent positions activity
    if os.path.exists('positions.json'):
        try:
            with open('positions.json', 'r') as f:
                positions = json.load(f)
            
            if positions:
                print(f"📊 Active positions: {len(positions)}")
                for symbol, pos in list(positions.items())[:5]:
                    print(f"   - {symbol}: {pos.get('side', 'UNKNOWN')}")
                if len(positions) > 5:
                    print(f"   ... and {len(positions) - 5} more")
            else:
                print("📊 Active positions: 0")
        except Exception as e:
            print(f"⚠️  Could not read positions: {e}")
    else:
        print("📊 No positions file found")
    
    print()
    
    # Check user registry
    if os.path.exists('data/user_investor_registry.json'):
        try:
            with open('data/user_investor_registry.json', 'r') as f:
                registry = json.load(f)
            
            users = registry.get('users', {})
            if users:
                print(f"👥 Registered users: {len(users)}")
                for user_id, user_data in users.items():
                    enabled = user_data.get('enabled', False)
                    status = "✅ ENABLED" if enabled else "❌ DISABLED"
                    name = user_data.get('name', 'Unknown')
                    print(f"   User #{user_id}: {name} - {status}")
            else:
                print("👥 No users registered")
        except Exception as e:
            print(f"⚠️  Could not read user registry: {e}")
    else:
        print("👥 No user registry found")
    
    print()
    
    # Check for recent trades
    if os.path.exists('trade_journal.jsonl'):
        try:
            with open('trade_journal.jsonl', 'r') as f:
                lines = f.readlines()
            
            if lines:
                recent_trades = lines[-5:]
                print(f"💰 Recent trades (last {len(recent_trades)} of {len(lines)}):")
                for line in recent_trades:
                    try:
                        trade = json.loads(line)
                        ts = trade.get('timestamp', 'Unknown')
                        symbol = trade.get('symbol', 'Unknown')
                        side = trade.get('side', 'Unknown')
                        price = trade.get('price', 0)
                        print(f"   {ts}: {symbol} {side} @ ${price:.2f}")
                    except:
                        pass
            else:
                print("💰 No trades recorded yet")
        except Exception as e:
            print(f"⚠️  Could not read trade journal: {e}")
    else:
        print("💰 No trade journal found")
    
    print()
    print("="*70)
    
    # Final determination
    print("\n🎯 FINAL STATUS:")
    print()
    
    # Check if we can find evidence of active trading
    has_process = True  # Assumed from earlier check
    no_emergency_stop = not os.path.exists('EMERGENCY_STOP')
    
    if has_process and no_emergency_stop:
        print("⚠️  Bot is RUNNING but may be in retry loop")
        print("   Check logs for connection status:")
        print("   - Look for '✅ Connected to Coinbase'")
        print("   - Or '⚠️  Connection attempt X/10 failed'")
        print()
        print("   If seeing 403 errors, bot is waiting for API to recover")
        print("   This can take 5-30 minutes")
    else:
        print("❌ Bot is NOT trading")
        if os.path.exists('EMERGENCY_STOP'):
            print("   Reason: Emergency stop active")
        else:
            print("   Reason: Bot process not running")
    
    print()
    print("="*70)
    print()

if __name__ == "__main__":
    check_trading_status()
