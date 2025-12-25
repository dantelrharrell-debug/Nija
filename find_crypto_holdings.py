#!/usr/bin/env python3
"""
Find which account/portfolio holds the 11 crypto
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
from coinbase.rest import RESTClient

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

print("\n" + "="*80)
print("🔍 FINDING ACCOUNTS WITH CRYPTO")
print("="*80 + "\n")

# Get all accounts
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

print(f"Total accounts found: {len(accounts)}\n")

# Group by portfolio
portfolios = {}
crypto_found = {}

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    portfolio = getattr(acc, 'retail_portfolio_id', 'Unknown')
    platform = getattr(acc, 'platform', 'Unknown')
    avail = getattr(acc, 'available_balance', None)
    
    if not curr or not avail:
        continue
    
    bal = float(getattr(avail, 'value', '0'))
    
    if bal > 0:
        print(f"✅ {curr}: {bal}")
        print(f"   Portfolio: {portfolio}")
        print(f"   Platform:  {platform}\n")
        
        crypto_found[curr] = {
            'balance': bal,
            'portfolio': portfolio,
            'platform': platform
        }
        
        if portfolio not in portfolios:
            portfolios[portfolio] = []
        portfolios[portfolio].append(curr)

print("\n" + "="*80)
print("📊 SUMMARY BY PORTFOLIO")
print("="*80 + "\n")

for portfolio, cryptos in portfolios.items():
    print(f"Portfolio: {portfolio}")
    print(f"Crypto: {', '.join(cryptos)}\n")

if not crypto_found:
    print("❌ No crypto found with positive balance")
    print("\nThis means either:")
    print("1. The 11 crypto are in a DIFFERENT Coinbase account")
    print("2. They're in a CONSUMER wallet, not ADVANCED TRADE")
    print("3. They were already sold/transferred")
    print("\n⚠️  You may need to check a different API key")
else:
    print(f"\n✅ Found {len(crypto_found)} crypto holdings")
    print("Check Coinbase web interface to verify portfolio")

print("\n" + "="*80 + "\n")
