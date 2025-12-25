#!/bin/bash
echo "Making scripts executable..."
chmod +x RUN_FIX_NOW.sh
chmod +x RUN_FIX_AND_START.sh
chmod +x START_SELLING_NOW.sh
chmod +x start.sh

echo "✅ All scripts ready!"
echo ""
echo "Now running diagnostic to find your $164.45..."
echo ""

python3 FIND_AND_FIX_NOW.py
