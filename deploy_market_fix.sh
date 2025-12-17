#!/bin/bash
# Fix market fetch timeout issue

git add bot/trading_strategy.py
git commit -m "🔧 Fix: Use curated 50-market list instead of hanging API fetch"
git push origin main

echo "✅ Deployed curated market list - bot will scan 50 top crypto pairs"
