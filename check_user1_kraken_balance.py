#!/usr/bin/env python3
"""
Check User #1 Kraken Account Balance

This script connects to User #1 (Daivon Frazier)'s Kraken account
and displays the available trading balance.

Usage:
    python check_user1_kraken_balance.py
"""

import os
import sys

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, use system environment variables

def print_header(title):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_section(title):
    """Print formatted section"""
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80)

def get_user1_kraken_credentials():
    """Get User #1 (Daivon Frazier) Kraken credentials"""
    # These are the credentials from setup_user_daivon.py
    # In production, these would be stored encrypted in the user database
    kraken_api_key = "8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7"
    kraken_api_secret = "e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA=="
    
    return kraken_api_key, kraken_api_secret

def check_kraken_balance():
    """Check User #1's Kraken account balance"""
    print_header("USER #1 KRAKEN ACCOUNT BALANCE CHECK")
    
    # User Info
    print_section("User Information")
    print("  User ID: daivon_frazier")
    print("  Name: Daivon Frazier")
    print("  Email: Frazierdaivon@gmail.com")
    print("  Broker: Kraken Pro")
    
    # Get credentials
    print_section("Retrieving Kraken Credentials")
    api_key, api_secret = get_user1_kraken_credentials()
    print(f"  ✅ API Key: {api_key[:20]}...{api_key[-10:]}")
    print(f"  ✅ API Secret: {api_secret[:20]}...{api_secret[-10:]}")
    
    # Test connection and get balance
    print_section("Connecting to Kraken Pro")
    
    try:
        import krakenex
        
        print("  🔄 Initializing Kraken API client...")
        api = krakenex.API(key=api_key, secret=api_secret)
        
        print("  🔄 Querying account balance...")
        balance = api.query_private('Balance')
        
        if balance and 'error' in balance:
            if balance['error']:
                error_msgs = ', '.join(balance['error'])
                print(f"  ❌ Connection failed: {error_msgs}")
                print_section("Possible Issues")
                print("  1. API credentials may be invalid or expired")
                print("  2. API key permissions may be insufficient")
                print("  3. Network connectivity issue")
                print("  4. Kraken API may be temporarily unavailable")
                return False
        
        if balance and 'result' in balance:
            print("  ✅ Successfully connected to Kraken Pro!")
            
            # Parse balance
            result = balance.get('result', {})
            
            print_section("Account Balance")
            
            # USD Balance
            usd_balance = float(result.get('ZUSD', 0))
            print(f"  USD Balance:  ${usd_balance:,.2f}")
            
            # USDT Balance (Tether)
            usdt_balance = float(result.get('USDT', 0))
            print(f"  USDT Balance: ${usdt_balance:,.2f}")
            
            # Total USD equivalent
            total_usd = usd_balance + usdt_balance
            print(f"\n  💰 TOTAL AVAILABLE FOR TRADING: ${total_usd:,.2f} USD")
            
            # Crypto Holdings
            print_section("Crypto Holdings")
            crypto_assets = {k: v for k, v in result.items() if k not in ['ZUSD', 'USDT'] and float(v) > 0}
            
            if crypto_assets:
                print("  The following crypto assets are also in the account:")
                for asset, amount in crypto_assets.items():
                    amount_float = float(amount)
                    # Clean up asset names (Kraken uses X prefix for many assets)
                    clean_asset = asset.replace('X', '').replace('Z', '')
                    print(f"    {clean_asset}: {amount_float:.8f}")
                print("\n  ⚠️  Note: Crypto holdings are listed but USD/USDT is used for trading")
            else:
                print("  No crypto holdings found (account has only USD/USDT)")
            
            # Trading Readiness
            print_section("Trading Readiness Assessment")
            
            if total_usd >= 100:
                print(f"  ✅ EXCELLENT - ${total_usd:,.2f} available")
                print("     Sufficient for multiple positions")
                print("     Bot can trade effectively with current balance")
            elif total_usd >= 50:
                print(f"  ✅ GOOD - ${total_usd:,.2f} available")
                print("     Sufficient for several small positions")
                print("     Consider adding more for better diversification")
            elif total_usd >= 25:
                print(f"  ⚠️  LIMITED - ${total_usd:,.2f} available")
                print("     Meets minimum requirement")
                print("     Will limit position sizes")
                print("     Recommended: Add at least $50 more")
            elif total_usd >= 2:
                print(f"  ⚠️  VERY LIMITED - ${total_usd:,.2f} available")
                print("     Below recommended minimum")
                print("     Bot may struggle to find valid trades")
                print("     Recommended: Add at least $100")
            else:
                print(f"  ❌ INSUFFICIENT - ${total_usd:,.2f} available")
                print("     Below minimum requirement ($2.00)")
                print("     Bot cannot trade with this balance")
                print("     Action required: Deposit funds to Kraken")
            
            # User #1 Limits
            print_section("User #1 Trading Limits (When Activated)")
            print("  Max Position Size: $300.00 USD")
            print("  Max Daily Loss: $150.00 USD")
            print("  Max Concurrent Positions: 7")
            print("  Allowed Trading Pairs: 8")
            print("    • BTC-USD (Bitcoin)")
            print("    • ETH-USD (Ethereum)")
            print("    • SOL-USD (Solana)")
            print("    • AVAX-USD (Avalanche)")
            print("    • MATIC-USD (Polygon)")
            print("    • DOT-USD (Polkadot)")
            print("    • LINK-USD (Chainlink)")
            print("    • ADA-USD (Cardano)")
            
            # Summary
            print_header("SUMMARY")
            print(f"\n  User #1: Daivon Frazier")
            print(f"  Broker: Kraken Pro")
            print(f"  Balance: ${total_usd:,.2f} USD available for trading")
            
            if total_usd >= 25:
                print(f"  Status: ✅ READY TO TRADE")
            elif total_usd >= 2:
                print(f"  Status: ⚠️  CAN TRADE (limited)")
            else:
                print(f"  Status: ❌ INSUFFICIENT FUNDS")
            
            print(f"\n  Next Steps:")
            if total_usd < 100:
                print(f"    1. Consider depositing more funds (recommend $100-200)")
                print(f"    2. Activate user system: python init_user_system.py")
                print(f"    3. Setup user: python setup_user_daivon.py")
                print(f"    4. Enable trading: python manage_user_daivon.py enable")
            else:
                print(f"    1. Activate user system: python init_user_system.py")
                print(f"    2. Setup user: python setup_user_daivon.py")
                print(f"    3. Enable trading: python manage_user_daivon.py enable")
                print(f"    4. Bot will start trading with Kraken account")
            
            print("\n" + "=" * 80 + "\n")
            return True
        else:
            print("  ❌ Connection failed: No balance data returned")
            return False
            
    except ImportError:
        print("  ❌ Kraken SDK not installed")
        print("\n  To install:")
        print("    pip install krakenex pykrakenapi")
        print("  Or:")
        print("    pip install -r requirements.txt")
        return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    try:
        check_kraken_balance()
    except KeyboardInterrupt:
        print("\n\n❌ Check interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
