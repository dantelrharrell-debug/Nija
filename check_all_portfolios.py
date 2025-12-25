#!/usr/bin/env python3
"""
Check balances across ALL Coinbase Advanced Trade portfolios
Shows which portfolio has your funds
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
    print("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET in .env")
    sys.exit(1)

# Normalize PEM format
if '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

print("\n" + "="*80)
print("💼 ALL COINBASE ADVANCED TRADE PORTFOLIOS")
print("="*80)

try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    # Get all portfolios
    print("\n🔍 Fetching portfolios...")
    portfolios_response = client.get_portfolios()
    
    if not hasattr(portfolios_response, 'portfolios'):
        print("❌ No portfolios found or API error")
        sys.exit(1)
    
    portfolios = portfolios_response.portfolios
    print(f"✅ Found {len(portfolios)} portfolio(s)\n")
    
    total_usd = 0.0
    total_crypto_value = 0.0
    portfolio_details = []
    
    for idx, portfolio in enumerate(portfolios, 1):
        portfolio_name = portfolio.name
        portfolio_uuid = portfolio.uuid
        portfolio_type = portfolio.type if hasattr(portfolio, 'type') else 'UNKNOWN'
        
        print(f"\n{'='*80}")
        print(f"📁 PORTFOLIO #{idx}: {portfolio_name}")
        print(f"{'='*80}")
        print(f"   UUID: {portfolio_uuid}")
        print(f"   Type: {portfolio_type}")
        
        # Get accounts for this portfolio
        try:
            accounts_response = client.get_accounts(portfolio_uuid=portfolio_uuid)
            accounts = accounts_response.accounts if hasattr(accounts_response, 'accounts') else []
            
            portfolio_usd = 0.0
            portfolio_crypto = 0.0
            holdings = []
            
            print(f"\n   💰 Holdings:")
            print(f"   {'-'*76}")
            
            found_balance = False
            for account in accounts:
                currency = account.currency
                available = float(account.available_balance.value) if hasattr(account.available_balance, 'value') else 0.0
                
                if available > 0.01:  # Only show meaningful balances
                    found_balance = True
                    if currency == 'USD' or currency == 'USDC':
                        portfolio_usd += available
                        print(f"   💵 {currency:10s} ${available:,.2f}")
                    else:
                        portfolio_crypto += available  # Approximate
                        print(f"   🪙 {currency:10s} {available:.8f}")
                    
                    holdings.append({
                        'currency': currency,
                        'amount': available
                    })
            
            if not found_balance:
                print(f"   ❌ No balances (empty portfolio)")
            
            total_usd += portfolio_usd
            total_crypto_value += portfolio_crypto
            
            portfolio_details.append({
                'name': portfolio_name,
                'uuid': portfolio_uuid,
                'usd': portfolio_usd,
                'crypto': portfolio_crypto,
                'holdings': holdings
            })
            
        except Exception as e:
            print(f"   ⚠️  Error fetching accounts: {str(e)}")
    
    # Summary
    print(f"\n\n{'='*80}")
    print("📊 SUMMARY")
    print(f"{'='*80}")
    
    print(f"\n   Total USD/USDC across all portfolios: ${total_usd:,.2f}")
    
    if total_crypto_value > 0:
        print(f"   Total crypto holdings (count): {total_crypto_value:.2f} positions")
    
    # Recommendations
    print(f"\n\n{'='*80}")
    print("💡 RECOMMENDATIONS")
    print(f"{'='*80}")
    
    nija_portfolio = None
    default_portfolio = None
    
    for p in portfolio_details:
        if 'NIJA' in p['name'].upper():
            nija_portfolio = p
        if 'DEFAULT' in p['name'].upper():
            default_portfolio = p
    
    if nija_portfolio and default_portfolio:
        if default_portfolio['usd'] > 0 and nija_portfolio['usd'] == 0:
            print(f"\n   ⚠️  YOUR FUNDS ARE IN DEFAULT PORTFOLIO!")
            print(f"   💰 Default has: ${default_portfolio['usd']:,.2f}")
            print(f"   📭 NIJA has: ${nija_portfolio['usd']:,.2f}")
            print(f"\n   🔄 TRANSFER FUNDS:")
            print(f"      1. Go to Coinbase Advanced Trade")
            print(f"      2. Click 'Portfolios' (top right)")
            print(f"      3. Select 'Default' portfolio")
            print(f"      4. Click 'Transfer' → Select 'NIJA' portfolio")
            print(f"      5. Transfer ${default_portfolio['usd']:,.2f}")
            print(f"\n   ✅ After transfer, bot will see funds in NIJA portfolio")
        elif nija_portfolio['usd'] > 0:
            print(f"\n   ✅ FUNDS IN NIJA PORTFOLIO: ${nija_portfolio['usd']:,.2f}")
            print(f"   ✅ Bot should be able to trade with these funds")
    elif total_usd == 0:
        print(f"\n   ❌ NO USD/USDC FOUND IN ANY PORTFOLIO")
        print(f"      - Deposit funds to Coinbase Advanced Trade")
        print(f"      - Recommended: $50-100 minimum for profitable trading")
    
    print(f"\n{'='*80}\n")

except Exception as e:
    print(f"\n❌ ERROR: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
