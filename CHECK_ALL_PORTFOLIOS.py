#!/usr/bin/env python3
"""
Check ALL Coinbase portfolios for crypto positions
"""

import sys
import os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("🔍 SCANNING ALL COINBASE PORTFOLIOS")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# First, get ALL portfolios
print("📋 Fetching all portfolios...")
try:
    portfolios_resp = client.get_portfolios()
    portfolios = getattr(portfolios_resp, 'portfolios', [])
    
    print(f"\n✅ Found {len(portfolios)} portfolio(s):\n")
    
    for portfolio in portfolios:
        name = getattr(portfolio, 'name', 'Unknown')
        portfolio_id = getattr(portfolio, 'uuid', 'Unknown')
        portfolio_type = getattr(portfolio, 'type', 'Unknown')
        deleted = getattr(portfolio, 'deleted', False)
        
        if deleted:
            continue
            
        print(f"  • {name}")
        print(f"    ID: {portfolio_id}")
        print(f"    Type: {portfolio_type}")
        print()
        
except Exception as e:
    print(f"❌ Error fetching portfolios: {e}")
    portfolios = []

# Now get ALL accounts across all portfolios
print("=" * 80)
print("💰 CHECKING ALL ACCOUNTS IN ALL PORTFOLIOS")
print("=" * 80)

accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

# Group by portfolio
portfolio_data = {}

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    acc_type = getattr(acc, 'type', 'UNKNOWN')
    acc_uuid = getattr(acc, 'uuid', 'unknown')
    
    # Try to get portfolio info
    # Coinbase API doesn't always expose portfolio_id in accounts
    # We'll categorize by account type
    
    if not curr or not avail_obj:
        continue
    
    amount = float(getattr(avail_obj, 'value', 0))
    
    if amount == 0:
        continue
    
    # Determine portfolio category
    if acc_type == 'ACCOUNT':
        portfolio_name = 'Consumer Wallet'
    else:
        portfolio_name = 'Advanced Trade'
    
    if portfolio_name not in portfolio_data:
        portfolio_data[portfolio_name] = {
            'cash': {},
            'crypto': {}
        }
    
    if curr in ['USD', 'USDC']:
        portfolio_data[portfolio_name]['cash'][curr] = amount
    else:
        portfolio_data[portfolio_name]['crypto'][curr] = amount

# Display findings
print("\n")
for portfolio_name, data in portfolio_data.items():
    print("=" * 80)
    print(f"📊 {portfolio_name.upper()}")
    print("=" * 80)
    
    cash = data['cash']
    crypto = data['crypto']
    
    if cash:
        print("\n💵 Cash Holdings:")
        for curr, amount in cash.items():
            print(f"  {curr}: ${amount:.2f}")
    
    if crypto:
        print("\n🪙 Crypto Holdings:")
        for curr, amount in crypto.items():
            print(f"  {curr}: {amount:.8f}")
    
    if not cash and not crypto:
        print("\n✅ Empty")
    
    print()

# Calculate totals
total_cash = 0
total_crypto_positions = 0

for data in portfolio_data.values():
    for amount in data['cash'].values():
        total_cash += amount
    total_crypto_positions += len(data['crypto'])

print("=" * 80)
print("📊 GRAND TOTALS")
print("=" * 80)
print(f"Total Cash: ${total_cash:.2f}")
print(f"Total Crypto Positions: {total_crypto_positions}")
print("=" * 80)

# Identify where crypto is stuck
crypto_in_consumer = portfolio_data.get('Consumer Wallet', {}).get('crypto', {})
crypto_in_advanced = portfolio_data.get('Advanced Trade', {}).get('crypto', {})

if crypto_in_consumer:
    print("\n🚨 CRYPTO STUCK IN CONSUMER WALLET:")
    print("   Bot CANNOT sell from Consumer wallet via API!")
    print("\n   Options:")
    print("   1. MANUAL SALE: Sell on Coinbase.com manually")
    print("   2. TRANSFER: Move to Advanced Trade, then bot can sell")
    print(f"\n   Positions in Consumer wallet: {list(crypto_in_consumer.keys())}")

if crypto_in_advanced:
    print("\n✅ CRYPTO IN ADVANCED TRADE:")
    print("   Bot CAN sell these positions!")
    print(f"\n   Positions: {list(crypto_in_advanced.keys())}")
    print("\n   Action: Bot should be selling these automatically.")
    print("   If not selling, there may be a code issue.")

print("\n" + "=" * 80)
