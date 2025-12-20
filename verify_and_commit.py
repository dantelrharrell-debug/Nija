#!/usr/bin/env python3
"""Quick status check and commit helper"""
import subprocess
import sys

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.returncode

print("\n" + "="*70)
print("📊 CURRENT STATUS CHECK")
print("="*70 + "\n")

# Check if there are staged files
staged, _ = run("git diff --cached --name-only")
if staged:
    print("✅ Files staged for commit:")
    for f in staged.split('\n'):
        print(f"   - {f}")
else:
    print("⚠️  No files currently staged")

# Check unstaged changes
unstaged, _ = run("git diff --name-only")
if unstaged:
    print("\n⚠️  Unstaged changes:")
    for f in unstaged.split('\n'):
        print(f"   - {f}")

# Check recent commits
print("\n" + "="*70)
print("📝 RECENT COMMITS (last 5)")
print("="*70)
log, _ = run("git log --oneline -5")
print(log)

# Check if we're ahead
print("\n" + "="*70)
print("🌐 REMOTE STATUS")
print("="*70)
status, _ = run("git status -sb")
print(status)

print("\n" + "="*70)
print("RECOMMENDED COMMIT MESSAGE:")
print("="*70)
print("""
FIX: Bot balance detection via portfolio breakdown API ($155.46 detected)

PROBLEM SOLVED:
- get_accounts() API returned $0.00 despite $156.97 in web UI
- Bot couldn't detect funds to trade with

SOLUTION IMPLEMENTED:
- Switched to portfolio breakdown API (get_portfolio_breakdown)
- Iterates spot_positions to extract available_to_trade_fiat
- Now successfully detects $155.46 ($97.92 USD + $57.54 USDC)

CHANGES:
- bot/broker_manager.py: Complete rewrite of get_account_balance()
- check_tradable_balance.py: Fixed to use getattr() for API objects
- test_updated_bot.py: Integration test confirming $155.46 visible

TESTING:
✅ test_updated_bot.py confirms bot sees $155.46
✅ check_tradable_balance.py shows exact USD/USDC breakdown
✅ Portfolio breakdown API returns all data correctly

DEPLOYMENT:
- Railway will auto-deploy on push
- Bot will start trading with full $155.46 balance
- Dual RSI strategy (RSI_9 + RSI_14) scanning 732+ markets
""")

print("\n" + "="*70)
print("QUICK COMMANDS:")
print("="*70)
print("To commit with this message:")
print("  git commit -F .git/COMMIT_EDITMSG")
print("\nOr use a custom message:")
print("  git commit -m 'Your message here'")
print("\nThen push:")
print("  git push")
print("="*70 + "\n")
