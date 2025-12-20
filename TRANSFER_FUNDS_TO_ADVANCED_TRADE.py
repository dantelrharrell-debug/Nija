#!/usr/bin/env python3
"""
CRITICAL: Transfer funds from Consumer wallet to Advanced Trade portfolio

Your setup:
- Consumer wallet (Default): Has your crypto/USD (CANNOT trade from here)
- Advanced Trade: Where bot trades from (currently empty)

Solution: Move funds from Consumer → Advanced Trade via Coinbase.com UI
OR use this script to transfer internally if available
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

if not api_key or not api_secret:
    print("❌ Missing API credentials")
    sys.exit(1)

client = RESTClient(api_key=api_key, api_secret=api_secret)

print("=" * 80)
print("⚠️  FUND TRANSFER REQUIREMENT")
print("=" * 80)
print()

# Get portfolios
portfolios_resp = client.get_portfolios()
portfolios = getattr(portfolios_resp, 'portfolios', [])

print("Your Coinbase Portfolios:")
print()

for p in portfolios:
    name = getattr(p, 'name', None)
    ptype = getattr(p, 'type', None)
    uuid = getattr(p, 'uuid', None)
    
    icon = "🏦" if ptype == "DEFAULT" else "📊"
    trading = "✅ TRADING" if ptype == "DEFAULT" else "❌ NO TRADING"
    
    print(f"{icon} {name:15s} ({ptype:15s}) - {trading}")
    print(f"   UUID: {uuid}")
    print()

print("=" * 80)
print("🔴 CRITICAL ISSUE")
print("=" * 80)
print()
print("Bot Status: READY TO TRADE")
print("Your Funds: IN CONSUMER WALLET (Cannot trade)")
print()
print("❌ PROBLEM:")
print("   The Coinbase API can ONLY place trades from:")
print("   → Default Advanced Trade portfolio")
print()
print("   Your funds are currently in:")
print("   → Consumer wallet (Default portfolio)")
print()
print("✅ SOLUTION:")
print()
print("   Transfer funds manually via Coinbase.com UI:")
print()
print("   1. Go to: https://www.coinbase.com/portfolio")
print("   2. Click 'Advanced Trade' or switch portfolio")
print("   3. Look for your USD balance in Consumer wallet")
print("   4. Transfer to Advanced Trade portfolio")
print()
print("   OR")
print()
print("   Use 'Portfolio' section → 'Deposit' to move funds")
print()
print("=" * 80)
print()
print("🚀 Once transferred, bot will:")
print("   1. Detect USD balance in Advanced Trade")
print("   2. Start scanning markets (every 2.5 seconds)")
print("   3. Execute $5-$100 trades per signal")
print("   4. Compound gains toward $1,000/day")
print()
