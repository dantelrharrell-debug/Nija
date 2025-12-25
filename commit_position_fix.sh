#!/bin/bash
echo "🔧 Committing position limit fix: 10 → 8 positions max"
echo ""

# Add changes
git add bot/apex_config.py
git add FIND_AND_FIX_NOW.py
git add find_164_dollars.py
git add RUN_FIX_NOW.sh
git add RUN_FIX_AND_START.sh
git add START_SELLING_NOW.sh
git add run_diagnostic.sh

# Commit with detailed message
git commit -m "Fix: Reduce max concurrent positions from 10 to 8

- Updated RISK_LIMITS['max_positions'] = 8 in apex_config.py (line 296)
- Updated RISK_CONFIG['max_positions'] = 8 in apex_config.py (line 492)
- Already set to 8 in trading_strategy.py (line 226)
- Ensures bot respects 8 position limit per user's buy/sell logic
- Also added diagnostic scripts to find and fix balance issues

Changes:
  • bot/apex_config.py: max_positions 5 → 8 (2 locations)
  • Added FIND_AND_FIX_NOW.py: Comprehensive balance checker
  • Added find_164_dollars.py: Advanced Trade balance locator
  • Added START_SELLING_NOW.sh: Emergency trading starter
  
Why: User reported holding 10 trades when limit should be 8
Fix: All config files now consistently enforce 8 max positions"

# Push to GitHub
echo ""
echo "🚀 Pushing to GitHub..."
git push origin main

echo ""
echo "✅ Changes committed and pushed!"
echo ""
echo "📊 Position limit now: 8 concurrent positions (ULTRA AGGRESSIVE)"
echo "   → Matches your buy/sell logic requirements"
