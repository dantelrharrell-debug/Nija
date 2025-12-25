#!/usr/bin/env python3
"""
Test raw Coinbase API call with proper JWT authentication
Shows exactly what the /v3/brokerage/accounts endpoint returns
"""

import os
import sys
import json
import time
import jwt
import requests
from cryptography.hazmat.primitives import serialization

# Load .env file manually
if os.path.isfile(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value

# Load credentials
api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

if not api_key or not api_secret:
    print("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET")
    sys.exit(1)

# Normalize PEM newlines
if '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

print("=" * 80)
print("🔍 RAW COINBASE API TEST")
print("=" * 80)
print(f"API Key: {api_key[:30]}...")
print(f"API Secret length: {len(api_secret)} chars")
print()

try:
    # 1. Load the private key
    print("🔐 Loading EC private key from PEM...")
    private_key = serialization.load_pem_private_key(
        api_secret.encode('utf-8'),
        password=None
    )
    print("✅ Private key loaded successfully\n")
    
    # 2. Generate JWT token (valid for 2 minutes)
    print("🎫 Generating JWT token...")
    uri = "GET api.coinbase.com/api/v3/brokerage/accounts"
    
    payload = {
        'sub': api_key,
        'iss': 'coinbase-cloud',
        'nbf': int(time.time()),
        'exp': int(time.time()) + 120,  # 2 minutes
        'aud': ['coinbase-apis'],
        'uri': uri
    }
    
    token = jwt.encode(
        payload,
        private_key,
        algorithm='ES256',
        headers={'kid': api_key, 'nonce': str(int(time.time()))}
    )
    
    print(f"✅ JWT generated (length: {len(token)} chars)")
    print(f"   Preview: {token[:50]}...\n")
    
    # 3. Make the API call
    print("📡 Making API request to /v3/brokerage/accounts...")
    url = "https://api.coinbase.com/api/v3/brokerage/accounts"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    response = requests.get(url, headers=headers)
    
    print(f"   Status Code: {response.status_code}")
    print()
    
    # 4. Parse and display response
    if response.status_code == 200:
        print("✅ SUCCESS! Response:")
        print("=" * 80)
        data = response.json()
        
        # Pretty print the JSON
        print(json.dumps(data, indent=2))
        print("=" * 80)
        
        # Analyze accounts
        accounts = data.get('accounts', [])
        print(f"\n📊 ANALYSIS:")
        print(f"   Total accounts: {len(accounts)}")
        
        if len(accounts) == 0:
            print("\n⚠️ WARNING: API returned 0 accounts!")
            print("   Your API key has permissions, but no accounts are visible.")
            print("   This usually means:")
            print("   1. Funds are in Coinbase.com (not Advanced Trade)")
            print("   2. Need to transfer to Advanced Trade portfolio")
            print("   3. Account is completely empty")
        else:
            print("\nAccounts found:")
            usd_found = False
            usdc_found = False
            for acc in accounts:
                currency = acc.get('currency', 'UNKNOWN')
                name = acc.get('name', 'UNKNOWN')
                available = float(acc.get('available_balance', {}).get('value', 0))
                
                if currency == 'USD':
                    usd_found = True
                if currency == 'USDC':
                    usdc_found = True
                
                if currency in ['USD', 'USDC'] or available > 0:
                    print(f"   • {currency}: ${available:.2f} ({name})")
            
            print()
            if not usd_found and not usdc_found:
                print("⚠️ No USD or USDC accounts found!")
                print("   You need to have USD or USDC in Advanced Trade to execute trades.")
            elif available == 0:
                print("⚠️ USD/USDC accounts exist but balance is $0.00")
                print("   Transfer funds to Advanced Trade to enable trading.")
    
    elif response.status_code == 401:
        print("❌ AUTHENTICATION FAILED (401)")
        print("   Your API credentials are invalid or expired.")
        print("\nResponse:")
        print(response.text)
        
    elif response.status_code == 403:
        print("❌ PERMISSION DENIED (403)")
        print("   Your API key doesn't have permission to view accounts.")
        print("   Go to: https://portal.cloud.coinbase.com/access/api")
        print("   Ensure 'View' permission is enabled for your API key.")
        print("\nResponse:")
        print(response.text)
        
    else:
        print(f"❌ API ERROR ({response.status_code})")
        print("\nResponse:")
        print(response.text)
    
    print("\n" + "=" * 80)
    print("💡 NEXT STEPS:")
    print("=" * 80)
    print("If you see 0 accounts or $0 balance:")
    print("1. Go to: https://www.coinbase.com/settings/advanced-trade")
    print("2. Check if you have USD/USDC in the Advanced Trade section")
    print("3. If funds are in 'Coinbase.com', click 'Deposit' to move them")
    print("4. Verify: https://www.coinbase.com/advanced-portfolio")
    print("=" * 80)

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
