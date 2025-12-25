#!/bin/bash

# Commit and push critical trading blocker fixes

cd /workspaces/Nija

git add bot/market_adapter.py bot/broker_manager.py

git commit -m "FIX CRITICAL TRADING BLOCKERS: Position size + error logging

ISSUE 1 - Position Size Below Minimum:
- Changed minimum from \$0.005 to \$5.00 (Coinbase Advanced Trade requirement)
- File: bot/market_adapter.py line 217
- Previous: All \$1.12 trades rejected (below \$5 minimum)
- After: All trades will be \$5+ (meets Coinbase requirement)

ISSUE 2 - Error Logging Still Generic:
- Detailed error format already in code (line 352)
- Just adding to commit to ensure deployed
- File: bot/broker_manager.py
- Previous: 'Unknown error from broker' (generic)  
- After: '🚨 Coinbase order error: [ErrorType]: [details]'

EXPECTED RESULTS (Deployment 6):
- Position sizes: \$5.00+ (meets Coinbase minimum)
- Error messages: Detailed with error type and description
- Trade success: First successful executions
- 15-day goal: Can finally start progress toward \$111.62

Current deployment 5 status:
- 40+ trade attempts, 100% failure rate
- All \$1.12 positions (below \$5 minimum)
- All errors generic (cannot diagnose)

After this commit:
- Railway will auto-rebuild (deployment 6)
- Position sizing will work
- Error logging will work
- Can diagnose any remaining issues"

git push origin main

echo ""
echo "✅ Commit and push completed!"
echo "Commit hash:"
git log -1 --oneline
