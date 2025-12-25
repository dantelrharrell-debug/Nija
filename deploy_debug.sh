#!/bin/bash
# Deploy debug logging

git add bot/trading_strategy.py
git commit -m "🔍 Add debug logging to diagnose market scan hang"
git push origin main

echo "Deployed debug logging - watch Railway for detailed market scan progress"
