#!/usr/bin/env python3
"""
Find USD Portfolio - Locate which Coinbase portfolio contains USD/USDC funds
"""

import os
from dotenv import load_dotenv
from coinbase.rest import RESTClient

# Load credentials
load_dotenv()

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

if not api_key or not api_secret:
    print("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET")
    exit(1)

try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    print("\n" + "="*80)
    print("PORTFOLIO SCANNER - Finding USD/USDC Wallets")
    print("="*80 + "\n")
    
    # Step 1: List all portfolios
    print("📁 Fetching all portfolios...")
    portfolios_response = client.get_portfolios()
    
    if hasattr(portfolios_response, 'portfolios') and portfolios_response.portfolios:
        print(f"✅ Found {len(portfolios_response.portfolios)} portfolio(s)\n")
        
        for portfolio in portfolios_response.portfolios:
            portfolio_uuid = getattr(portfolio, 'uuid', 'N/A')
            portfolio_name = getattr(portfolio, 'name', 'N/A')
            portfolio_type = getattr(portfolio, 'type', 'N/A')
            
            print(f"\n{'='*80}")
            print(f"Portfolio: {portfolio_name}")
            print(f"UUID: {portfolio_uuid}")
            print(f"Type: {portfolio_type}")
            print(f"{'='*80}")
            
            # Step 2: Get accounts for this portfolio
            try:
                accounts_response = client.get_accounts(retail_portfolio_id=portfolio_uuid)
                
                if hasattr(accounts_response, 'accounts') and accounts_response.accounts:
                    print(f"\n📊 Accounts in '{portfolio_name}':")
                    
                    usd_found = False
                    usdc_found = False
                    total_usd = 0.0
                    total_usdc = 0.0
                    
                    for account in accounts_response.accounts:
                        currency = getattr(account, 'currency', 'UNKNOWN')
                        
                        # Extract balance
                        available_balance = getattr(account, 'available_balance', None)
                        if available_balance:
                            if hasattr(available_balance, 'value'):
                                balance_value = float(available_balance.value)
                            elif isinstance(available_balance, dict):
                                balance_value = float(available_balance.get('value', 0))
                            else:
                                balance_value = 0.0
                        else:
                            balance_value = 0.0
                        
                        # Track USD and USDC
                        if currency == "USD":
                            usd_found = True
                            total_usd += balance_value
                            print(f"  💵 USD: ${balance_value:.2f}")
                        elif currency == "USDC":
                            usdc_found = True
                            total_usdc += balance_value
                            print(f"  💵 USDC: ${balance_value:.2f}")
                        elif balance_value > 0:
                            print(f"  🪙 {currency}: {balance_value:.8f}")
                    
                    # Summary
                    if usd_found or usdc_found:
                        print(f"\n  🎯 TOTAL IN THIS PORTFOLIO:")
                        if usd_found:
                            print(f"     USD: ${total_usd:.2f}")
                        if usdc_found:
                            print(f"     USDC: ${total_usdc:.2f}")
                else:
                    print(f"  ⚠️ No accounts found in this portfolio")
                    
            except Exception as e:
                print(f"  ❌ Error fetching accounts for portfolio '{portfolio_name}': {e}")
    
    else:
        print("⚠️ No portfolios found")
    
    # Step 3: Also check accounts WITHOUT portfolio filter (default behavior)
    print(f"\n\n{'='*80}")
    print("📊 DEFAULT ACCOUNTS (no portfolio filter)")
    print(f"{'='*80}\n")
    
    default_accounts = client.get_accounts()
    
    if hasattr(default_accounts, 'accounts') and default_accounts.accounts:
        print(f"Found {len(default_accounts.accounts)} account(s) in default view:\n")
        
        for account in default_accounts.accounts:
            currency = getattr(account, 'currency', 'UNKNOWN')
            platform = getattr(account, 'platform', 'UNKNOWN')
            
            available_balance = getattr(account, 'available_balance', None)
            if available_balance:
                if hasattr(available_balance, 'value'):
                    balance_value = float(available_balance.value)
                elif isinstance(available_balance, dict):
                    balance_value = float(available_balance.get('value', 0))
                else:
                    balance_value = 0.0
            else:
                balance_value = 0.0
            
            if currency in ["USD", "USDC"] or balance_value > 0:
                print(f"  {currency}: {balance_value:.8f} (platform: {platform})")
    else:
        print("⚠️ No accounts in default view")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80 + "\n")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
