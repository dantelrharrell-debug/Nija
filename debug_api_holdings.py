#!/usr/bin/env python3
"""
Deep dive into why API shows $0 when user sees 10 crypto in web interface
"""
import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔍 DEBUG: Why API shows $0 but web shows 10 crypto")
print("="*80 + "\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

print("Method 1: Get all accounts\n")
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

print(f"Total accounts returned: {len(accounts)}\n")

# Look for accounts with balances
found_crypto = {}
for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail = getattr(acc, 'available_balance', None)
    hold = getattr(acc, 'hold', None)
    
    avail_bal = float(getattr(avail, 'value', '0')) if avail else 0
    hold_bal = float(getattr(hold, 'value', '0')) if hold else 0
    total = avail_bal + hold_bal
    
    if total > 0:
        found_crypto[curr] = {
            'available': avail_bal,
            'hold': hold_bal,
            'total': total
        }

if found_crypto:
    print(f"✅ FOUND CRYPTO:\n")
    for curr, bal in found_crypto.items():
        print(f"   {curr}: {bal['total']} (Avail: {bal['available']}, Hold: {bal['hold']})")
else:
    print("❌ NO CRYPTO FOUND in get_accounts()\n")

print("\n" + "="*80)
print("Method 2: Try portfolio endpoint\n")

try:
    # Try to get portfolio data
    portfolios = client.list_portfolios()
    portfolio_list = getattr(portfolios, 'portfolios', [])
    print(f"Total portfolios: {len(portfolio_list)}\n")
    
    for port in portfolio_list:
        name = getattr(port, 'name', 'Unknown')
        uuid = getattr(port, 'uuid', 'Unknown')
        print(f"Portfolio: {name} ({uuid})")
        
except Exception as e:
    print(f"❌ Error getting portfolios: {e}\n")

print("\n" + "="*80)
print("Method 3: Check account summary\n")

try:
    summary = client.get_account_summary()
    print(f"Summary type: {type(summary)}")
    print(f"Summary: {summary}\n")
except Exception as e:
    print(f"Error getting summary: {e}\n")

print("\n" + "="*80)
print("Method 4: Try direct product query for known assets\n")

# Try querying for assets you said you have
test_assets = ['BTC', 'ETH', 'DOGE']
for asset in test_assets:
    try:
        symbol = f"{asset}-USD"
        product = client.get_product(symbol)
        print(f"✅ {symbol}: Current price = ${getattr(product, 'price', 'N/A')}")
    except Exception as e:
        print(f"❌ {symbol}: {e}")

print("\n" + "="*80)
print("DIAGNOSIS")
print("="*80)
print("""
If Method 1 shows NO CRYPTO but you see 10 in web interface:
→ The API key may have limited permissions
→ Or it's querying a different portfolio/sub-account
→ Need to check API key settings in Coinbase

If Method 4 shows prices but Method 1 shows $0:
→ API can talk to Coinbase
→ But isn't seeing YOUR holdings
→ Likely a portfolio/permissions issue
""")

print("="*80 + "\n")
