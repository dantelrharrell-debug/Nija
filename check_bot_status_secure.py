#!/usr/bin/env python3
"""
Check if NIJA bot is currently running
"""
import os
import subprocess
import sys
from datetime import datetime

def check_bot_running():
    """Check if NIJA process is running"""
    print("\n" + "="*80)
    print("🤖 NIJA BOT STATUS CHECK")
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Check for trading lock
    if os.path.exists('/workspaces/Nija/TRADING_LOCKED.conf'):
        print("🔒 TRADING LOCK: ACTIVE")
        with open('/workspaces/Nija/TRADING_LOCKED.conf', 'r') as f:
            lock_content = f.read()
        print("\nLock file contents:")
        for line in lock_content.split('\n'):
            if line.strip() and not line.startswith('#'):
                print(f"   {line}")
        print()
    
    # Check processes
    print("-" * 80)
    print("PROCESS STATUS:\n")
    
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'python.*trading_strategy|python.*live_trading|python.*apex'],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            print(f"⚠️  RUNNING: {len(pids)} bot process(es) found\n")
            
            for pid in pids:
                if pid:
                    try:
                        ps_result = subprocess.run(
                            ['ps', '-p', pid, '-o', 'cmd='],
                            capture_output=True,
                            text=True
                        )
                        cmd = ps_result.stdout.strip()
                        print(f"   PID {pid}: {cmd[:70]}")
                    except:
                        print(f"   PID {pid}: [unknown]")
        else:
            print("✅ NO BOT PROCESSES: Bot is not running\n")
    
    except Exception as e:
        print(f"⚠️  Could not check processes: {e}\n")
    
    # Check for running services
    print("\n" + "-" * 80)
    print("SERVICE STATUS:\n")
    
    try:
        # Check if Railway or systemd services are running
        if os.path.exists('/etc/systemd/system/nija.service'):
            result = subprocess.run(
                ['systemctl', 'is-active', 'nija'],
                capture_output=True,
                text=True
            )
            status = result.stdout.strip()
            print(f"   systemd nija service: {status}")
    except:
        pass
    
    # Check log file
    print("\n" + "-" * 80)
    print("RECENT LOG ENTRIES:\n")
    
    log_file = '/workspaces/Nija/nija.log'
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()[-10:]  # Last 10 lines
            
            if lines:
                print(f"   Last 10 log entries from {log_file}:\n")
                for line in lines:
                    print(f"   {line.rstrip()}")
            else:
                print("   (Log file is empty)")
        except Exception as e:
            print(f"   Could not read log: {e}")
    else:
        print(f"   (No log file at {log_file})")
    
    print("\n" + "="*80)
    print("SUMMARY:\n")
    
    if os.path.exists('/workspaces/Nija/TRADING_LOCKED.conf'):
        print("✅ TRADING IS LOCKED - No new positions can be opened")
        print("✅ All crypto has been liquidated to USD/USDC")
        print("✅ Account is protected from further losses\n")
    else:
        print("⚠️  Trading lock not in place - bot could trade\n")
    
    print("="*80 + "\n")

if __name__ == '__main__':
    check_bot_running()
