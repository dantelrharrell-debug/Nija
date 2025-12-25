#!/usr/bin/env python3
"""
Simple portfolio check - lists all portfolios and their balances.
"""
import os
import sys
from pathlib import Path
from coinbase.rest import RESTClient

# Load .env
dotenv_path = Path('.env')
if dotenv_path.exists():
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                if not os.getenv(key.strip()):
                    os.environ[key.strip()] = val.strip()

api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

if not api_key or not api_secret:
    print("❌ Missing credentials in env or .env")
    sys.exit(1)

print("\n🔐 Initializing Coinbase client...")
try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    print("✅ Connected to Coinbase\n")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    sys.exit(1)

# Get portfolios
try:
    print("📡 Fetching portfolios...")
    resp = client.get_portfolios()
    
    # Handle response format
    if isinstance(resp, dict) and 'portfolios' in resp:
        portfolios = resp['portfolios']
    elif isinstance(resp, list):
        portfolios = resp
    else:
        portfolios = [resp] if resp else []
    
    print(f"\n✅ Found {len(portfolios)} portfolio(s):\n")
    print("=" * 80)
    
    for i, p in enumerate(portfolios, 1):
        name = p.get('name', 'Unknown')
        portfolio_id = p.get('id', 'N/A')
        ptype = p.get('type', 'N/A')
        
        print(f"\n{i}. {name}")
        print(f"   Type: {ptype}")
        print(f"   UUID: {portfolio_id}")
        
        # Get breakdown
        try:
            breakdown = client.get_portfolio_breakdown(portfolio_id)
            
            # Parse breakdown
            if isinstance(breakdown, dict):
                bd = breakdown
            elif isinstance(breakdown, list) and len(breakdown) > 0:
                bd = breakdown[0]
            else:
                bd = {}
            
            assets = bd.get('breakdown', [])
            usd_bal = usdc_bal = 0.0
            
            for asset in assets:
                if isinstance(asset, dict):
                    symbol = asset.get('asset', {}).get('symbol', '')
                    amount = float(asset.get('amount', 0))
                    if symbol == 'USD':
                        usd_bal = amount
                    elif symbol == 'USDC':
                        usdc_bal = amount
            
            total = usd_bal + usdc_bal
            print(f"   💵 Balance: ${total:.2f}")
            if total > 0:
                print(f"   ✅ FUNDED - Copy UUID above for COINBASE_RETAIL_PORTFOLIO_ID")
            
        except Exception as e:
            print(f"   ⚠️ Could not fetch balance: {e}")
    
    print("\n" + "=" * 80)
    print("\n📌 To use a funded portfolio for trading:")
    print("   export COINBASE_RETAIL_PORTFOLIO_ID=\"<uuid-from-above>\"")
    print("   Then restart the bot.\n")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
