#!/usr/bin/env python3
import subprocess
import sys
import os

os.chdir('/workspaces/Nija')

try:
    # Stage files
    print("📝 Staging portfolio scanner and broker updates...")
    subprocess.run(['git', 'add', 'find_usd_portfolio.py', 'bot/broker_manager.py'], check=True)
    
    # Check status
    print("\n📋 Git status:")
    subprocess.run(['git', 'status'], check=True)
    
    # Commit
    print("\n💾 Committing changes...")
    subprocess.run([
        'git', 'commit', '-m',
        'Auto-detect correct Coinbase portfolio for USD balance\n\n'
        '- Add portfolio scanner script (find_usd_portfolio.py) for diagnostics\n'
        '- Update get_account_balance() to scan all portfolios via get_portfolios()\n'
        '- Auto-detect portfolio containing USD and query with retail_portfolio_id\n'
        '- Fixes $0.00 balance issue when USD is in non-default portfolio\n'
        '- Maintains fallback to default accounts if portfolio scan fails'
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
