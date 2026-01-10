#!/bin/bash
# Quick Start Trading - Verify setup and optionally start bot

echo "=========================================="
echo "  NIJA QUICK START TRADING"
echo "=========================================="
echo ""

# Step 1: Verify setup
echo "Step 1: Verifying trading setup..."
echo ""
python3 verify_trading_setup.py

echo ""
echo "=========================================="
echo ""
read -p "Do you want to start trading now? (yes/no): " answer

if [ "$answer" = "yes" ] || [ "$answer" = "y" ] || [ "$answer" = "YES" ] || [ "$answer" = "Y" ]; then
    echo ""
    echo "=========================================="
    echo "  STARTING NIJA TRADING BOT"
    echo "=========================================="
    echo ""
    echo "The bot will now start trading for:"
    echo "  - Master accounts (Coinbase, Kraken, Alpaca, OKX)"
    echo "  - User #1 (Daivon Frazier on Kraken)"
    echo ""
    echo "Trading will begin within 30-90 seconds."
    echo "Press Ctrl+C to stop the bot."
    echo ""
    echo "=========================================="
    echo ""
    
    # Start the bot
    ./start.sh
else
    echo ""
    echo "Trading not started. To start later, run:"
    echo "  ./start.sh"
    echo ""
    echo "Or on Railway:"
    echo "  Deploy the latest code to Railway"
    echo ""
fi
