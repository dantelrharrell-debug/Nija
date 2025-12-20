#!/usr/bin/env python3
"""
Deep dive: Check pending deposits, holds, and all balance fields
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
print("🔍 DETAILED BALANCE INVESTIGATION")
print("="*80)

try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    # Get all accounts with FULL details
    print("\n📊 CHECKING ALL BALANCE FIELDS...")
    print("-" * 80)
    
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    usd_accounts = []
    
    for acc in accounts:
        currency = getattr(acc, 'currency', None)
        
        # Focus on USD/USDC accounts
        if currency in ['USD', 'USDC']:
            # Get all balance fields
            available_bal = getattr(acc, 'available_balance', None)
            available = float(getattr(available_bal, 'value', 0)) if available_bal else 0.0
            
            # Check for other balance types
            hold = 0.0
            total = 0.0
            
            # Try to get hold balance
            if hasattr(acc, 'hold'):
                hold_obj = getattr(acc, 'hold', None)
                hold = float(getattr(hold_obj, 'value', 0)) if hold_obj else 0.0
            
            # Print even if zero
            print(f"\n💵 {currency} Account:")
            print(f"   Available: ${available:.2f}")
            if hold > 0:
                print(f"   On Hold:   ${hold:.2f}")
            
            # Print ALL attributes to see what else is there
            print(f"\n   Raw attributes:")
            for attr_name in dir(acc):
                if not attr_name.startswith('_'):
                    try:
                        attr_val = getattr(acc, attr_name)
                        if not callable(attr_val):
                            print(f"      {attr_name}: {attr_val}")
                    except:
                        pass
    
    # Check for pending transactions/deposits
    print("\n\n🕐 CHECKING FOR PENDING DEPOSITS...")
    print("-" * 80)
    
    # Try to get transactions
    try:
        # This might not be available in all API versions
        if hasattr(client, 'get_transactions'):
            print("   Attempting to fetch recent transactions...")
            # We'd need an account ID for this
        else:
            print("   ⚠️  Transaction history not available via this API method")
    except Exception as e:
        print(f"   ⚠️  Could not fetch transactions: {e}")
    
    # Alternative: Check using portfolios breakdown
    print("\n\n📁 PORTFOLIO BREAKDOWN...")
    print("-" * 80)
    
    portfolios_resp = client.get_portfolios()
    portfolios = getattr(portfolios_resp, 'portfolios', [])
    
    for portfolio in portfolios:
        pf_name = portfolio.name
        pf_uuid = portfolio.uuid
        
        print(f"\n   Portfolio: {pf_name}")
        
        # Try to get portfolio breakdown
        try:
            if hasattr(client, 'get_portfolio_breakdown'):
                breakdown = client.get_portfolio_breakdown(portfolio_uuid=pf_uuid)
                print(f"      Breakdown: {breakdown}")
        except:
            pass
        
        # Check if portfolio object has total_balance or similar
        for attr in dir(portfolio):
            if 'balance' in attr.lower() or 'value' in attr.lower():
                if not attr.startswith('_'):
                    try:
                        val = getattr(portfolio, attr)
                        if not callable(val):
                            print(f"      {attr}: {val}")
                    except:
                        pass
    
    print("\n\n" + "="*80)
    print("💡 POSSIBLE EXPLANATIONS")
    print("="*80)
    
    print("\n1. PENDING DEPOSIT:")
    print("   Your $156.97 deposit might still be processing")
    print("   ACH deposits can take 5-7 business days to clear")
    print("   Web UI shows it, but API won't until it's fully cleared")
    
    print("\n2. DIFFERENT BALANCE TYPE:")
    print("   Funds might be in 'total' but not 'available'")
    print("   Check web UI if it says 'Pending' or 'On Hold'")
    
    print("\n3. COINBASE GLITCH:")
    print("   Sometimes there's a sync delay between web UI and API")
    print("   Wait 1-2 hours and check again")
    
    print("\n4. FUNDS IN COINBASE ONE/PRO:")
    print("   If funds are in old Coinbase Pro, they need manual migration")
    print("   Check: https://pro.coinbase.com")
    
    print("\n\n🔍 ACTION: Check your Coinbase web UI and answer:")
    print("   • Does it say 'Available' or 'Pending' next to $156.97?")
    print("   • When did you deposit the funds? (Date/time)")
    print("   • What deposit method? (Bank transfer, debit card, etc.)")
    
    print("\n" + "="*80 + "\n")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
