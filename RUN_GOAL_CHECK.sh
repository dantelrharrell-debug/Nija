#!/bin/bash
# Quick Goal Assessment Script
# Checks balance, connection, and determines if goal is achievable

echo "🎯 Running NIJA Goal Assessment..."
echo ""

cd /workspaces/Nija
python3 assess_goal_now.py

echo ""
echo "✅ Assessment complete!"
