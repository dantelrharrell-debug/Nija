#!/usr/bin/env python3
"""
Verify Kraken Master Account Connection
========================================

This script tests the connection to the master's Kraken account
and confirms that the credentials are properly configured.
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

print("=" * 70)
print("🔍 VERIFYING MASTER'S KRAKEN ACCOUNT CONNECTION")
print("=" * 70)
print()

# Step 1: Check if credentials are present
print("Step 1: Checking for Kraken Master credentials...")
api_key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
api_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()

if not api_key:
    print("❌ KRAKEN_MASTER_API_KEY is not set or empty")
    print()
    print("Please set the following in your .env file:")
    print("   KRAKEN_MASTER_API_KEY=<your-master-api-key>")
    print("   KRAKEN_MASTER_API_SECRET=<your-master-api-secret>")
    sys.exit(1)

if not api_secret:
    print("❌ KRAKEN_MASTER_API_SECRET is not set or empty")
    print()
    print("Please set the following in your .env file:")
    print("   KRAKEN_MASTER_API_KEY=<your-master-api-key>")
    print("   KRAKEN_MASTER_API_SECRET=<your-master-api-secret>")
    sys.exit(1)

print(f"✅ KRAKEN_MASTER_API_KEY found ({len(api_key)} characters)")
print(f"✅ KRAKEN_MASTER_API_SECRET found ({len(api_secret)} characters)")
print()

# Step 2: Test Kraken API connection
print("Step 2: Testing connection to Kraken API...")
try:
    import krakenex
    from pykrakenapi import KrakenAPI
    import time
    
    # Initialize Kraken API with master credentials
    api = krakenex.API(key=api_key, secret=api_secret)
    kraken_api = KrakenAPI(api)
    
    print("✅ Kraken SDK initialized successfully")
    print()
    
    # Step 3: Test connection by fetching account balance
    print("Step 3: Fetching account balance...")
    max_attempts = 3
    base_delay = 5.0
    
    balance = None
    for attempt in range(1, max_attempts + 1):
        try:
            if attempt > 1:
                delay = base_delay * (2 ** (attempt - 2))
                print(f"🔄 Retrying in {delay}s (attempt {attempt}/{max_attempts})...")
                time.sleep(delay)
            
            balance = api.query_private('Balance')
            
            if balance and 'error' in balance:
                if balance['error']:
                    error_msgs = ', '.join(balance['error'])
                    
                    # Check if it's a permission error
                    is_permission_error = any(keyword in error_msgs.lower() for keyword in [
                        'permission denied', 'permission', 'egeneral:permission', 
                        'eapi:invalid permission', 'insufficient permission'
                    ])
                    
                    if is_permission_error:
                        print(f"❌ Kraken API permission error: {error_msgs}")
                        print()
                        print("⚠️  API KEY PERMISSION ERROR")
                        print("Your Kraken API key does not have the required permissions.")
                        print()
                        print("To fix this issue:")
                        print("1. Go to https://www.kraken.com/u/security/api")
                        print("2. Find your API key and edit its permissions")
                        print("3. Enable these permissions:")
                        print("   - Query Funds")
                        print("   - Query Open Orders & Trades")
                        print("   - Query Closed Orders & Trades")
                        print("   - Create & Modify Orders")
                        print("   - Cancel/Close Orders")
                        print("4. Save the changes and try again")
                        sys.exit(1)
                    else:
                        print(f"⚠️  Kraken API error: {error_msgs}")
                        if attempt == max_attempts:
                            print(f"❌ Failed after {max_attempts} attempts")
                            sys.exit(1)
                        continue
                else:
                    # Success - no errors
                    break
            else:
                # Success - balance retrieved
                break
                
        except Exception as e:
            print(f"⚠️  Connection error: {e}")
            if attempt == max_attempts:
                print(f"❌ Failed after {max_attempts} attempts")
                import traceback
                print()
                print("Error details:")
                print(traceback.format_exc())
                sys.exit(1)
    
    # Step 4: Display account balance
    print("✅ Successfully connected to Kraken Master account!")
    print()
    
    if balance and 'result' in balance:
        balances = balance['result']
        if balances:
            print("📊 Account Balances:")
            total_usd = 0.0
            
            for currency, amount in balances.items():
                amount_float = float(amount)
                if amount_float > 0.0001:  # Show non-dust balances
                    print(f"   {currency}: {amount_float:.4f}")
                    
                    # Estimate USD value for common currencies
                    if currency in ['ZUSD', 'USD']:
                        total_usd += amount_float
                    elif currency in ['USDT', 'USDC']:
                        total_usd += amount_float
            
            print()
            if total_usd > 0:
                print(f"💰 Estimated USD value: ${total_usd:,.2f}")
        else:
            print("📊 Account has no balances (empty account)")
    
    print()
    print("=" * 70)
    print("✅ MASTER'S KRAKEN ACCOUNT IS CONNECTED AND WORKING!")
    print("=" * 70)
    print()
    print("The master's Kraken account credentials are properly configured")
    print("and the connection to Kraken Pro API is successful.")
    print()
    print("Next steps:")
    print("1. The trading bot will automatically use this connection")
    print("2. Master account will trade on Kraken Pro exchange")
    print("3. Monitor logs to see Kraken trading activity")
    
except ImportError as e:
    print(f"❌ Failed to import required modules: {e}")
    print()
    print("Please install required dependencies:")
    print("   pip install krakenex pykrakenapi")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    import traceback
    print()
    print("Error details:")
    print(traceback.format_exc())
    sys.exit(1)
