#!/usr/bin/env python3
"""
TASK 4: Check if bot is currently running
Checks Railway deployment, git status, and process info
"""
import os
import sys
import subprocess
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

print("\n" + "="*100)
print("⚙️  TASK 4: CHECK IF NIJA BOT IS RUNNING")
print("="*100)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

# Check 1: Git status and recent commits
print("CHECK 1: Recent Git Activity")
print("-"*100)

try:
    result = subprocess.run(['git', 'log', '--oneline', '-10'], 
                          cwd='/workspaces/Nija',
                          capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print("✅ Recent commits:")
        for line in result.stdout.strip().split('\n')[:5]:
            print(f"   {line}")
    else:
        print("❌ Could not fetch git log")
except Exception as e:
    print(f"⚠️  Git check failed: {e}")

# Check 2: Bot configuration
print(f"\nCHECK 2: Bot Configuration")
print("-"*100)

try:
    # Check .env file
    if os.path.exists('/workspaces/Nija/.env'):
        with open('/workspaces/Nija/.env', 'r') as f:
            env_content = f.read()
        
        has_api_key = 'COINBASE_API_KEY' in env_content
        has_api_secret = 'COINBASE_API_SECRET' in env_content
        paper_mode = 'PAPER_MODE' in env_content
        
        print(f"   API Key set: {'✅' if has_api_key else '❌'}")
        print(f"   API Secret set: {'✅' if has_api_secret else '❌'}")
        print(f"   Paper Mode: {'🟡 ENABLED' if paper_mode else '✅ DISABLED (LIVE)'}")
        
        if not (has_api_key and has_api_secret):
            print(f"\n   ⚠️  CREDENTIALS MISSING - Bot cannot run!")
    else:
        print(f"   ❌ No .env file found")
except Exception as e:
    print(f"⚠️  Could not check .env: {e}")

# Check 3: Process status
print(f"\nCHECK 3: Bot Process Status (Local)")
print("-"*100)

try:
    result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
    lines = result.stdout.split('\n')
    
    bot_processes = [l for l in lines if any(x in l for x in ['trading_strategy', 'live_trading', 'nija', 'bot.py'])]
    
    if bot_processes:
        print("✅ Bot processes found:")
        for proc in bot_processes[:3]:
            print(f"   {proc.strip()[:100]}")
    else:
        print("❌ NO BOT PROCESS FOUND")
        print("   → Bot is NOT running locally")
        print("   → Check if it's running on Railway (cloud deployment)")
except Exception as e:
    print(f"⚠️  Process check failed: {e}")

# Check 4: Flask/Webhook server status
print(f"\nCHECK 4: Webhook Server Status")
print("-"*100)

try:
    result = subprocess.run(['lsof', '-i', ':5000'], capture_output=True, text=True, timeout=5)
    
    if result.returncode == 0 and result.stdout.strip():
        print("✅ Flask webhook server is RUNNING on port 5000")
        print(result.stdout.strip()[:200])
    else:
        print("❌ No service listening on port 5000")
        print("   → Webhook server is NOT running")
except Exception as e:
    print(f"⚠️  Port check failed: {e}")

# Check 5: Position files
print(f"\nCHECK 5: Position Tracking Files")
print("-"*100)

position_files = [
    '/workspaces/Nija/data/open_positions.json',
    '/usr/src/app/data/open_positions.json',
    './data/open_positions.json'
]

found_position_file = False
for file_path in position_files:
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                import json
                positions = json.load(f)
            
            print(f"✅ Found position file: {file_path}")
            print(f"   Positions tracked: {len(positions)}")
            if positions:
                print(f"   Examples: {list(positions.keys())[:3]}")
            found_position_file = True
            break
        except Exception as e:
            print(f"⚠️  Could not read {file_path}: {e}")

if not found_position_file:
    print("❌ No position file found")
    print("   → Bot hasn't started yet OR")
    print("   → Bot crashed/stopped before creating file")

# Check 6: Log file
print(f"\nCHECK 6: Bot Activity Log")
print("-"*100)

log_files = [
    '/workspaces/Nija/nija.log',
    '/usr/src/app/nija.log'
]

for log_file in log_files:
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
            
            print(f"✅ Found log file: {log_file}")
            print(f"   Total entries: {len(lines)}")
            
            # Get last activity
            if lines:
                last_line = lines[-1].strip()
                print(f"   Last activity: {last_line[:100]}")
                
                # Check for errors
                error_lines = [l for l in lines[-50:] if 'ERROR' in l or 'Failed' in l]
                if error_lines:
                    print(f"   Recent errors: {len(error_lines)}")
                    for err in error_lines[:2]:
                        print(f"      {err.strip()[:80]}")
                
                # Check for sells
                sell_lines = [l for l in lines[-50:] if 'SELL' in l or 'closed' in l]
                if sell_lines:
                    print(f"   ✅ Recent sells/closures: {len(sell_lines)}")
                else:
                    print(f"   ❌ No recent sells found")
        except Exception as e:
            print(f"⚠️  Could not read {log_file}: {e}")

print(f"\n" + "="*100)
print("📊 BOT STATUS SUMMARY")
print("="*100)

print(f"""
LIKELIHOOD BOT IS RUNNING:
├─ Local: ❌ (No process found - check if on Railway)
├─ Webhook: ❌ (Port 5000 not listening)
├─ Positions: {"✅ Tracked" if found_position_file else "❌ Not tracked"}
└─ Activity: {"✅ Has logs" if any(os.path.exists(f) for f in log_files) else "❌ No logs"}

ACTION NEEDED:
1. If bot should be running on Railway:
   → Check Railway dashboard at https://railway.app
   → Look for deployment logs
   → Verify service is active

2. If bot should be local:
   → Run: ./start.sh
   → Monitor with: tail -f nija.log

3. Regardless:
   → You have {len(positions)} open positions needing closure
   → Run force liquidation or restart bot
""")

print("="*100 + "\n")
