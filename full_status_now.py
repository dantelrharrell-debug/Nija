#!/usr/bin/env python3
"""Complete status check - balance, positions, bot state"""
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, '/usr/src/app/bot')
from coinbase.rest import RESTClient

# Load .env manually
def load_env():
    env_path = '/workspaces/Nija/.env'
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

load_env()

print("\n" + "="*70)
print("🔍 NIJA COMPLETE STATUS CHECK")
print("="*70)

# 1. Check API credentials
api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n")

if not api_key or not api_secret:
    print("\n❌ CREDENTIALS: Missing API credentials")
else:
    print("\n✅ CREDENTIALS: API keys loaded")

# 2. Check balance
try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    portfolios_resp = client.get_portfolios()
    portfolios = getattr(portfolios_resp, 'portfolios', [])
    
    default = None
    for p in portfolios:
        if p.name == 'Default':
            default = p
            break
    
    if default:
        breakdown_resp = client.get_portfolio_breakdown(portfolio_uuid=default.uuid)
        breakdown = getattr(breakdown_resp, 'breakdown', None)
        spot = getattr(breakdown, 'spot_positions', [])
        
        usd_total = 0
        usdc_total = 0
        crypto_positions = []
        
        for pos in spot:
            asset = getattr(pos, 'asset', 'N/A')
            is_cash = getattr(pos, 'is_cash', False)
            crypto = getattr(pos, 'total_balance_crypto', 0)
            fiat = getattr(pos, 'total_balance_fiat', 0)
            
            if crypto > 0 or fiat > 0:
                if is_cash:
                    if asset == 'USD':
                        usd_total += fiat
                    elif asset == 'USDC':
                        usdc_total += fiat
                else:
                    crypto_positions.append(f"{asset}: {crypto:.8f} (${fiat:.2f})")
        
        print(f"\n💰 BALANCE:")
        print(f"   USD:   ${usd_total:.2f}")
        print(f"   USDC:  ${usdc_total:.2f}")
        print(f"   Total Cash: ${usd_total + usdc_total:.2f}")
        
        if crypto_positions:
            print(f"\n🪙 CRYPTO HOLDINGS ({len(crypto_positions)}):")
            for pos in crypto_positions:
                print(f"   {pos}")
        else:
            print("\n✅ No crypto holdings (all liquidated)")
        
        total_available = usd_total + usdc_total
        if total_available >= 50:
            print(f"\n✅ TRADING STATUS: Can trade (${total_available:.2f} ≥ $50)")
        else:
            print(f"\n⚠️  TRADING STATUS: Need ${50 - total_available:.2f} more")
        
except Exception as e:
    print(f"\n❌ BALANCE CHECK FAILED: {e}")

# 3. Check for open positions file
print("\n📁 POSITION FILES:")
position_paths = [
    '/usr/src/app/data/open_positions.json',
    '/workspaces/Nija/bot/data/open_positions.json',
    '/workspaces/Nija/data/open_positions.json'
]

found_positions = False
for path in position_paths:
    if os.path.exists(path):
        print(f"   ✅ Found: {path}")
        try:
            with open(path) as f:
                data = json.load(f)
                if data:
                    print(f"      Open positions: {len(data)}")
                    for symbol, pos in data.items():
                        print(f"         {symbol}: {pos.get('side')} @ ${pos.get('entry_price', 0):.2f}")
                else:
                    print("      No open positions")
        except Exception as e:
            print(f"      Error reading: {e}")
        found_positions = True

if not found_positions:
    print("   ℹ️  No position files found (bot not started or no positions)")

# 4. Check if bot is running
print("\n🤖 BOT STATUS:")
print("   ℹ️  Check Railway dashboard or run: ps aux | grep python")

print("\n" + "="*70)
print("💡 NEXT STEPS:")

if crypto_positions:
    print("   1. Run: python3 sell_now_auto.py  (liquidate crypto)")
    print("   2. Wait 10 seconds")
    print("   3. Run: python3 full_status_now.py  (verify)")
else:
    if total_available >= 50:
        print("   ✅ Ready to trade! Deploy bot to Railway")
    else:
        print("   ⚠️  Deposit more funds or lower threshold")

print("="*70 + "\n")
