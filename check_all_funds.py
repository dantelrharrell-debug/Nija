#!/usr/bin/env python3
"""
Comprehensive check of ALL funds in Coinbase - both Consumer and Advanced Trade
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
print("🔍 COMPREHENSIVE FUND CHECK - ALL COINBASE ACCOUNTS")
print("="*80)

# ============================================================================
# CHECK 1: Consumer Wallets (v2 API) - NOT TRADABLE VIA API
# ============================================================================
print("\n📦 CONSUMER WALLETS (Coinbase.com) - NOT TRADABLE VIA BOT:")
print("-" * 80)

consumer_total = 0.0
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
        v2_accounts = data.get('data', [])
        
        for acc in v2_accounts:
            currency_obj = acc.get('currency', {})
            currency = currency_obj.get('code', 'N/A') if isinstance(currency_obj, dict) else currency_obj
            balance_obj = acc.get('balance', {})
            balance = float(balance_obj.get('amount', 0) if isinstance(balance_obj, dict) else balance_obj or 0)
            account_type = acc.get('type', 'unknown')
            name = acc.get('name', 'Unknown')
            
            if balance > 0:
                print(f"  • {currency:6s} ${balance:>10.2f}  [{account_type}] {name}")
                if currency in ['USD', 'USDC']:
                    consumer_total += balance
    else:
        print(f"  ⚠️  API returned status {response.status_code}")
        
except Exception as e:
    print(f"  ❌ Error: {e}")

print(f"\n  💰 Consumer Total (USD + USDC): ${consumer_total:.2f}")
if consumer_total > 0:
    print(f"  ⚠️  These funds CANNOT be used for bot trading!")
    print(f"  ➡️  Transfer to Advanced Trade: https://www.coinbase.com/advanced-portfolio")

# ============================================================================
# CHECK 2: Advanced Trade (v3 API) - TRADABLE VIA BOT
# ============================================================================
print("\n\n🚀 ADVANCED TRADE PORTFOLIO - TRADABLE VIA BOT:")
print("-" * 80)

advanced_total = 0.0
try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    accounts_resp = client.list_accounts() if hasattr(client, 'list_accounts') else client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    for account in accounts:
        currency = getattr(account, 'currency', None)
        available_obj = getattr(account, 'available_balance', None)
        available = float(getattr(available_obj, 'value', 0) or 0)
        account_type = getattr(account, 'type', 'unknown')
        account_name = getattr(account, 'name', 'Unknown')
        
        if available > 0:
            print(f"  • {currency:6s} ${available:>10.2f}  [{account_type}] {account_name}")
            if currency in ['USD', 'USDC']:
                advanced_total += available
                
except Exception as e:
    print(f"  ❌ Error: {e}")

print(f"\n  ✅ Advanced Trade Total (USD + USDC): ${advanced_total:.2f}")
if advanced_total >= 10:
    print(f"  ✅ Sufficient for bot trading!")
elif advanced_total >= 5:
    print(f"  ⚠️  Low balance - may have issues with fees")
else:
    print(f"  ❌ Insufficient for bot trading (need at least $10)")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n\n" + "="*80)
print("📊 SUMMARY")
print("="*80)
print(f"Consumer Wallet:       ${consumer_total:>10.2f}  ❌ Not tradable")
print(f"Advanced Trade:        ${advanced_total:>10.2f}  {'✅ Tradable' if advanced_total >= 10 else '⚠️  Too low'}")
print(f"{'─' * 80}")
print(f"Total:                 ${consumer_total + advanced_total:>10.2f}")

if consumer_total > 0 and advanced_total < 10:
    print(f"\n{'!' * 80}")
    print(f"🚨 ACTION REQUIRED:")
    print(f"   You have ${consumer_total:.2f} in Consumer wallet but only ${advanced_total:.2f} tradable")
    print(f"\n   TO FIX:")
    print(f"   1. Go to: https://www.coinbase.com/advanced-portfolio")
    print(f"   2. Click 'Deposit' → 'From Coinbase'")
    print(f"   3. Transfer ${consumer_total:.2f} to Advanced Trade")
    print(f"   4. Bot will automatically detect and use it!")
    print(f"{'!' * 80}")
elif advanced_total >= 10:
    print(f"\n✅ You're all set for bot trading!")
else:
    print(f"\n⚠️  Need to deposit more funds to reach $10 minimum")

print("="*80 + "\n")
