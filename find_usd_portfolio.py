#!/usr/bin/env python3
"""
Portfolio Scanner - Find and display Coinbase portfolios with USD/USDC funds

This tool helps you:
1. List all your Coinbase portfolios with their UUIDs and types
2. Show USD/USDC balances in each portfolio
3. Identify which portfolio UUID to set in COINBASE_RETAIL_PORTFOLIO_ID

Usage:
    python find_usd_portfolio.py

Environment variables required:
    COINBASE_API_KEY     - Your Coinbase API key
    COINBASE_API_SECRET  - Your Coinbase API secret (or use PEM options)
    COINBASE_PEM_CONTENT - Alternative: PEM key content
    COINBASE_PEM_PATH    - Alternative: Path to PEM key file

Optional:
    COINBASE_RETAIL_PORTFOLIO_ID - If set, highlights this portfolio
    ALLOW_CONSUMER_USD          - If set to true/1, shows consumer USD in totals
"""

import os
import sys
import tempfile
from coinbase.rest import RESTClient

def main():
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
    
    # Check configuration flags
    portfolio_override = os.environ.get("COINBASE_RETAIL_PORTFOLIO_ID")
    allow_consumer_usd = str(os.environ.get("ALLOW_CONSUMER_USD", "")).lower() in ("1", "true", "yes")
    
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
        print("\n" + "="*80)
        print("🔍 COINBASE PORTFOLIO SCANNER")
        print("="*80)
        
        if portfolio_override:
            print(f"\n🔧 Portfolio Override: {portfolio_override} (set via COINBASE_RETAIL_PORTFOLIO_ID)")
        if allow_consumer_usd:
            print("⚙️  Consumer USD Inclusion: ENABLED (ALLOW_CONSUMER_USD=true)")
        else:
            print("⚙️  Consumer USD Inclusion: DISABLED (set ALLOW_CONSUMER_USD=true to enable)")
        
        # Step 1: List all portfolios
        print("\n📁 Fetching all portfolios...")
        portfolios_response = client.get_portfolios()
        
        if hasattr(portfolios_response, 'portfolios') and portfolios_response.portfolios:
            print(f"✅ Found {len(portfolios_response.portfolios)} portfolio(s)\n")
            
            all_portfolio_data = []
            
            for portfolio in portfolios_response.portfolios:
                portfolio_uuid = getattr(portfolio, 'uuid', 'N/A')
                portfolio_name = getattr(portfolio, 'name', 'N/A')
                portfolio_type = getattr(portfolio, 'type', 'N/A')
                
                is_override = (portfolio_override == portfolio_uuid)
                
                print(f"\n{'='*80}")
                if is_override:
                    print(f"📌 Portfolio: {portfolio_name} ⭐ CURRENTLY SELECTED ⭐")
                else:
                    print(f"📁 Portfolio: {portfolio_name}")
                print(f"   UUID: {portfolio_uuid}")
                print(f"   Type: {portfolio_type}")
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
                        consumer_usd = 0.0
                        
                        for account in accounts_response.accounts:
                            currency = getattr(account, 'currency', 'UNKNOWN')
                            platform = getattr(account, 'platform', None)
                            
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
                                is_consumer = (platform == "ACCOUNT_PLATFORM_CONSUMER")
                                if is_consumer:
                                    consumer_usd += balance_value
                                    if allow_consumer_usd:
                                        total_usd += balance_value
                                        print(f"  💵 USD: ${balance_value:.2f} (Consumer - INCLUDED via ALLOW_CONSUMER_USD)")
                                    else:
                                        print(f"  ⚠️  USD: ${balance_value:.2f} (Consumer - EXCLUDED, set ALLOW_CONSUMER_USD=true to include)")
                                else:
                                    total_usd += balance_value
                                    print(f"  💵 USD: ${balance_value:.2f} (Platform: {platform})")
                            elif currency == "USDC":
                                usdc_found = True
                                total_usdc += balance_value
                                print(f"  💵 USDC: ${balance_value:.2f}")
                            elif balance_value > 0:
                                print(f"  🪙 {currency}: {balance_value:.8f}")
                        
                        # Summary
                        print(f"\n  {'─'*76}")
                        print(f"  📊 TOTALS FOR THIS PORTFOLIO:")
                        if usdc_found:
                            print(f"     USDC: ${total_usdc:.2f}")
                        if usd_found:
                            print(f"     USD:  ${total_usd:.2f}")
                        trading_balance = total_usdc if total_usdc > 0 else total_usd
                        print(f"     TRADING BALANCE: ${trading_balance:.2f}")
                        
                        if consumer_usd > 0 and not allow_consumer_usd:
                            print(f"\n     ℹ️  Note: ${consumer_usd:.2f} consumer USD excluded")
                            print(f"        Set ALLOW_CONSUMER_USD=true to include it")
                        
                        all_portfolio_data.append({
                            'uuid': portfolio_uuid,
                            'name': portfolio_name,
                            'type': portfolio_type,
                            'usdc': total_usdc,
                            'usd': total_usd,
                            'trading_balance': trading_balance,
                            'is_override': is_override
                        })
                    else:
                        print(f"  ⚠️ No accounts found in this portfolio")
                        all_portfolio_data.append({
                            'uuid': portfolio_uuid,
                            'name': portfolio_name,
                            'type': portfolio_type,
                            'usdc': 0.0,
                            'usd': 0.0,
                            'trading_balance': 0.0,
                            'is_override': is_override
                        })
                        
                except Exception as e:
                    print(f"  ❌ Error fetching accounts for portfolio '{portfolio_name}': {e}")
                    all_portfolio_data.append({
                        'uuid': portfolio_uuid,
                        'name': portfolio_name,
                        'type': portfolio_type,
                        'usdc': 0.0,
                        'usd': 0.0,
                        'trading_balance': 0.0,
                        'is_override': is_override,
                        'error': str(e)
                    })
            
            # Summary table
            print(f"\n\n{'='*80}")
            print("📊 PORTFOLIO SUMMARY")
            print(f"{'='*80}")
            print(f"{'Portfolio Name':<25} {'UUID':<38} {'Balance':<10}")
            print(f"{'-'*80}")
            
            for pf in all_portfolio_data:
                marker = "⭐" if pf['is_override'] else "  "
                print(f"{marker} {pf['name']:<23} {pf['uuid']:<38} ${pf['trading_balance']:.2f}")
            
            print(f"{'='*80}")
            
            # Recommendations
            print(f"\n💡 RECOMMENDATIONS:\n")
            
            funded_portfolios = [pf for pf in all_portfolio_data if pf['trading_balance'] > 0]
            if not funded_portfolios:
                print("   ⚠️  No portfolios with USD/USDC balance found!")
                print("   Please deposit funds to your Coinbase account.")
            elif len(funded_portfolios) == 1:
                pf = funded_portfolios[0]
                print(f"   ✅ Found 1 funded portfolio: {pf['name']}")
                print(f"      Trading Balance: ${pf['trading_balance']:.2f}")
                if not pf['is_override']:
                    print(f"\n   To use this portfolio, set:")
                    print(f"      COINBASE_RETAIL_PORTFOLIO_ID={pf['uuid']}")
            else:
                print(f"   ✅ Found {len(funded_portfolios)} funded portfolios:")
                for pf in funded_portfolios:
                    marker = "⭐ SELECTED" if pf['is_override'] else ""
                    print(f"      • {pf['name']}: ${pf['trading_balance']:.2f} {marker}")
                
                if not portfolio_override:
                    print(f"\n   To select a specific portfolio, set:")
                    print(f"      COINBASE_RETAIL_PORTFOLIO_ID=<uuid>")
                    
        else:
            print("⚠️ No portfolios found")
        
        # Step 3: Also check accounts WITHOUT portfolio filter (default behavior)
        print(f"\n\n{'='*80}")
        print("📊 DEFAULT ACCOUNT VIEW (no portfolio filter)")
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
        print("✅ SCAN COMPLETE")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
    finally:
        # Clean up temp PEM file
        if temp_pem_file:
            try:
                os.unlink(temp_pem_file.name)
            except:
                pass

if __name__ == "__main__":
    main()
