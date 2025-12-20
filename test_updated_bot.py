#!/usr/bin/env python3
"""
Test that the updated bot can now see the $155.46
"""
import os
import sys
from pathlib import Path

# Load .env first
dotenv_path = Path('.env')
if dotenv_path.exists():
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                if not os.getenv(key.strip()):
                    os.environ[key.strip()] = val.strip()

sys.path.insert(0, '/workspaces/Nija/bot')

from broker_manager import CoinbaseBroker

print("\n" + "="*80)
print("🧪 TESTING UPDATED BOT BROKER MANAGER")
print("="*80)

print("\n1️⃣ Connecting to Coinbase...")
broker = CoinbaseBroker()

if not broker.connect():
    print("❌ Connection failed!")
    sys.exit(1)

print("\n2️⃣ Fetching account balance (using portfolio breakdown API)...")
balance = broker.get_account_balance()

print("\n" + "="*80)
print("📊 RESULT")
print("="*80)

trading_balance = balance.get('trading_balance', 0)

if trading_balance >= 50:
    print(f"\n   🎉 SUCCESS! Bot can see ${trading_balance:.2f}!")
    print(f"   ✅ Bot is ready to trade")
    print(f"\n   💡 Breakdown:")
    print(f"      USD:  ${balance.get('usd', 0):.2f}")
    print(f"      USDC: ${balance.get('usdc', 0):.2f}")
    print(f"      Crypto holdings: {len(balance.get('crypto', {}))}")
    print(f"\n   🚀 READY TO DEPLOY!")
elif trading_balance > 0:
    print(f"\n   ⚠️  Bot can see ${trading_balance:.2f}")
    print(f"   ⚠️  This is low but should work")
else:
    print(f"\n   ❌ Bot still sees $0.00")
    print(f"   ❌ Something is still wrong")

print("\n" + "="*80 + "\n")
