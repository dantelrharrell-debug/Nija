#!/usr/bin/env python3
"""
COMPREHENSIVE STATUS CHECK - Balance, Holdings, Goal Analysis
Run sell_all_crypto_now.py and assess goal progress
"""
import os
import sys
import subprocess
from dotenv import load_dotenv

load_dotenv()

print("\n" + "="*80)
print("🎯 NIJA COMPREHENSIVE STATUS & GOAL CHECK")
print("="*80 + "\n")

# Step 1: Run auto-sell script
print("Step 1: Checking & Selling Crypto Holdings")
print("-" * 80)
try:
    result = subprocess.run(
        ["python3", "auto_sell_all_crypto.py"],
        capture_output=True,
        text=True,
        timeout=60
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"⚠️ Warning: {result.stderr}")
except Exception as e:
    print(f"⚠️ Could not auto-sell: {e}")
    print("   Run manually: python3 sell_all_crypto_now.py")

print("\n" + "="*80)

# Step 2: Check current balance
print("Step 2: Checking Account Balance")
print("-" * 80)
try:
    result = subprocess.run(
        ["python3", "assess_goal_now.py"],
        capture_output=True,
        text=True,
        timeout=60
    )
    print(result.stdout)
except Exception as e:
    print(f"Error checking balance: {e}")

print("\n" + "="*80)

# Step 3: Calculate path to $1000/day
print("Step 3: Path to $1000/Day Analysis")
print("-" * 80)
try:
    result = subprocess.run(
        ["python3", "PATH_TO_1000_A_DAY.py"],
        capture_output=True,
        text=True,
        timeout=30
    )
    print(result.stdout)
except Exception as e:
    print(f"Error calculating path: {e}")

print("\n" + "="*80)
print("✅ COMPREHENSIVE CHECK COMPLETE")
print("="*80 + "\n")
