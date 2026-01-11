#!/bin/bash
# Quick script to check if NIJA has made profitable trades
# across all accounts (Master: Kraken, Coinbase, Alpaca; Users)

echo "=================================================="
echo "  NIJA Profitable Trades Status Check"
echo "=================================================="
echo ""

# Run the comprehensive check
python3 check_profitable_trades_all_accounts.py

echo ""
echo "=================================================="
echo "For detailed documentation, see:"
echo "  ANSWER_HAS_NIJA_MADE_PROFITABLE_TRADES.md"
echo "=================================================="
