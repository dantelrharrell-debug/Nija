#!/usr/bin/env python3
"""
Coinbase Portfolio Discovery Tool

Lists all available Coinbase portfolios and their USD/USDC balances.
Helps identify which portfolio to fund or set as COINBASE_RETAIL_PORTFOLIO_ID.

Usage:
    python3 find_funded_portfolio.py
"""

import os
import sys
from pathlib import Path

from coinbase.rest import RESTClient


def load_env_from_dotenv():
    """Load environment variables from .env if not already set."""
    dotenv_path = Path('.env')
    if not dotenv_path.exists():
        return
    try:
        with dotenv_path.open('r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and (os.getenv(key) is None):
                    os.environ[key] = val
    except Exception as e:
        print(f"⚠️ Failed to parse .env: {e}")


def safe_preview(value: str, max_prefix: int = 8) -> str:
    """Safe preview of a credential value."""
    if not value:
        return "<empty>"
    return f"{value[:max_prefix]}… (len={len(value)})"


def main():
    """Main entry point."""
    print("\n" + "=" * 80)
    print("💼 COINBASE PORTFOLIO DISCOVERY TOOL")
    print("=" * 80)

    # Load .env if not set
    if not os.getenv('COINBASE_API_KEY') or not os.getenv('COINBASE_API_SECRET'):
        load_env_from_dotenv()

    # Validate credentials
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    pem_content = os.getenv('COINBASE_PEM_CONTENT')

    if not api_key:
        print("❌ Missing COINBASE_API_KEY. Set in env or .env")
        sys.exit(1)

    if not api_secret and not pem_content:
        print("❌ Missing secret. Provide COINBASE_API_SECRET (JWT) or COINBASE_PEM_CONTENT (PEM)")
        sys.exit(1)

    auth_method = 'pem' if pem_content and not api_secret else 'jwt'
    print(f"\n🔐 Auth: {auth_method} | key={safe_preview(api_key)} | secret={safe_preview(api_secret or pem_content)}")

    # Initialize client
    client_kwargs = {'api_key': api_key}
    if auth_method == 'jwt':
        client_kwargs['api_secret'] = api_secret
    else:
        client_kwargs['api_secret'] = pem_content

    try:
        client = RESTClient(**client_kwargs)
    except Exception as e:
        print(f"❌ Failed to initialize Coinbase client: {e}")
        sys.exit(1)

    # Fetch portfolios
    try:
        print("\n📡 Fetching portfolios...")
        portfolios_response = client.get_portfolios()
        
        # Handle both list and dict responses
        if isinstance(portfolios_response, dict):
            if 'portfolios' in portfolios_response:
                portfolios = portfolios_response['portfolios']
            else:
                portfolios = [portfolios_response]
        else:
            portfolios = portfolios_response if isinstance(portfolios_response, list) else []
        
        if not portfolios:
            print("❌ No portfolios found")
            sys.exit(1)

        print(f"\n✅ Found {len(portfolios)} portfolio(s):\n")
        print("-" * 80)

        funded_portfolios = []

        for idx, portfolio in enumerate(portfolios, 1):
            portfolio_id = portfolio.get('id')
            portfolio_name = portfolio.get('name', 'N/A')
            portfolio_type = portfolio.get('type', 'N/A')

            print(f"\n{idx}. {portfolio_name}")
            print(f"   Type: {portfolio_type}")
            print(f"   UUID: {portfolio_id}")

            # Fetch breakdown (assets in this portfolio)
            try:
                breakdown = client.get_portfolio_breakdown(portfolio_id)
                
                if breakdown:
                    # Handle both dict and potential list responses
                    if isinstance(breakdown, dict):
                        breakdown_data = breakdown
                    elif isinstance(breakdown, list) and len(breakdown) > 0:
                        breakdown_data = breakdown[0]
                    else:
                        breakdown_data = {}

                    assets = breakdown_data.get('breakdown', [])
                    
                    usd_balance = 0.0
                    usdc_balance = 0.0
                    total_value = 0.0
                    
                    if assets:
                        print(f"   Assets ({len(assets)}):")
                        for asset in assets:
                            if isinstance(asset, dict):
                                currency = asset.get('asset', {}).get('symbol', 'UNKNOWN')
                                amount = float(asset.get('amount', 0.0))
                                
                                if amount > 0:
                                    percentage = asset.get('percentage', '0%')
                                    
                                    if currency == 'USD':
                                        usd_balance = amount
                                    elif currency == 'USDC':
                                        usdc_balance = amount
                                    
                                    print(f"     - {currency}: {amount:.2f} ({percentage})")
                    
                    trading_balance = usd_balance + usdc_balance
                    
                    print(f"\n   💵 USD/USDC Balance: ${trading_balance:.2f}")
                    
                    if trading_balance > 0:
                        funded_portfolios.append({
                            'name': portfolio_name,
                            'id': portfolio_id,
                            'type': portfolio_type,
                            'usd': usd_balance,
                            'usdc': usdc_balance,
                            'total': trading_balance
                        })
                        print(f"   ✅ FUNDED")
                    else:
                        print(f"   ⚠️ No USD/USDC")

            except Exception as e:
                print(f"   ⚠️ Error fetching breakdown: {e}")

        print("\n" + "-" * 80)

        # Summary
        if funded_portfolios:
            print(f"\n🎯 FUNDED PORTFOLIOS ({len(funded_portfolios)}):")
            for portfolio in funded_portfolios:
                print(f"\n   • {portfolio['name']} (Type: {portfolio['type']})")
                print(f"     UUID: {portfolio['id']}")
                print(f"     Balance: ${portfolio['total']:.2f}")
                print(f"     └─ USD: ${portfolio['usd']:.2f}, USDC: ${portfolio['usdc']:.2f}")

            print(f"\n📋 TO USE A FUNDED PORTFOLIO FOR TRADING:")
            print(f"\n   Set the portfolio UUID as an environment variable:")
            print(f"\n   export COINBASE_RETAIL_PORTFOLIO_ID=\"<portfolio-uuid>\"")
            print(f"\n   Example:")
            print(f"   export COINBASE_RETAIL_PORTFOLIO_ID=\"{funded_portfolios[0]['id']}\"")
            print(f"\n   Then restart the NIJA bot container.")
        else:
            print("\n⚠️ NO FUNDED PORTFOLIOS FOUND")
            print("\n   To enable trading, choose one of:")
            print("   1. Fund the Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio")
            print("   2. Move USD/USDC to a non-Advanced-Trade portfolio and set its UUID above")

        print("\n" + "=" * 80 + "\n")

    except Exception as e:
        print(f"❌ Error fetching portfolios: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
