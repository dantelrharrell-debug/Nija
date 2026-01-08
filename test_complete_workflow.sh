#!/bin/bash
# Complete workflow test for user management

echo "=========================================="
echo "NIJA Multi-User System - Complete Test"
echo "=========================================="
echo ""

echo "Step 1: Initialize system with first user..."
python init_user_system.py
echo ""

echo "Step 2: Check user status..."
python manage_user_daivon.py status
echo ""

echo "Step 3: Disable user trading..."
python manage_user_daivon.py disable
echo ""

echo "Step 4: Verify disabled status..."
python manage_user_daivon.py status
echo ""

echo "Step 5: Re-enable user trading..."
python manage_user_daivon.py enable
echo ""

echo "Step 6: View detailed information..."
python manage_user_daivon.py info
echo ""

echo "=========================================="
echo "✅ Complete workflow test finished!"
echo "=========================================="
