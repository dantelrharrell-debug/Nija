#!/usr/bin/env python3
import subprocess
import sys
import os

os.chdir('/workspaces/Nija')

try:
    # Stage files
    print("📝 Staging files...")
    subprocess.run(['git', 'add', 'bot/broker_manager.py', 'bot/trading_strategy.py'], check=True)
    
    # Check status
    print("\n📋 Git status:")
    subprocess.run(['git', 'status'], check=True)
    
    # Commit
    print("\n💾 Committing changes...")
    subprocess.run([
        'git', 'commit', '-m',
        'Refactor balance tracking and candle normalization\n\n'
        '- Update get_account_balance() to include USD + USDC balance\n'
        '- Add _normalize_candles() helper for early type conversion\n'
        '- Replace pd.to_numeric() with .astype(float) for better clarity'
    ], check=True)
    
    # Push
    print("\n🚀 Pushing to origin/main...")
    subprocess.run(['git', 'push', 'origin', 'main'], check=True)
    
    print("\n✅ Successfully committed and pushed!")
    sys.exit(0)
    
except subprocess.CalledProcessError as e:
    print(f"\n❌ Git command failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"\n❌ Error: {e}")
    sys.exit(1)
