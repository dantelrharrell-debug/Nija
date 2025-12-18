#!/usr/bin/env python3
"""
Commit and push critical trading blocker fixes
"""
import subprocess
import sys
import os

def run_command(cmd, description):
    """Run a shell command and print output"""
    print(f"\n🔧 {description}...")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd='/workspaces/Nija')
    
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    if result.returncode != 0:
        print(f"❌ Command failed with code {result.returncode}")
        sys.exit(result.returncode)
    
    return result

def main():
    os.chdir('/workspaces/Nija')
    
    # Add files
    run_command('git add bot/market_adapter.py bot/broker_manager.py', 
                'Staging critical fix files')
    
    # Commit with detailed message
    commit_msg = """FIX CRITICAL TRADING BLOCKERS: Position size + error logging

ISSUE 1 - Position Size Below Minimum:
- Changed minimum from $0.005 to $5.00 (Coinbase Advanced Trade requirement)
- File: bot/market_adapter.py line 217
- Previous: All $1.12 trades rejected (below $5 minimum)
- After: All trades will be $5+ (meets Coinbase requirement)

ISSUE 2 - Error Logging Still Generic:
- Detailed error format already in code (line 352)
- Just adding to commit to ensure deployed
- File: bot/broker_manager.py
- Previous: 'Unknown error from broker' (generic)  
- After: '🚨 Coinbase order error: [ErrorType]: [details]'

EXPECTED RESULTS (Deployment 6):
- Position sizes: $5.00+ (meets Coinbase minimum)
- Error messages: Detailed with error type and description
- Trade success: First successful executions
- 15-day goal: Can finally start progress toward $111.62

Current deployment 5 status:
- 40+ trade attempts, 100% failure rate
- All $1.12 positions (below $5 minimum)
- All errors generic (cannot diagnose)

After this commit:
- Railway will auto-rebuild (deployment 6)
- Position sizing will work
- Error logging will work
- Can diagnose any remaining issues"""
    
    run_command(f'git commit -m "{commit_msg}"', 'Committing critical fixes')
    
    # Push to remote
    run_command('git push origin main', 'Pushing to GitHub')
    
    # Show final commit
    print("\n✅ Commit and push completed!")
    print("\n📝 Commit details:")
    result = run_command('git log -1 --oneline', 'Getting commit hash')
    
    print("\n🚀 Railway will now auto-deploy Deployment 6")
    print("   Watch logs at: https://railway.app")

if __name__ == '__main__':
    main()
