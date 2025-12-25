#!/usr/bin/env python3
"""
Detect all Coinbase portfolios and their UUIDs
Run this to find your 'nija' portfolio UUID
"""

import sys
import os
sys.path.insert(0, '/workspaces/Nija/bot')

from broker_manager import CoinbaseBroker
import json

print("=" * 80)
print("COINBASE PORTFOLIO DETECTOR")
print("=" * 80)

try:
    # Initialize broker
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        sys.exit(1)
    
    print("✅ Connected to Coinbase\n")
    
    # Try to get portfolios via the REST client
    if hasattr(broker.client, 'get_portfolios'):
        try:
            portfolios_resp = broker.client.get_portfolios()
            
            # Handle response
            if hasattr(portfolios_resp, 'portfolios'):
                portfolios = portfolios_resp.portfolios
            elif isinstance(portfolios_resp, dict):
                portfolios = portfolios_resp.get('portfolios', [])
            else:
                portfolios = []
            
            print(f"📊 Found {len(portfolios)} portfolio(s):\n")
            
            for portfolio in portfolios:
                # Extract portfolio info
                pid = None
                pname = None
                
                if hasattr(portfolio, 'uuid'):
                    pid = portfolio.uuid
                elif isinstance(portfolio, dict):
                    pid = portfolio.get('uuid') or portfolio.get('id')
                
                if hasattr(portfolio, 'name'):
                    pname = portfolio.name
                elif isinstance(portfolio, dict):
                    pname = portfolio.get('name')
                
                if pid and pname:
                    print(f"Portfolio: {pname}")
                    print(f"UUID: {pid}")
                    print()
                    
                    # Check if this is the 'nija' portfolio
                    if 'nija' in pname.lower():
                        print("🎯 THIS IS YOUR NIJA PORTFOLIO!")
                        print(f"\n✅ Set this env var in Railway:")
                        print(f"   COINBASE_RETAIL_PORTFOLIO_ID={pid}")
                        print()
        
        except Exception as e:
            print(f"⚠️  Error fetching portfolios: {e}")
            print("\nTrying alternative method...")
            
            # Try accounts which might show portfolio info
            try:
                accounts = broker.client.get_accounts()
                if hasattr(accounts, 'accounts'):
                    accts = accounts.accounts
                elif isinstance(accounts, dict):
                    accts = accounts.get('accounts', [])
                else:
                    accts = []
                
                print(f"\nFound {len(accts)} account(s):")
                for acct in accts:
                    acct_dict = acct.__dict__ if hasattr(acct, '__dict__') else acct
                    print(json.dumps(acct_dict, indent=2, default=str))
                    
            except Exception as e2:
                print(f"Alternative method failed: {e2}")
    
    else:
        print("❌ get_portfolios not available on client")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
