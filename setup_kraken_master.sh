#!/bin/bash
# Quick launcher for Kraken Master Account Setup Guide

echo ""
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃         KRAKEN MASTER ACCOUNT SETUP GUIDE                      ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

# Check if running in correct directory
if [ ! -f "setup_kraken_master.py" ]; then
    echo "❌ Error: Must run from NIJA repository root directory"
    echo "   Current directory: $(pwd)"
    echo "   Please cd to NIJA directory first"
    exit 1
fi

# Try to find Python
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "❌ Error: Python not found"
    echo "   Please install Python 3.11 or higher"
    exit 1
fi

echo "Using Python: $($PYTHON --version)"
echo ""

# Run the setup script
$PYTHON setup_kraken_master.py
exit $?
