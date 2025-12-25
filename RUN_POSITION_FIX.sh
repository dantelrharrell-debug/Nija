#!/bin/bash

echo "========================================================================"
echo "🚨 EMERGENCY POSITION DIAGNOSTIC & FIX"
echo "========================================================================"
echo ""

# Step 1: Compare positions
echo "📊 Step 1: Checking position tracking vs actual holdings..."
echo "------------------------------------------------------------------------"
python3 COMPARE_POSITIONS.py
echo ""

# Step 2: Check what's really on Coinbase
echo "📊 Step 2: Deep check of all Coinbase positions..."
echo "------------------------------------------------------------------------"
python3 CHECK_POSITIONS_NOW.py
echo ""

# Step 3: Ask user if they want to liquidate
echo "========================================================================" 
echo "⚠️  CRITICAL DECISION POINT"
echo "========================================================================"
echo ""
echo "If you have crypto positions that bot isn't selling, you have 3 options:"
echo ""
echo "1. FORCE SELL ALL - Liquidate everything immediately"
echo "   Run: python3 FORCE_SELL_ALL_POSITIONS.py"
echo ""
echo "2. TRANSFER TO ADVANCED TRADE - If funds are in Consumer wallet"
echo "   Go to: https://www.coinbase.com/advanced-portfolio"
echo "   Transfer the $57.54 USDC to Advanced Trade"
echo ""
echo "3. WAIT - If positions need to reach +6% profit target"
echo "   Let bot continue managing them"
echo ""
echo "========================================================================"
echo "✅ Diagnostic complete. Choose your action above."
echo "========================================================================"
