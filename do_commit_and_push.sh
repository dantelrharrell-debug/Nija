#!/bin/bash

cd /workspaces/Nija

# Stage all changes
git add -A

# Create commit with detailed message
git commit -m "fix: critical position sizing and circuit breaker repairs to prevent account bleeding

BREAKING CHANGE: Position sizing logic corrected from min to max percentage

## Problem
Bot account bled from \$5.05 to \$0.15 (97% loss) due to:
1. Position sizing using min_position_pct (5%) instead of max_position_pct (15%)
2. Missing absolute position minimum (\$2.00) allowing unprofitable micro-trades
3. No circuit breaker for critically low balances
4. Ineffective reserve management on small accounts

## Solution
Four critical fixes deployed:

### Fix 1: Position Sizing Direction (adaptive_growth_manager.py:157)
- Changed: config['min_position_pct'] → config['max_position_pct']
- Effect: Uses 15% max instead of 5% min on ultra-aggressive stage

### Fix 2: Absolute Position Minimum (adaptive_growth_manager.py)
- Added: get_min_position_usd() method returning \$2.00
- Effect: No position < \$2.00 (prevents fee drag)

### Fix 3: Circuit Breaker (trading_strategy.py:655)
- Added: MINIMUM_TRADING_BALANCE check (\$25 default)
- Effect: Halts ALL trading if balance < \$25

### Fix 4: Reserve Management (trading_strategy.py:679)
- Changed: Dynamic reserve tiers
  - < \$100: 50% reserve (was 100%)
  - \$100-500: 30% (was 15%)
  - \$500-2K: 20% (was 10%)
  - \$2K+: 10% (was 5%)

## Files Modified
- bot/adaptive_growth_manager.py: Fixed position sizing, added minimum
- bot/trading_strategy.py: Added circuit breaker, improved reserves

## Documentation
- BLEEDING_ROOT_CAUSE_ANALYSIS.md: Technical analysis
- BLEEDING_FIX_APPLIED.md: Implementation summary
- FIX_DEPLOYMENT_CHECKLIST.md: Deployment steps
- BLEEDING_INCIDENT_SUMMARY.txt: Executive summary
- QUICK_REFERENCE.md: 1-page reference

## Next Steps
1. Deposit \$50-100 to Coinbase Advanced Trade
2. Restart bot with updated code
3. Monitor logs for positions \$2.00-\$100.00
4. Verify no trades when balance < \$25"

# Show commit result
echo "=== COMMIT RESULT ==="
git log -1 --oneline
echo ""
echo "=== PUSHING TO ORIGIN ==="

# Push to origin
git push origin main

echo ""
echo "=== PUSH COMPLETE ==="
git log -1 --stat
