#!/usr/bin/env python3
"""
Find USD Portfolio - Locate which Coinbase portfolio contains USD/USDC funds
Self-contained: reads environment directly (no .env required).
"""

import os
import tempfile
from coinbase.rest import RESTClient

api_key = os.environ.get("COINBASE_API_KEY")
api_secret = os.environ.get("COINBASE_API_SECRET")
pem_content = os.environ.get("COINBASE_PEM_CONTENT")
pem_path = os.environ.get("COINBASE_PEM_PATH")

if not api_key or not (api_secret or pem_content or pem_path):
    print("❌ Missing credentials for Coinbase Advanced Trade API")
    print("   Expected env vars:")
    print("   - COINBASE_API_KEY")
    print("   - COINBASE_API_SECRET  (PEM private key content) OR COINBASE_PEM_CONTENT OR COINBASE_PEM_PATH")
    # Show which relevant envs are currently set to help debugging
    present = {k: ("<set>" if os.environ.get(k) else "<missing>") for k in ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_PEM_CONTENT", "COINBASE_PEM_PATH", "COINBASE_RETAIL_PORTFOLIO_ID"]}
    print(f"   Current env status: {present}")
    raise SystemExit(1)

# If PEM content is provided as a single-line env, write it to a temp file for the SDK
temp_pem_file = None
try:
    key_file_arg = None
    if pem_path:
        key_file_arg = pem_path
    elif pem_content:
        # Normalize \n escapes into real newlines
        normalized = pem_content.replace("\\n", "\n")
        temp_pem_file = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".pem")
        temp_pem_file.write(normalized)
        temp_pem_file.flush()
        key_file_arg = temp_pem_file.name

    client = RESTClient(api_key=api_key, api_secret=api_secret if not key_file_arg else None, key_file=key_file_arg)
except Exception as e:
    print(f"❌ Failed to initialize RESTClient: {e}")
    raise SystemExit(1)

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
    
    # If an override is set, show that portfolio first
    override = os.environ.get("COINBASE_RETAIL_PORTFOLIO_ID")
    if override:
        print(f"\nUsing override portfolio: {override}")
        try:
            ov_accounts = client.get_accounts(retail_portfolio_id=override)
            if hasattr(ov_accounts, 'accounts') and ov_accounts.accounts:
                print(f"Found {len(ov_accounts.accounts)} account(s) in override view:\n")
                for account in ov_accounts.accounts:
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
                    print(f"  {currency}: {balance_value:.8f} (platform: {platform})")
            else:
                print("⚠️ No accounts in override view")
        except Exception as e:
            print(f"❌ Error fetching override portfolio accounts: {e}")

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
