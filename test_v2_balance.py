#!/usr/bin/env python3
"""Test NIJA balance detection with v2 API"""

import os
import sys

# Load .env
if os.path.isfile(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value

sys.path.insert(0, 'bot')

from broker_manager import CoinbaseBroker

print("="*70)
print("🧪 TESTING NIJA BALANCE DETECTION (v2 API)")
print("="*70)
print()

coinbase = CoinbaseBroker()

print("🔌 Connecting to Coinbase Advanced Trade...")
success = coinbase.connect()
print()

if success:
    print("✅ Connection successful!")
    print()
    print("💰 Fetching account balance...")
    print()
    
    balance = coinbase.get_account_balance()
    
    print()
    print("="*70)
    print("📊 BALANCE TEST RESULT:")
    print("="*70)
    print(f"USD:             ${balance['usd']:.2f}")
    print(f"USDC:            ${balance['usdc']:.2f}")
    print(f"TRADING BALANCE: ${balance['trading_balance']:.2f}")
    print(f"Crypto Holdings: {len(balance['crypto'])} assets")
    print("="*70)
    print()
    
    if balance['trading_balance'] >= 35:
        print("✅✅✅ SUCCESS! Balance detected!")
        print(f"✅ NIJA can trade with ${balance['trading_balance']:.2f}")
        print()
        print("🚀 READY TO START TRADING!")
    elif balance['trading_balance'] > 0:
        print(f"⚠️  Balance detected but low: ${balance['trading_balance']:.2f}")
        print("   Expected ~$35-$48 based on iPad display")
    else:
        print("❌ Balance still showing $0.00")
        print("   The v2 API fix may need additional work")
else:
    print("❌ Connection failed")
    print("   Check API credentials in .env file")
