#!/usr/bin/env python3
"""
Live Kraken Connection Test
============================

This script attempts to connect to Kraken with the current environment variables
and provides detailed diagnostics about what's working and what's not.

Run this on Railway/Render to diagnose Kraken connection issues.

Usage:
    python3 test_kraken_connection_live.py
"""

import os
import sys
from datetime import datetime

def print_header(title, char="="):
    """Print formatted header"""
    width = 80
    print()
    print(char * width)
    print(title.center(width))
    print(char * width)
    print()


def print_section(title):
    """Print formatted section"""
    print()
    print(f"{'─' * 80}")
    print(f"  {title}")
    print(f"{'─' * 80}")


def mask_credential(value):
    """Mask credential for safe logging"""
    if not value:
        return None
    if len(value) > 12:
        return f"{value[:4]}...{value[-4:]}"
    return "***"


def test_kraken_master():
    """Test Kraken master account connection"""
    print_section("🔍 TESTING KRAKEN MASTER ACCOUNT")
    
    # Check environment variables
    master_key_raw = os.getenv("KRAKEN_MASTER_API_KEY", "")
    master_secret_raw = os.getenv("KRAKEN_MASTER_API_SECRET", "")
    legacy_key_raw = os.getenv("KRAKEN_API_KEY", "")
    legacy_secret_raw = os.getenv("KRAKEN_API_SECRET", "")
    
    # Strip whitespace
    master_key = master_key_raw.strip()
    master_secret = master_secret_raw.strip()
    legacy_key = legacy_key_raw.strip()
    legacy_secret = legacy_secret_raw.strip()
    
    # Determine which credentials to use
    if master_key and master_secret:
        api_key = master_key
        api_secret = master_secret
        cred_source = "KRAKEN_MASTER_*"
        print(f"  ✅ Using KRAKEN_MASTER_* credentials")
    elif legacy_key and legacy_secret:
        api_key = legacy_key
        api_secret = legacy_secret
        cred_source = "KRAKEN_* (legacy)"
        print(f"  ✅ Using legacy KRAKEN_* credentials")
    else:
        print(f"  ❌ No Kraken master credentials found")
        print()
        print("  Checked for:")
        print(f"    KRAKEN_MASTER_API_KEY: {'SET (but empty after strip)' if master_key_raw else 'NOT SET'}")
        print(f"    KRAKEN_MASTER_API_SECRET: {'SET (but empty after strip)' if master_secret_raw else 'NOT SET'}")
        print(f"    KRAKEN_API_KEY (legacy): {'SET (but empty after strip)' if legacy_key_raw else 'NOT SET'}")
        print(f"    KRAKEN_API_SECRET (legacy): {'SET (but empty after strip)' if legacy_secret_raw else 'NOT SET'}")
        return False
    
    # Show what we have
    print(f"  Source: {cred_source}")
    print(f"  API Key: {mask_credential(api_key)}")
    print(f"  API Secret: {mask_credential(api_secret)}")
    
    # Try to import Kraken SDK
    print()
    print("  📦 Checking Kraken SDK...")
    try:
        import krakenex
        print("  ✅ krakenex imported successfully")
    except ImportError as e:
        print(f"  ❌ Failed to import Kraken SDK: {e}")
        print("  💡 Install with: pip install krakenex pykrakenapi")
        return False
    
    # Try to connect
    print()
    print("  🔌 Attempting connection...")
    try:
        # Initialize API
        api = krakenex.API(key=api_key, secret=api_secret)
        
        # Test with a simple balance query
        print("  ⏳ Querying account balance...")
        balance = api.query_private('Balance')
        
        # Check for errors
        if balance and 'error' in balance:
            if balance['error']:
                error_msgs = ', '.join(balance['error'])
                print(f"  ❌ Kraken API error: {error_msgs}")
                
                # Provide specific guidance
                if 'permission' in error_msgs.lower():
                    print()
                    print("  ⚠️  PERMISSION ERROR")
                    print("  Your API key exists but lacks required permissions.")
                    print()
                    print("  Fix:")
                    print("    1. Go to https://www.kraken.com/u/security/api")
                    print("    2. Edit your API key permissions")
                    print("    3. Enable these permissions:")
                    print("       ✅ Query Funds")
                    print("       ✅ Query Open Orders & Trades")
                    print("       ✅ Query Closed Orders & Trades")
                    print("       ✅ Create & Modify Orders")
                    print("       ✅ Cancel/Close Orders")
                    print("    4. Save and restart the bot")
                elif 'invalid key' in error_msgs.lower() or 'authentication' in error_msgs.lower():
                    print()
                    print("  ⚠️  AUTHENTICATION ERROR")
                    print("  Your API key or secret is invalid.")
                    print()
                    print("  Fix:")
                    print("    1. Verify credentials at https://www.kraken.com/u/security/api")
                    print("    2. Create a new API key if needed")
                    print("    3. Update environment variables in Railway/Render")
                    print("    4. Restart the deployment")
                elif 'nonce' in error_msgs.lower():
                    print()
                    print("  ⚠️  NONCE ERROR")
                    print("  This can happen if:")
                    print("    - Multiple bots are using the same API key")
                    print("    - System clock is out of sync")
                    print()
                    print("  Try again in a few seconds - nonce errors are often transient.")
                
                return False
        
        # Check for result
        if balance and 'result' in balance:
            print("  ✅ Successfully connected to Kraken!")
            print()
            print("  📊 Account Balance:")
            
            result = balance.get('result', {})
            usd_balance = float(result.get('ZUSD', 0))
            usdt_balance = float(result.get('USDT', 0))
            total = usd_balance + usdt_balance
            
            print(f"    USD (ZUSD): ${usd_balance:.2f}")
            print(f"    USDT: ${usdt_balance:.2f}")
            print(f"    Total: ${total:.2f}")
            
            if total < 1.0:
                print()
                print("  ⚠️  Account balance is very low (< $1)")
                print("  The bot needs at least $1-2 to trade effectively.")
            
            return True
        else:
            print("  ❌ Unexpected response format (no result)")
            print(f"  Response: {balance}")
            return False
            
    except Exception as e:
        print(f"  ❌ Exception during connection: {type(e).__name__}: {e}")
        import traceback
        print()
        print("  Stack trace:")
        traceback.print_exc()
        return False


def test_kraken_user(user_name, user_id):
    """Test Kraken user account connection"""
    print_section(f"👤 TESTING USER: {user_name} ({user_id})")
    
    # Extract first name for env var
    user_env_name = user_id.split('_')[0].upper() if '_' in user_id else user_id.upper()
    
    # Check environment variables
    key_name = f"KRAKEN_USER_{user_env_name}_API_KEY"
    secret_name = f"KRAKEN_USER_{user_env_name}_API_SECRET"
    
    api_key_raw = os.getenv(key_name, "")
    api_secret_raw = os.getenv(secret_name, "")
    
    # Strip whitespace
    api_key = api_key_raw.strip()
    api_secret = api_secret_raw.strip()
    
    if not api_key or not api_secret:
        print(f"  ❌ No credentials found for {user_name}")
        print()
        print("  Checked for:")
        print(f"    {key_name}: {'SET (but empty after strip)' if api_key_raw else 'NOT SET'}")
        print(f"    {secret_name}: {'SET (but empty after strip)' if api_secret_raw else 'NOT SET'}")
        return False
    
    # Show what we have
    print(f"  ✅ Credentials found")
    print(f"  API Key: {mask_credential(api_key)}")
    print(f"  API Secret: {mask_credential(api_secret)}")
    
    # Try to import Kraken SDK
    print()
    print("  📦 Checking Kraken SDK...")
    try:
        import krakenex
        print("  ✅ krakenex imported successfully")
    except ImportError as e:
        print(f"  ❌ Failed to import Kraken SDK: {e}")
        return False
    
    # Try to connect
    print()
    print("  🔌 Attempting connection...")
    try:
        # Initialize API
        api = krakenex.API(key=api_key, secret=api_secret)
        
        # Test with a simple balance query
        print("  ⏳ Querying account balance...")
        balance = api.query_private('Balance')
        
        # Check for errors
        if balance and 'error' in balance:
            if balance['error']:
                error_msgs = ', '.join(balance['error'])
                print(f"  ❌ Kraken API error: {error_msgs}")
                
                if 'permission' in error_msgs.lower():
                    print("  ⚠️  PERMISSION ERROR - API key lacks required permissions")
                elif 'invalid key' in error_msgs.lower():
                    print("  ⚠️  AUTHENTICATION ERROR - Invalid API key or secret")
                
                return False
        
        # Check for result
        if balance and 'result' in balance:
            print(f"  ✅ Successfully connected to Kraken for {user_name}!")
            print()
            print("  📊 Account Balance:")
            
            result = balance.get('result', {})
            usd_balance = float(result.get('ZUSD', 0))
            usdt_balance = float(result.get('USDT', 0))
            total = usd_balance + usdt_balance
            
            print(f"    USD (ZUSD): ${usd_balance:.2f}")
            print(f"    USDT: ${usdt_balance:.2f}")
            print(f"    Total: ${total:.2f}")
            
            return True
        else:
            print("  ❌ Unexpected response format")
            return False
            
    except Exception as e:
        print(f"  ❌ Exception: {type(e).__name__}: {e}")
        return False


def main():
    """Main test function"""
    print_header("🔬 KRAKEN CONNECTION LIVE TEST")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Environment: {os.getenv('RAILWAY_ENVIRONMENT', os.getenv('RENDER', 'LOCAL'))}")
    
    results = {}
    
    # Test master account
    results['master'] = test_kraken_master()
    
    # Test user accounts
    results['daivon'] = test_kraken_user("Daivon Frazier", "daivon_frazier")
    results['tania'] = test_kraken_user("Tania Gilbert", "tania_gilbert")
    
    # Summary
    print_header("📊 TEST SUMMARY")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed
    
    print(f"  Total Tests: {total}")
    print(f"  Passed: {passed} ✅")
    print(f"  Failed: {failed} ❌")
    print()
    
    for account, status in results.items():
        icon = "✅" if status else "❌"
        status_text = "CONNECTED" if status else "FAILED"
        print(f"  {icon} {account.title()}: {status_text}")
    
    print()
    print("=" * 80)
    
    # Exit code
    if passed == total:
        print()
        print("🎉 ALL TESTS PASSED!")
        print("Kraken is ready to trade for all configured accounts.")
        print()
        return 0
    elif passed > 0:
        print()
        print("⚠️  PARTIAL SUCCESS")
        print(f"{passed}/{total} accounts connected successfully.")
        print("Fix the failed accounts and re-run this test.")
        print()
        return 1
    else:
        print()
        print("❌ ALL TESTS FAILED")
        print("Kraken is NOT connected for any account.")
        print()
        print("Next steps:")
        print("  1. Verify credentials are set in Railway/Render environment variables")
        print("  2. Check that credentials have required permissions")
        print("  3. Restart the deployment after fixing credentials")
        print()
        return 2


if __name__ == "__main__":
    sys.exit(main())
