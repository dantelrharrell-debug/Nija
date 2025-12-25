#!/bin/bash
# Quick liquidation script - sells all crypto to USD

echo "=================================="
echo "🔄 NIJA LIQUIDATION SCRIPT"
echo "=================================="
echo ""
echo "This will:"
echo "  1. Check your current crypto holdings"
echo "  2. Sell all crypto for USD"
echo "  3. Free up capital for trading"
echo ""
echo "Press ENTER to continue (or Ctrl+C to cancel)"
read

cd /workspaces/Nija
python3 liquidate_all_crypto.py
