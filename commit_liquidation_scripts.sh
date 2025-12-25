#!/bin/bash
# Commit emergency liquidation scripts

cd /workspaces/Nija

echo "📦 Staging files..."
git add check_crypto_positions.py emergency_liquidate.py take_profit_now.sh

echo "✅ Committing..."
git commit -m "Add emergency liquidation scripts and crypto position checker

- check_crypto_positions.py: Verify current holdings and values
- emergency_liquidate.py: Sell all crypto immediately without confirmation
- take_profit_now.sh: Convenience script to liquidate positions

Issue: Bot buying crypto but not selling - positions accumulate
Purpose: Manual liquidation tools while investigating automated sell logic"

echo "🚀 Pushing to GitHub..."
git push

echo "✅ Done!"
