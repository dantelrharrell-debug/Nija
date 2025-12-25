#!/usr/bin/env python3
"""
Access funds using portfolio breakdown API (the one that works!)
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
print("✅ ACCESSING FUNDS VIA PORTFOLIO BREAKDOWN API")
print("="*80)

try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    # Get Default portfolio
    portfolios_resp = client.get_portfolios()
    portfolios = getattr(portfolios_resp, 'portfolios', [])
    
    default_portfolio = None
    for p in portfolios:
        if p.name == 'Default':
            default_portfolio = p
            break
    
    if not default_portfolio:
        print("❌ Could not find Default portfolio")
        sys.exit(1)
    
    print(f"\n📁 Portfolio: {default_portfolio.name}")
    print(f"   UUID: {default_portfolio.uuid}")
    
    # Use the portfolio breakdown API (this one works!)
    print(f"\n💰 GETTING BREAKDOWN (the working method)...")
    print("-" * 80)
    
    breakdown_resp = client.get_portfolio_breakdown(portfolio_uuid=default_portfolio.uuid)
    
    # Extract balances - response is an object, not dict
    breakdown = getattr(breakdown_resp, 'breakdown', None)
    if not breakdown:
        print(f"❌ No breakdown data returned")
        sys.exit(1)
    
    portfolio_balances = getattr(breakdown, 'portfolio_balances', None)
    spot_positions = getattr(breakdown, 'spot_positions', [])
    
    # Total balance
    total_balance = getattr(portfolio_balances, 'total_balance', None)
    total_value = float(getattr(total_balance, 'value', 0)) if total_balance else 0.0
    
    print(f"\n💰 Total Portfolio Value: ${total_value:.2f}")
    
    # Show individual positions
    print(f"\n📊 POSITIONS:")
    print("-" * 80)
    
    tradable_usd = 0.0
    
    for position in spot_positions:
        asset = getattr(position, 'asset', 'N/A')
        available_fiat = getattr(position, 'available_to_trade_fiat', 0)
        total_balance_fiat = getattr(position, 'total_balance_fiat', 0)
        is_cash = getattr(position, 'is_cash', False)
        
        if total_balance_fiat > 0.01 or available_fiat > 0.01:
            status = "✅ TRADABLE" if available_fiat > 0 else "⚠️  LOCKED"
            
            if is_cash and asset in ['USD', 'USDC']:
                tradable_usd += available_fiat
                print(f"   💵 {asset:8s} ${total_balance_fiat:>10.2f} (Available: ${available_fiat:>10.2f}) {status}")
            else:
                total_crypto = getattr(position, 'total_balance_crypto', 0)
                print(f"   🪙 {asset:8s} ${total_balance_fiat:>10.2f} ({total_crypto:.8f} {asset})")
    
    print("-" * 80)
    print(f"   💰 Total Tradable USD/USDC: ${tradable_usd:.2f}")
    
    print("\n\n" + "="*80)
    print("📊 BOT READINESS")
    print("="*80)
    
    if tradable_usd >= 50:
        print(f"\n   🎉 EXCELLENT! You have ${tradable_usd:.2f} available!")
        print(f"   ✅ Bot is ready to trade")
        print(f"\n   💡 Recommended settings:")
        print(f"      - Position size: $15-20 per trade")
        print(f"      - This allows ~{int(tradable_usd / 15)} positions")
        print(f"\n   🚀 NEXT STEPS:")
        print(f"      1. Bot will use portfolio breakdown API to access funds")
        print(f"      2. Deploy to Railway")
        print(f"      3. Start trading!")
    elif tradable_usd >= 10:
        print(f"\n   ✅ You have ${tradable_usd:.2f} available")
        print(f"   ⚠️  This is low - recommend depositing more")
        print(f"   💡 With this amount:")
        print(f"      - Use $5-10 per trade")
        print(f"      - Fees will reduce profits significantly")
    else:
        print(f"\n   ❌ Only ${tradable_usd:.2f} available for trading")
        print(f"   ❌ Need at least $10 to start")
        
        if total_value > tradable_usd:
            print(f"\n   💡 You have ${total_value:.2f} total but only ${tradable_usd:.2f} is available")
            print(f"   💡 Some funds may be:")
            print(f"      - Staked (ATOM, ETH shown above)")
            print(f"      - In pending orders")
            print(f"      - Locked in other contracts")
    
    print("\n" + "="*80 + "\n")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
