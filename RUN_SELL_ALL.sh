#!/bin/bash
# Run comprehensive check and auto-sell

echo "🔍 Checking all funds and selling crypto holdings..."
echo ""

cd /workspaces/Nija || exit 1

# Run the auto-sell script
python3 auto_sell_all_crypto.py

# Then show final status
echo ""
echo "📊 Running final balance check..."
python3 assess_goal_now.py

echo ""
echo "✅ Complete!"
