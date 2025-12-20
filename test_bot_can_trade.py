#!/usr/bin/env python3
"""
Test that bot can now see and access the $156.97 in Default portfolio
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

if '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

print("\n" + "="*80)
print("✅ TESTING BOT ACCESS TO DEFAULT PORTFOLIO")
print("="*80)

try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    # Get Default portfolio UUID
    portfolios_resp = client.get_portfolios()
    portfolios = getattr(portfolios_resp, 'portfolios', [])
    
    default_uuid = None
    for p in portfolios:
        if p.name == 'Default':
            default_uuid = p.uuid
            break
    
    if not default_uuid:
        print("❌ Could not find Default portfolio")
        sys.exit(1)
    
    print(f"\n📁 Default Portfolio UUID: {default_uuid}")
    
    # Get accounts in Default portfolio
    print(f"\n💰 CHECKING BALANCES IN DEFAULT PORTFOLIO...")
    print("-" * 80)
    
    accounts_resp = client.get_accounts(portfolio_uuid=default_uuid)
    accounts = getattr(accounts_resp, 'accounts', [])
    
    total_usd = 0.0
    tradable_assets = []
    
    for acc in accounts:
        currency = getattr(acc, 'currency', None)
        bal_obj = getattr(acc, 'available_balance', None)
        available = float(getattr(bal_obj, 'value', 0)) if bal_obj else 0.0
        
        if available > 0.01:
            if currency in ['USD', 'USDC']:
                total_usd += available
                tradable_assets.append({
                    'currency': currency,
                    'amount': available
                })
                print(f"   💵 {currency:8s} ${available:>12.2f}  ← AVAILABLE FOR TRADING")
            elif available > 0.001:  # Crypto holdings
                print(f"   🪙 {currency:8s} {available:>12.8f}")
    
    print("-" * 80)
    print(f"   💰 Total USD/USDC: ${total_usd:.2f}")
    
    print("\n\n" + "="*80)
    print("📊 BOT TRADING STATUS")
    print("="*80)
    
    if total_usd >= 10:
        print(f"\n   ✅ SUCCESS! Bot can see ${total_usd:.2f}")
        print(f"   ✅ This is enough to start trading!")
        print(f"\n   💡 Recommended first trade size: ${min(total_usd * 0.1, 20):.2f}")
        print(f"   💡 Keep $10-15 per trade to avoid fee issues")
        print(f"\n   🚀 READY TO START!")
        print(f"\n   Next steps:")
        print(f"   1. Deploy bot to Railway")
        print(f"   2. Bot will automatically trade with Default portfolio")
        print(f"   3. Monitor trades via: python3 check_current_positions.py")
    elif total_usd >= 5:
        print(f"\n   ⚠️  Bot can see ${total_usd:.2f} but it's low")
        print(f"   ⚠️  Recommended minimum: $50 for profitable trading")
        print(f"   ⚠️  With ${total_usd:.2f}, fees will eat most profits")
    else:
        print(f"\n   ❌ Only ${total_usd:.2f} available")
        print(f"   ❌ Need at least $10 to trade")
    
    print("\n" + "="*80 + "\n")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
