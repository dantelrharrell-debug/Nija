#!/usr/bin/env python3
"""
Find the $157.97 - check EVERYWHERE in Coinbase
"""
import os
import sys
import time
import jwt
import requests
from pathlib import Path
from coinbase.rest import RESTClient
from cryptography.hazmat.primitives import serialization

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
    print("❌ Missing credentials")
    sys.exit(1)

# Normalize PEM
if '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

print("\n" + "="*80)
print("🔍 FINDING YOUR $157.97")
print("="*80)

total_found = 0.0

# ============================================================================
# CHECK 1: Consumer Wallets (Coinbase.com main app)
# ============================================================================
print("\n1️⃣ CHECKING CONSUMER WALLETS (Coinbase.com)...")
print("-" * 80)

try:
    private_key = serialization.load_pem_private_key(api_secret.encode('utf-8'), password=None)
    
    uri = "GET api.coinbase.com/v2/accounts"
    payload = {
        'sub': api_key,
        'iss': 'coinbase-cloud',
        'nbf': int(time.time()),
        'exp': int(time.time()) + 120,
        'aud': ['coinbase-apis'],
        'uri': uri
    }
    token = jwt.encode(payload, private_key, algorithm='ES256', 
                      headers={'kid': api_key, 'nonce': str(int(time.time()))})
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    response = requests.get(f"https://api.coinbase.com/v2/accounts", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        accounts = data.get('data', [])
        
        consumer_usd = 0.0
        found_any = False
        
        for acc in accounts:
            currency_obj = acc.get('currency', {})
            currency = currency_obj.get('code', 'N/A') if isinstance(currency_obj, dict) else currency_obj
            balance_obj = acc.get('balance', {})
            balance = float(balance_obj.get('amount', 0) if isinstance(balance_obj, dict) else balance_obj or 0)
            name = acc.get('name', 'Unknown')
            
            if balance > 0.0001:  # Show anything
                found_any = True
                print(f"   💵 {currency:8s} {balance:>12.8f}  ('{name}')")
                if currency in ['USD', 'USDC']:
                    consumer_usd += balance
        
        if not found_any:
            print("   ❌ No balances in consumer wallets")
        else:
            print(f"\n   💰 Consumer USD Total: ${consumer_usd:.2f}")
            total_found += consumer_usd
            
            if consumer_usd > 150:
                print(f"\n   🎯 FOUND IT! ${consumer_usd:.2f} in CONSUMER WALLET")
                print(f"   ⚠️  Bot CANNOT trade these funds!")
                print(f"\n   HOW TO FIX:")
                print(f"   1. Open Coinbase app or website")
                print(f"   2. Go to 'Advanced Trade' or 'Pro'")
                print(f"   3. Click 'Deposit from Coinbase'")
                print(f"   4. Transfer ${consumer_usd:.2f} to Advanced Trade")
                print(f"   5. Bot will then see and trade with it!")
    else:
        print(f"   ⚠️  API error: {response.status_code}")
        
except Exception as e:
    print(f"   ❌ Error: {e}")

# ============================================================================
# CHECK 2: Advanced Trade Accounts
# ============================================================================
print("\n\n2️⃣ CHECKING ADVANCED TRADE...")
print("-" * 80)

try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    # Check all portfolios
    portfolios_resp = client.get_portfolios()
    portfolios = getattr(portfolios_resp, 'portfolios', [])
    
    advanced_usd = 0.0
    
    for portfolio in portfolios:
        pf_name = portfolio.name
        pf_uuid = portfolio.uuid
        
        print(f"\n   📁 Portfolio: {pf_name}")
        
        accounts_resp = client.get_accounts(portfolio_uuid=pf_uuid)
        accounts = getattr(accounts_resp, 'accounts', [])
        
        found_in_portfolio = False
        for account in accounts:
            currency = getattr(account, 'currency', 'N/A')
            available_obj = getattr(account, 'available_balance', None)
            available = float(getattr(available_obj, 'value', 0) or 0)
            
            if available > 0.0001:
                found_in_portfolio = True
                print(f"      💵 {currency:8s} {available:>12.8f}")
                if currency in ['USD', 'USDC']:
                    advanced_usd += available
        
        if not found_in_portfolio:
            print(f"      (empty)")
    
    print(f"\n   💰 Advanced Trade USD Total: ${advanced_usd:.2f}")
    total_found += advanced_usd
    
    if advanced_usd > 150:
        print(f"\n   🎯 FOUND IT! ${advanced_usd:.2f} in ADVANCED TRADE")
        print(f"   ✅ Bot CAN trade these funds!")
        
except Exception as e:
    print(f"   ❌ Error: {e}")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n\n" + "="*80)
print("📊 RESULTS")
print("="*80)
print(f"\n   Total found: ${total_found:.2f}")

if abs(total_found - 157.97) < 5:
    print(f"\n   ✅ FOUND YOUR $157.97!")
elif total_found == 0:
    print(f"\n   ❌ NO FUNDS FOUND")
    print(f"   Possible issues:")
    print(f"   - Using wrong API keys")
    print(f"   - Funds in different Coinbase account")
    print(f"   - API permissions not set correctly")
else:
    print(f"\n   ⚠️  Found ${total_found:.2f} (expected ~$157.97)")

print("\n" + "="*80 + "\n")
