#!/usr/bin/env python3
"""
Diagnose Coinbase account types and balances
Shows why funds might not be available for trading
"""

import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

def main():
    """Check all Coinbase accounts and their types"""
    
    print("=" * 80)
    print("COINBASE ACCOUNT DIAGNOSTICS")
    print("=" * 80)
    
    # Import broker
    from bot.broker_manager import CoinbaseBroker
    
    # Connect
    broker = CoinbaseBroker()
    print("\n🔌 Connecting to Coinbase...")
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return 1
    
    print("✅ Connected successfully\n")
    
    # Check v2 API accounts
    print("=" * 80)
    print("V2 API ACCOUNTS (Consumer/Retail)")
    print("=" * 80)
    
    try:
        import requests
        import time
        import jwt
        from cryptography.hazmat.primitives import serialization
        
        api_key = os.getenv("COINBASE_API_KEY")
        api_secret = os.getenv("COINBASE_API_SECRET")
        
        # Normalize PEM
        if '\\n' in api_secret:
            api_secret = api_secret.replace('\\n', '\n')
        
        private_key = serialization.load_pem_private_key(api_secret.encode('utf-8'), password=None)
        
        # Make v2 API call
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
            print(f"\nFound {len(v2_accounts)} v2 accounts:\n")
            
            for i, acc in enumerate(v2_accounts, 1):
                currency = acc.get('currency', {}).get('code', 'N/A')
                balance = float(acc.get('balance', {}).get('amount', 0))
                name = acc.get('name', 'Unknown')
                account_type = acc.get('type', 'unknown')
                
                if currency in ['USD', 'USDC'] or balance > 0:
                    tradable = "❌ NOT TRADABLE (Consumer wallet)" if account_type == 'wallet' else "✅ Tradable"
                    print(f"{i}. {currency:>5} | Balance: ${balance:>10.2f} | Name: {name:30} | Type: {account_type:15} | {tradable}")
        else:
            print(f"❌ v2 API returned status {response.status_code}")
            
    except Exception as e:
        print(f"❌ v2 API check failed: {e}")
    
    # Check v3 API accounts
    print("\n" + "=" * 80)
    print("V3 API ACCOUNTS (Advanced Trade)")
    print("=" * 80)
    
    try:
        accounts_resp = broker.client.get_accounts()
        accounts = getattr(accounts_resp, 'accounts', [])
        print(f"\nFound {len(accounts)} v3 accounts:\n")
        
        for i, account in enumerate(accounts, 1):
            currency = getattr(account, 'currency', 'N/A')
            available_obj = getattr(account, 'available_balance', None)
            available = float(getattr(available_obj, 'value', 0) or 0)
            account_type = getattr(account, 'type', 'unknown')
            name = getattr(account, 'name', 'Unknown')
            
            if currency in ['USD', 'USDC'] or available > 0:
                # Check if tradable
                is_consumer = 'CONSUMER' in str(account_type)
                tradable = "❌ NOT TRADABLE (Consumer)" if is_consumer else "✅ Tradable"
                print(f"{i}. {currency:>5} | Available: ${available:>10.2f} | Type: {account_type:40} | {tradable}")
                
    except Exception as e:
        print(f"❌ v3 API check failed: {e}")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    balance_data = broker.get_account_balance()
    print(f"\nTrading Balance: ${balance_data.get('trading_balance', 0):.2f}")
    print(f"USD:             ${balance_data.get('usd', 0):.2f}")
    print(f"USDC:            ${balance_data.get('usdc', 0):.2f}")
    
    if balance_data.get('trading_balance', 0) < 5.0:
        print("\n⚠️  INSUFFICIENT FUNDS FOR TRADING")
        print("   Minimum: $5.00")
        print("\n💡 HOW TO FIX:")
        print("   1. Go to: https://www.coinbase.com/advanced-portfolio")
        print("   2. Click 'Deposit' or 'Transfer'")
        print("   3. Move funds from your Consumer wallet to Advanced Trade portfolio")
    else:
        print("\n✅ Sufficient funds for trading")
    
    print("\n" + "=" * 80)
    return 0

if __name__ == "__main__":
    sys.exit(main())
