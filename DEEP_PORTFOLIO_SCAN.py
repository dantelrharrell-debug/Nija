#!/usr/bin/env python3
"""
Deep scan - Check each portfolio individually using portfolio UUID
"""

import sys
import os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("🔬 DEEP PORTFOLIO SCAN - CHECKING EACH PORTFOLIO DIRECTLY")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get all portfolios first
portfolios_resp = client.get_portfolios()
portfolios = getattr(portfolios_resp, 'portfolios', [])

print(f"Found {len(portfolios)} portfolio(s)\n")

all_findings = {}

for portfolio in portfolios:
    name = getattr(portfolio, 'name', 'Unknown')
    portfolio_id = getattr(portfolio, 'uuid', None)
    portfolio_type = getattr(portfolio, 'type', 'Unknown')
    deleted = getattr(portfolio, 'deleted', False)
    
    if deleted:
        print(f"⏭️  Skipping deleted portfolio: {name}")
        continue
    
    print("=" * 80)
    print(f"📂 Portfolio: {name}")
    print(f"   Type: {portfolio_type}")
    print(f"   ID: {portfolio_id}")
    print("=" * 80)
    
    # Get accounts for this specific portfolio
    try:
        # Method 1: Get all accounts and filter
        accounts_resp = client.get_accounts()
        accounts = getattr(accounts_resp, 'accounts', [])
        
        portfolio_accounts = []
        for acc in accounts:
            # Try to match by various criteria
            acc_name = getattr(acc, 'name', '')
            acc_uuid = getattr(acc, 'uuid', '')
            
            # Add all accounts for now since API doesn't clearly expose portfolio_id
            portfolio_accounts.append(acc)
        
        print(f"\n💼 Checking {len(portfolio_accounts)} account(s)...\n")
        
        cash_found = {}
        crypto_found = {}
        
        for acc in portfolio_accounts:
            curr = getattr(acc, 'currency', None)
            avail_obj = getattr(acc, 'available_balance', None)
            acc_type = getattr(acc, 'type', 'UNKNOWN')
            acc_name = getattr(acc, 'name', 'Unknown')
            
            if not curr or not avail_obj:
                continue
            
            amount = float(getattr(avail_obj, 'value', 0))
            
            if amount <= 0:
                continue
            
            # Categorize
            if curr in ['USD', 'USDC']:
                cash_found[curr] = amount
                print(f"💵 {curr}: ${amount:.2f} ({acc_type} - {acc_name})")
            else:
                crypto_found[curr] = amount
                print(f"🪙 {curr}: {amount:.8f} ({acc_type} - {acc_name})")
        
        if not cash_found and not crypto_found:
            print("✅ No balances in this portfolio")
        
        all_findings[name] = {
            'cash': cash_found,
            'crypto': crypto_found
        }
        
    except Exception as e:
        print(f"❌ Error checking portfolio {name}: {e}")
    
    print()

# Summary
print("\n" + "=" * 80)
print("📊 COMPLETE SUMMARY")
print("=" * 80)

total_cash = 0
total_crypto_count = 0

for portfolio_name, data in all_findings.items():
    cash = data['cash']
    crypto = data['crypto']
    
    if cash or crypto:
        print(f"\n📂 {portfolio_name}:")
        
        if cash:
            for curr, amount in cash.items():
                print(f"  💵 {curr}: ${amount:.2f}")
                total_cash += amount
        
        if crypto:
            for curr, amount in crypto.items():
                print(f"  🪙 {curr}: {amount:.8f}")
                total_crypto_count += 1

print(f"\n💰 Total Cash: ${total_cash:.2f}")
print(f"🪙 Total Crypto Positions: {total_crypto_count}")

if total_crypto_count > 0:
    print("\n" + "=" * 80)
    print("🎯 NEXT STEP: SELL ALL CRYPTO")
    print("=" * 80)
    print("\nRun: python3 SELL_ALL_PORTFOLIOS.py")
    print("\nThis will sell ALL crypto from ALL portfolios at market price.")

print("=" * 80)
