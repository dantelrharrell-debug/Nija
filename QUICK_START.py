#!/usr/bin/env python3
"""
QUICK START GUIDE - Get Bot Running in 30 Seconds
"""

import os
import sys
import json
import subprocess
from pathlib import Path

def check_ready():
    """Verify everything is ready to start bot"""
    print("\n" + "="*80)
    print("✅ PRE-FLIGHT CHECKLIST")
    print("="*80 + "\n")
    
    checks = []
    
    # Check .env
    if Path(".env").exists():
        print("✅ .env file found (API credentials)")
        checks.append(True)
    else:
        print("❌ .env file missing")
        checks.append(False)
    
    # Check position file
    if Path("data/open_positions.json").exists():
        try:
            with open("data/open_positions.json") as f:
                data = json.load(f)
            pos_count = len(data.get("positions", {}))
            print(f"✅ Position file found ({pos_count} positions tracked)")
            checks.append(True)
        except:
            print("❌ Position file corrupted")
            checks.append(False)
    else:
        print("❌ Position file missing")
        checks.append(False)
    
    # Check bot code
    if Path("bot/trading_strategy.py").exists() and Path("bot/live_trading.py").exists():
        print("✅ Bot code files present")
        checks.append(True)
    else:
        print("❌ Bot code files missing")
        checks.append(False)
    
    # Check Python
    if sys.version_info >= (3, 8):
        print(f"✅ Python {sys.version.split()[0]} available")
        checks.append(True)
    else:
        print("❌ Python 3.8+ required")
        checks.append(False)
    
    print()
    
    if all(checks):
        print("="*80)
        print("✅ ALL CHECKS PASSED - Ready to start bot!")
        print("="*80 + "\n")
        return True
    else:
        print("="*80)
        print("❌ Some checks failed - Please fix issues above")
        print("="*80 + "\n")
        return False

def show_commands():
    """Show startup commands"""
    print("🚀 QUICK START COMMANDS\n")
    print("-"*80)
    print("\n1️⃣  START BOT (recommended):")
    print("   bash run_bot_position_management.sh\n")
    
    print("-"*80)
    print("\n2️⃣  MONITOR POSITIONS (in another terminal):")
    print("   python3 monitor_positions.py\n")
    
    print("-"*80)
    print("\n3️⃣  WATCH BOT LOGS (in another terminal):")
    print("   tail -f nija.log\n")
    
    print("-"*80)
    print("\n4️⃣  CHECK SPECIFIC EXITS:")
    print("   tail -f nija.log | grep -E 'Exit|CLOSE|Stop loss|Take profit'\n")
    
    print("-"*80)
    print("\n5️⃣  STOP BOT:")
    print("   Ctrl+C in the terminal running the bot\n")
    
    print("="*80)
    print("WHAT TO EXPECT")
    print("="*80)
    print("""
First 30 seconds:
  • Bot starts and loads 9 positions
  • API connects to Coinbase
  • Positions validated

First 2.5 minutes:
  • First trading cycle runs
  • Prices fetched for all 9 positions
  • Checks stops/takes/trails
  • Logs any position exits

Next 24 hours:
  • Bot runs every 2.5 minutes
  • Monitors for stop losses (2% down)
  • Monitors for take profits (5% up)
  • Closes positions when conditions met
  • Freed capital available for new trades

Expected timeline:
  • First exit: Within days (depends on price movement)
  • Week 1: 2-4 positions close
  • Month 1: All positions cycled, account growing
  • Month 2-3: Consistent daily profits begin
  
Key metric to watch:
  • Count closed positions in the log
  • Each closed position = freed capital
  • More exits = faster compounding
    """)
    
    print("="*80)
    print("\n💡 IMPORTANT NOTES:\n")
    print("• Keep bot running 24/7 for best results")
    print("• Monitor logs for exit activity") 
    print("• Each position close = opportunity to grow account")
    print("• Patient capital management = sustainable profits\n")
    print("="*80 + "\n")

def main():
    os.chdir(Path(__file__).parent)
    
    if check_ready():
        show_commands()
        
        print("Ready? Start with:\n")
        print("   bash run_bot_position_management.sh\n")
    else:
        print("Please fix issues and try again.\n")
        sys.exit(1)

if __name__ == '__main__':
    main()
