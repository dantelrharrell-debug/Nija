#!/usr/bin/env python3
"""Quick check of current status after liquidation attempt"""
import os
import sys
from coinbase.rest import RESTClient

# Load .env file manually if dotenv not available
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

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n")

if not api_key or not api_secret:
    print("❌ Missing credentials")
    sys.exit(1)

client = RESTClient(api_key=api_key, api_secret=api_secret)

print("\n" + "="*60)
print("💰 CURRENT BALANCE STATUS")
print("="*60)

# Get portfolio
portfolios_resp = client.get_portfolios()
portfolios = getattr(portfolios_resp, 'portfolios', [])

default = None
for p in portfolios:
    if p.name == 'Default':
        default = p
        break

if not default:
    print("❌ No Default portfolio")
    sys.exit(1)

# Get breakdown
breakdown_resp = client.get_portfolio_breakdown(portfolio_uuid=default.uuid)
breakdown = getattr(breakdown_resp, 'breakdown', None)

if not breakdown:
    print("❌ No breakdown data")
    sys.exit(1)

spot = getattr(breakdown, 'spot_positions', [])

usd_total = 0
usdc_total = 0
crypto_count = 0
crypto_value = 0

print("\n📊 HOLDINGS:")
for pos in spot:
    asset = getattr(pos, 'asset', 'N/A')
    is_cash = getattr(pos, 'is_cash', False)
    crypto = getattr(pos, 'total_balance_crypto', 0)
    fiat = getattr(pos, 'total_balance_fiat', 0)
    
    if crypto > 0 or fiat > 0:
        if is_cash:
            if asset == 'USD':
                usd_total += fiat
                print(f"   💵 USD: ${fiat:.2f}")
            elif asset == 'USDC':
                usdc_total += fiat
                print(f"   💵 USDC: ${fiat:.2f}")
        else:
            crypto_count += 1
            crypto_value += fiat
            print(f"   🪙 {asset}: {crypto:.8f} (${fiat:.2f})")

print("\n" + "="*60)
print(f"📊 TOTALS:")
print(f"   USD:   ${usd_total:.2f}")
print(f"   USDC:  ${usdc_total:.2f}")
print(f"   Crypto: {crypto_count} positions (${crypto_value:.2f})")
print(f"   TOTAL AVAILABLE: ${usd_total + usdc_total:.2f}")
print("="*60)

if usd_total + usdc_total >= 50:
    print("\n✅ SUFFICIENT BALANCE - Bot can trade!")
elif usd_total + usdc_total > 0:
    print(f"\n⚠️  INSUFFICIENT - Need ${50 - (usd_total + usdc_total):.2f} more to trade")
else:
    print("\n❌ NO CASH AVAILABLE")
print()
