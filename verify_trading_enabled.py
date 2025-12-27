#!/usr/bin/env python3
"""
Test script to verify STOP_ALL_ENTRIES.conf removal re-enables trading
This simulates the bot's checks without making actual trades
"""

import os
import sys

def check_emergency_stops():
    """Check for emergency stop files"""
    print("="*80)
    print("EMERGENCY STOP CHECK")
    print("="*80)
    
    # Check EMERGENCY_STOP file
    emergency_stop = os.path.exists('EMERGENCY_STOP')
    if emergency_stop:
        print("❌ EMERGENCY_STOP file exists - Bot will NOT start")
        with open('EMERGENCY_STOP', 'r') as f:
            print(f"   Content: {f.read()}")
        return False
    else:
        print("✅ EMERGENCY_STOP file not found - Bot can start")
    
    # Check STOP_ALL_ENTRIES.conf
    stop_entries = os.path.exists('STOP_ALL_ENTRIES.conf')
    if stop_entries:
        print("❌ STOP_ALL_ENTRIES.conf exists - New trades BLOCKED")
        with open('STOP_ALL_ENTRIES.conf', 'r') as f:
            print(f"   Content: {f.read()}")
        return False
    else:
        print("✅ STOP_ALL_ENTRIES.conf not found - New trades ALLOWED")
    
    print()
    return True

def check_trading_conditions(emergency_ok):
    """Check if trading conditions are met"""
    print("="*80)
    print("TRADING CONDITIONS CHECK")
    print("="*80)
    
    # Note: We can't check actual balance without API credentials
    # This just documents the requirements
    
    print("Required conditions for new trades:")
    status_1 = "✅ PASSED" if not os.path.exists('STOP_ALL_ENTRIES.conf') else "❌ FAILED"
    status_2 = "✅ PASSED" if not os.path.exists('EMERGENCY_STOP') else "❌ FAILED"
    print(f"1. {status_1} - STOP_ALL_ENTRIES.conf must NOT exist")
    print(f"2. {status_2} - EMERGENCY_STOP must NOT exist")
    print("3. ⚠️  UNKNOWN - Position count < 8 (requires live check)")
    print("4. ⚠️  UNKNOWN - Account balance >= $25 (requires API connection)")
    print("5. ⚠️  UNKNOWN - Position size >= $2 (calculated per trade)")
    print("6. ⚠️  UNKNOWN - Market conditions pass APEX v7.1 filters (per symbol)")
    print()
    if emergency_ok:
        print("Status: EMERGENCY STOPS REMOVED ✅")
        print("        Trading can resume when other conditions met")
    else:
        print("Status: EMERGENCY STOPS ACTIVE ❌")
        print("        Trading blocked - remove stop files to continue")
    print()

def simulate_bot_check():
    """Simulate the bot's trading cycle check"""
    print("="*80)
    print("SIMULATED BOT TRADING CYCLE")
    print("="*80)
    
    # Simulate the actual check from trading_strategy.py line 216-217
    # The bot code runs from bot/ directory, so it looks for '../STOP_ALL_ENTRIES.conf'
    # which resolves to the repository root. We're running from root, so just check directly.
    stop_entries_file = 'STOP_ALL_ENTRIES.conf'
    entries_blocked = os.path.exists(stop_entries_file)
    
    # Simulate position count (unknown without live data)
    simulated_positions = 0  # Assume 0 for testing
    
    print(f"stop_entries_file: {stop_entries_file}")
    print(f"entries_blocked: {entries_blocked}")
    print(f"simulated_positions: {simulated_positions}")
    print()
    
    # Reproduce bot logic from trading_strategy.py lines 219-226
    if entries_blocked:
        print("🛑 ALL NEW ENTRIES BLOCKED: STOP_ALL_ENTRIES.conf is active")
        print("   Exiting positions only (no new buys)")
        return False
    elif simulated_positions >= 8:
        print(f"🛑 ENTRY BLOCKED: Position cap reached ({simulated_positions}/8)")
        print("   Closing positions only until below cap")
        return False
    else:
        print(f"✅ Position cap OK ({simulated_positions}/8) - entries enabled")
        print("   Bot will scan markets for new opportunities")
        return True

def main():
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "NIJA TRADING BOT - STATUS CHECK" + " "*27 + "║")
    print("╚" + "="*78 + "╝")
    print()
    
    # Check emergency stops
    emergency_ok = check_emergency_stops()
    
    # Check trading conditions
    check_trading_conditions(emergency_ok)
    
    # Simulate bot check
    trading_enabled = simulate_bot_check()
    
    # Final summary
    print("="*80)
    print("SUMMARY")
    print("="*80)
    if trading_enabled:
        print("✅ TRADING ENABLED")
        print("   Emergency stops removed")
        print("   Bot will trade when:")
        print("   - Position count < 8")
        print("   - Account balance >= $25")
        print("   - Market conditions favorable")
    else:
        print("❌ TRADING DISABLED")
        print("   Emergency stops active or position cap reached")
    print()
    
    return 0 if trading_enabled else 1

if __name__ == '__main__':
    sys.exit(main())
