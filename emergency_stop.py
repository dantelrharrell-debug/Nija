#!/usr/bin/env python3
"""
EMERGENCY STOP - Disable bot from running
"""
import os
import subprocess
import sys

def main():
    print("\n" + "="*80)
    print("🚨 EMERGENCY STOP - Disable Trading Bot")
    print("="*80)
    
    print("\n⚠️  This will:")
    print("   1. Kill any running bot processes")
    print("   2. Create a STOP file that prevents bot startup")
    print("   3. Show you how to keep it stopped on Railway/Render")
    
    confirm = input("\nProceed with emergency stop? (yes/no): ")
    
    if confirm.lower() != 'yes':
        print("\n❌ Cancelled")
        return
    
    # 1. Kill running processes
    print("\n1️⃣ Checking for running bot processes...")
    print("-" * 80)
    
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        
        bot_processes = []
        for line in result.stdout.split('\n'):
            if 'python' in line.lower():
                # Check if it's a bot-related process
                if any(x in line for x in ['trading_strategy', 'main.py', 'bot.py', 'webhook', 'nija']):
                    parts = line.split()
                    if len(parts) > 1:
                        pid = parts[1]
                        bot_processes.append((pid, line[:100]))
        
        if bot_processes:
            print(f"\n   🚨 Found {len(bot_processes)} bot process(es):\n")
            for pid, desc in bot_processes:
                print(f"   PID {pid}: {desc}...")
            
            print("\n   Killing processes...")
            for pid, _ in bot_processes:
                try:
                    subprocess.run(['kill', pid])
                    print(f"   ✅ Killed process {pid}")
                except Exception as e:
                    print(f"   ⚠️  Could not kill {pid}: {e}")
        else:
            print("   ✅ No bot processes running")
            
    except Exception as e:
        print(f"   ⚠️  Could not check processes: {e}")
    
    # 2. Create STOP file
    print("\n2️⃣ Creating EMERGENCY_STOP file...")
    print("-" * 80)
    
    with open('EMERGENCY_STOP', 'w') as f:
        f.write("""# EMERGENCY STOP ACTIVE
# 
# Bot will not start while this file exists
# Created: Auto-generated
# Reason: $5 trading causing losses
#
# To resume trading:
# 1. Delete this file
# 2. Ensure account has $50+ balance
# 3. Verify bot settings are updated
# 4. Monitor first 10 trades manually
#
# DO NOT RESUME until you have proper capital!
""")
    
    print("   ✅ Created EMERGENCY_STOP file")
    
    # 3. Add stop check to main entry points
    print("\n3️⃣ Adding stop check to bot entry points...")
    print("-" * 80)
    
    entry_points = ['main.py', 'bot.py', 'bot/trading_strategy.py']
    
    for entry_point in entry_points:
        if os.path.exists(entry_point):
            with open(entry_point, 'r') as f:
                content = f.read()
            
            # Add check at the beginning (after imports)
            stop_check = '''
# EMERGENCY STOP CHECK
import os
if os.path.exists('EMERGENCY_STOP'):
    print("\\n" + "="*80)
    print("🚨 EMERGENCY STOP ACTIVE")
    print("="*80)
    print("Bot is disabled. See EMERGENCY_STOP file for details.")
    print("Delete EMERGENCY_STOP file to resume trading.")
    print("="*80 + "\\n")
    exit(0)
'''
            
            if 'EMERGENCY STOP CHECK' not in content:
                # Find where to insert (after imports)
                import_end = 0
                for i, line in enumerate(content.split('\n')):
                    if line.startswith('import ') or line.startswith('from '):
                        import_end = i + 1
                
                lines = content.split('\n')
                lines.insert(import_end + 1, stop_check)
                
                with open(entry_point, 'w') as f:
                    f.write('\n'.join(lines))
                
                print(f"   ✅ Added stop check to {entry_point}")
    
    # 4. Instructions for cloud platforms
    print("\n" + "="*80)
    print("☁️  STOPPING BOT ON CLOUD PLATFORMS")
    print("="*80)
    
    print("\n📍 If deployed on Railway:")
    print("   1. Go to: https://railway.app/dashboard")
    print("   2. Find your Nija project")
    print("   3. Click 'Settings'")
    print("   4. Pause deployment or set replicas to 0")
    
    print("\n📍 If deployed on Render:")
    print("   1. Go to: https://dashboard.render.com")
    print("   2. Find your Nija service")
    print("   3. Click 'Suspend' or 'Manual Deploy Off'")
    
    print("\n📍 If deployed on Heroku:")
    print("   1. Go to: https://dashboard.heroku.com")
    print("   2. Find your app")
    print("   3. Click 'More' → 'Stop'")
    
    # Summary
    print("\n" + "="*80)
    print("✅ EMERGENCY STOP COMPLETE")
    print("="*80)
    
    print("\n🛑 Bot Status: DISABLED")
    print("\n✅ What was done:")
    print("   • Killed running processes")
    print("   • Created EMERGENCY_STOP file")
    print("   • Added stop checks to entry points")
    
    print("\n⚠️  Bot will NOT start even if server restarts")
    
    print("\n💡 To resume trading (when ready):")
    print("   1. Deposit $50-100 to Coinbase")
    print("   2. Run: python3 fix_bot_settings.py")
    print("   3. Delete EMERGENCY_STOP file:")
    print("      rm EMERGENCY_STOP")
    print("   4. Restart bot and monitor trades")
    
    print("\n📊 Recommended next steps:")
    print("   1. Run: python3 show_holdings.py")
    print("      → See what crypto you're holding")
    print("   2. Decide: Sell now or hold?")
    print("   3. If selling: python3 sell_all_positions.py")
    print("   4. Deposit proper capital ($50+)")
    print("   5. Resume with updated settings")

if __name__ == "__main__":
    main()
