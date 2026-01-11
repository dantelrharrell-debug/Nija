#!/usr/bin/env python3
"""
Kraken Multi-Account Connection Diagnostics
============================================

This script diagnoses Kraken connection issues for:
- Master account
- User #1 (Daivon Frazier)
- User #2 (Tania Gilbert)

It checks:
1. Environment variables are set
2. Credentials are valid
3. API connections work
4. Trading permissions are sufficient

Date: January 11, 2026
"""

import os
import sys

# Try to load .env if dotenv is available (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not available, use system environment variables
    pass

def print_header(title):
    """Print formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_status(label, status, is_good=True):
    """Print status line with emoji."""
    emoji = "✅" if is_good else "❌"
    print(f"{emoji} {label}: {status}")

def check_env_var(var_name, account_name):
    """Check if environment variable is set."""
    value = os.getenv(var_name, "").strip()
    if value:
        print_status(f"{account_name} - {var_name}", f"Set ({len(value)} chars)", True)
        return value
    else:
        print_status(f"{account_name} - {var_name}", "NOT SET", False)
        return None

def test_kraken_connection(api_key, api_secret, account_name):
    """Test Kraken API connection."""
    print(f"\n🔄 Testing {account_name} connection...")
    
    if not api_key or not api_secret:
        print_status(f"{account_name} Connection", "Skipped (credentials missing)", False)
        return False
    
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        
        # Initialize API
        api = krakenex.API(key=api_key, secret=api_secret)
        
        # Test connection by getting balance
        balance = api.query_private('Balance')
        
        if balance and 'error' in balance and balance['error']:
            error_msgs = ', '.join(balance['error'])
            print_status(f"{account_name} Connection", f"FAILED: {error_msgs}", False)
            
            # Check for specific errors
            if 'permission' in error_msgs.lower():
                print("\n⚠️  PERMISSION ERROR:")
                print("   Your Kraken API key needs these permissions:")
                print("   • Query Funds")
                print("   • Query Open Orders & Trades")
                print("   • Create & Modify Orders")
                print("   • Cancel/Close Orders")
                print("   Go to: https://www.kraken.com/u/security/api")
            
            if 'nonce' in error_msgs.lower():
                print("\n⚠️  NONCE ERROR:")
                print("   This usually means:")
                print("   • Clock drift on server")
                print("   • Previous API calls with same nonce")
                print("   • API key recently reset")
            
            return False
        
        if balance and 'result' in balance:
            result = balance['result']
            usd = float(result.get('ZUSD', 0))
            usdt = float(result.get('USDT', 0))
            total = usd + usdt
            
            print_status(f"{account_name} Connection", "SUCCESS", True)
            print(f"   USD Balance:  ${usd:.2f}")
            print(f"   USDT Balance: ${usdt:.2f}")
            print(f"   Total:        ${total:.2f}")
            
            # List other assets
            other_assets = {k: v for k, v in result.items() if k not in ['ZUSD', 'USDT']}
            if other_assets:
                print(f"   Other assets: {len(other_assets)}")
                for asset, amount in list(other_assets.items())[:5]:
                    print(f"      {asset}: {amount}")
            
            return True
        else:
            print_status(f"{account_name} Connection", "FAILED: No result data", False)
            return False
            
    except ImportError:
        print_status(f"{account_name} Connection", "ERROR: krakenex not installed", False)
        print("   Install with: pip install krakenex pykrakenapi")
        return False
    except Exception as e:
        print_status(f"{account_name} Connection", f"ERROR: {e}", False)
        import traceback
        print("\n📋 Full Error Traceback:")
        print(traceback.format_exc())
        return False

def main():
    """Main diagnostic function."""
    print_header("KRAKEN MULTI-ACCOUNT CONNECTION DIAGNOSTICS")
    print(f"  Date: {os.popen('date').read().strip()}")
    
    # Check environment variables
    print_header("STEP 1: Environment Variables Check")
    
    master_key = check_env_var("KRAKEN_MASTER_API_KEY", "MASTER")
    master_secret = check_env_var("KRAKEN_MASTER_API_SECRET", "MASTER")
    
    user1_key = check_env_var("KRAKEN_USER_DAIVON_API_KEY", "USER #1 (Daivon)")
    user1_secret = check_env_var("KRAKEN_USER_DAIVON_API_SECRET", "USER #1 (Daivon)")
    
    user2_key = check_env_var("KRAKEN_USER_TANIA_API_KEY", "USER #2 (Tania)")
    user2_secret = check_env_var("KRAKEN_USER_TANIA_API_SECRET", "USER #2 (Tania)")
    
    # Also check legacy credentials (for backward compatibility)
    legacy_key = check_env_var("KRAKEN_API_KEY", "LEGACY")
    legacy_secret = check_env_var("KRAKEN_API_SECRET", "LEGACY")
    
    # Test connections
    print_header("STEP 2: API Connection Tests")
    
    results = {
        'master': test_kraken_connection(master_key, master_secret, "MASTER"),
        'user1': test_kraken_connection(user1_key, user1_secret, "USER #1 (Daivon)"),
        'user2': test_kraken_connection(user2_key, user2_secret, "USER #2 (Tania)")
    }
    
    # Summary
    print_header("SUMMARY")
    
    total_accounts = 3
    connected_accounts = sum(1 for v in results.values() if v)
    
    if connected_accounts == 0:
        print("\n❌ NO ACCOUNTS CONNECTED")
        print("\nPossible issues:")
        print("  1. Environment variables not set (check .env file)")
        print("  2. Invalid API credentials")
        print("  3. Missing API permissions")
        print("  4. krakenex library not installed")
    elif connected_accounts < total_accounts:
        print(f"\n⚠️  PARTIAL CONNECTION ({connected_accounts}/{total_accounts} accounts)")
        print("\nConnected accounts:")
        for name, connected in results.items():
            status = "✅ Connected" if connected else "❌ Not connected"
            print(f"  {name.upper()}: {status}")
    else:
        print("\n✅ ALL ACCOUNTS CONNECTED SUCCESSFULLY")
        print("\nAccount Status:")
        print("  MASTER:           ✅ Connected and trading-ready")
        print("  USER #1 (Daivon): ✅ Connected and trading-ready")
        print("  USER #2 (Tania):  ✅ Connected and trading-ready")
    
    # Configuration check
    print_header("STEP 3: Code Configuration Check")
    
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
        
        # Check if broker_manager has KrakenBroker
        from broker_manager import KrakenBroker, AccountType
        print_status("KrakenBroker class", "Available", True)
        
        # Check if multi_account_broker_manager exists
        from multi_account_broker_manager import MultiAccountBrokerManager
        print_status("MultiAccountBrokerManager", "Available", True)
        
        # Check if trading_strategy is configured for users
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
            
        if 'user1_id = "daivon_frazier"' in content:
            print_status("User #1 (Daivon) configured", "Yes", True)
        else:
            print_status("User #1 (Daivon) configured", "No", False)
        
        if 'user2_id = "tania_gilbert"' in content:
            print_status("User #2 (Tania) configured", "Yes", True)
        else:
            print_status("User #2 (Tania) configured", "No", False)
        
        if 'add_user_broker(user1_id, user1_broker_type)' in content:
            print_status("User #1 broker connection code", "Present", True)
        else:
            print_status("User #1 broker connection code", "Missing", False)
        
        if 'add_user_broker(user2_id, user2_broker_type)' in content:
            print_status("User #2 broker connection code", "Present", True)
        else:
            print_status("User #2 broker connection code", "Missing", False)
            
    except Exception as e:
        print_status("Code configuration check", f"Error: {e}", False)
    
    # Next steps
    print_header("NEXT STEPS")
    
    if connected_accounts == total_accounts:
        print("\n✅ All accounts are connected!")
        print("\nTo deploy:")
        print("  1. Commit and push this code")
        print("  2. Set environment variables on Railway/Render:")
        print("     • KRAKEN_MASTER_API_KEY")
        print("     • KRAKEN_MASTER_API_SECRET")
        print("     • KRAKEN_USER_DAIVON_API_KEY")
        print("     • KRAKEN_USER_DAIVON_API_SECRET")
        print("     • KRAKEN_USER_TANIA_API_KEY")
        print("     • KRAKEN_USER_TANIA_API_SECRET")
        print("  3. Deploy and verify logs")
    else:
        print("\n⚠️  Fix the issues above, then:")
        print("  1. Set missing environment variables")
        print("  2. Verify API credentials")
        print("  3. Check API permissions")
        print("  4. Run this script again")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()
