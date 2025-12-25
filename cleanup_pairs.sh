#!/bin/bash
git add bot/trading_strategy.py
git commit -m "✅ Remove invalid Coinbase pairs (MATIC, THETA, GALA, ENJ, RUNE, QNT)"
git push origin main
echo "Cleaned up invalid pairs - bot will scan 50 verified markets error-free"
