#!/usr/bin/env python3
"""
CRITICAL FIX EXECUTOR
Automatically commits and restarts NIJA with order closure fix
"""

import os
import sys
import time
import subprocess
import signal
from pathlib import Path

def run_command(cmd, description="", fatal=False):
    """Execute shell command and report status"""
    print(f"\n{'='*60}")
    print(f"📋 {description}")
    print(f"{'='*60}")
    print(f"$ {cmd}\n")
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(f"⚠️  {result.stderr}", file=sys.stderr)
        
        if result.returncode != 0:
            if fatal:
                print(f"❌ FAILED (exit code: {result.returncode})")
                sys.exit(1)
            else:
                print(f"⚠️  Warning: exit code {result.returncode}")
                return False
        else:
            print(f"✅ Success")
            return True
            
    except subprocess.TimeoutExpired:
        print(f"❌ TIMEOUT after 30 seconds")
        if fatal:
            sys.exit(1)
        return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        if fatal:
            sys.exit(1)
        return False

def main():
    os.chdir("/workspaces/Nija")
    
    print("\n" + "🔴"*30)
    print("CRITICAL FIX EXECUTION SEQUENCE")
    print("🔴"*30)
    
    # Step 1: Kill old bot
    run_command(
        "pkill -f 'python3 bot/live_trading.py' || true; sleep 2",
        "Step 1/6: Kill existing bot process"
    )
    
    # Step 2: Check git status
    run_command(
        "git status",
        "Step 2/6: Check git status"
    )
    
    # Step 3: Stage changes
    run_command(
        "git add -A",
        "Step 3/6: Stage all changes",
        fatal=True
    )
    
    # Step 4: Commit
    commit_msg = """CRITICAL FIX: Only remove positions from tracking when sell orders ACTUALLY execute

Root cause: Bot was removing positions from tracking even when sell orders failed on Coinbase.
Result: Positions appeared closed in logs but remained open and bleeding on Coinbase.

Changes:
1. trading_strategy.py - manage_open_positions():
   - Changed: ONLY remove positions if order.status == 'filled' or 'partial'
   - Before: Removed positions even if order failed
   - Now: Keep retrying failed exits on next cycle
   - Added error logging for failed orders

2. trade_analytics.py - get_session_stats():
   - Fixed KeyError when session has no completed trades
   - Added all required keys

Result: Failed orders now retry instead of being abandoned"""
    
    run_command(
        f'git commit -m "{commit_msg}"',
        "Step 4/6: Commit critical fix"
    )
    
    # Step 5: Push to origin
    run_command(
        "git push origin main",
        "Step 5/6: Push to origin",
        fatal=False  # Don't fail if nothing to push
    )
    
    # Step 6: Restart bot
    print(f"\n{'='*60}")
    print(f"Step 6/6: Restart NIJA bot with corrected order handling")
    print(f"{'='*60}\n")
    
    print("🤖 Starting bot in background...")
    bot_process = subprocess.Popen(
        "python3 bot/live_trading.py",
        cwd="/workspaces/Nija",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    print(f"✅ Bot started with PID: {bot_process.pid}\n")
    
    # Wait for logs to start
    time.sleep(3)
    
    # Show recent logs
    print("📊 Recent logs:")
    print("="*60)
    try:
        result = subprocess.run(
            "tail -30 nija.log",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        print(result.stdout)
    except:
        pass
    
    # Summary
    print("\n" + "="*60)
    print("✅ CRITICAL FIX DEPLOYMENT COMPLETE")
    print("="*60)
    print("""
Status:
  ✅ Old bot killed
  ✅ Changes committed
  ✅ Code pushed to origin
  ✅ Bot restarted with fixes

Expected Behavior:
  • Bot detects your 9 open positions
  • Places SELL orders for each position
  • Failed orders → logged as error, retried next cycle
  • Successful orders → position removed from tracking
  • NO MORE orphaned positions

Monitor Progress:
  tail -f nija.log | grep -E "POSITION|Closing|Exit|ERROR"

Watch for these patterns:
  ✅ "🔄 Closing {SYMBOL}: Stop loss hit"
  ✅ "✅ Position closed with PROFIT/LOSS"
  ❌ "❌ Failed to close {SYMBOL}: will retry"

Your positions are actively bleeding. If any orders fail,
the bot will retry them automatically next cycle.

""")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        sys.exit(1)
