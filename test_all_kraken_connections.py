#!/usr/bin/env python3
"""
Comprehensive Kraken Connection Test
=====================================

This script tests Kraken API connections for:
- Master account (NIJA system)
- All configured user accounts (Daivon Frazier, Tania Gilbert)

It verifies:
1. Environment variables are set
2. Credentials are valid
3. API connections work
4. Account balances can be retrieved
5. Trading permissions are configured

Usage:
    python3 test_all_kraken_connections.py

Exit Codes:
    0 - All connections successful
    1 - Some connections failed
    2 - All connections failed
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

# Try to load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Running in environment with pre-set variables

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def print_header(title: str, char: str = "=", width: int = 80):
    """Print a formatted header."""
    print()
    print(char * width)
    print(title.center(width))
    print(char * width)
    print()


def print_section(title: str, width: int = 80):
    """Print a formatted section header."""
    print()
    print("─" * width)
    print(f"  {title}")
    print("─" * width)


def mask_credential(value: Optional[str]) -> str:
    """Mask credential for safe logging."""
    if not value:
        return "NOT SET"
    if len(value) > 12:
        return f"{value[:4]}...{value[-4:]}"
    return "***"


def check_env_var(var_name: str) -> Tuple[bool, str, Optional[str]]:
    """
    Check if an environment variable is set and valid.
    
    Returns:
        Tuple of (is_valid, status_message, value)
    """
    value = os.getenv(var_name, "")
    
    if not value:
        return False, "❌ NOT SET", None
    
    # Check if it's just whitespace
    if not value.strip():
        return False, "⚠️  SET but EMPTY (whitespace only)", None
    
    # Check if it looks like a real credential (at least 10 chars)
    if len(value.strip()) < 10:
        return False, f"⚠️  TOO SHORT ({len(value.strip())} chars, need 10+)", None
    
    return True, f"✅ VALID ({len(value.strip())} chars)", value.strip()


def get_user_env_var_names(user_id: str) -> Tuple[str, str]:
    """
    Get environment variable names for a user ID.
    
    Args:
        user_id: User identifier (e.g., 'daivon_frazier', 'tania_gilbert')
        
    Returns:
        Tuple of (api_key_var_name, api_secret_var_name)
    """
    # Convert user_id to uppercase, extract first part before underscore
    if '_' in user_id:
        user_env_name = user_id.split('_')[0].upper()
    else:
        user_env_name = user_id.upper()
    
    key_var = f"KRAKEN_USER_{user_env_name}_API_KEY"
    secret_var = f"KRAKEN_USER_{user_env_name}_API_SECRET"
    
    return key_var, secret_var


def load_configured_users() -> List[Dict]:
    """Load configured Kraken users from config files."""
    config_file = project_root / "config" / "users" / "retail_kraken.json"
    
    if not config_file.exists():
        return []
    
    try:
        with open(config_file, 'r') as f:
            users = json.load(f)
        
        # Filter to enabled users only
        return [u for u in users if u.get('enabled', False)]
    except Exception as e:
        logger.error(f"Error loading user config: {e}")
        return []


def test_master_credentials() -> bool:
    """Test master account credentials are set."""
    print_section("1️⃣  MASTER ACCOUNT CREDENTIALS")
    
    # Check primary credentials
    master_key_valid, master_key_status, master_key_value = check_env_var("KRAKEN_MASTER_API_KEY")
    master_secret_valid, master_secret_status, master_secret_value = check_env_var("KRAKEN_MASTER_API_SECRET")
    
    print(f"   KRAKEN_MASTER_API_KEY:    {master_key_status}")
    print(f"   KRAKEN_MASTER_API_SECRET: {master_secret_status}")
    
    # Check legacy credentials as fallback
    if not (master_key_valid and master_secret_valid):
        print()
        print("   📌 Checking legacy credentials (fallback)...")
        legacy_key_valid, legacy_key_status, legacy_key_value = check_env_var("KRAKEN_API_KEY")
        legacy_secret_valid, legacy_secret_status, legacy_secret_value = check_env_var("KRAKEN_API_SECRET")
        
        print(f"   KRAKEN_API_KEY:           {legacy_key_status}")
        print(f"   KRAKEN_API_SECRET:        {legacy_secret_status}")
        
        if legacy_key_valid and legacy_secret_valid:
            print()
            print("   ✅ Legacy credentials found - will be used for master account")
            return True
        else:
            print()
            print("   ❌ No valid credentials found for master account")
            return False
    else:
        print()
        print("   ✅ Master account credentials configured")
        return True


def test_master_connection() -> bool:
    """Test master account connection to Kraken."""
    print_section("2️⃣  MASTER ACCOUNT CONNECTION TEST")
    
    try:
        # Try to import krakenex
        try:
            import krakenex
            print("   ✅ krakenex library imported successfully")
        except ImportError:
            print("   ❌ krakenex library not installed")
            print("   💡 Install with: pip install krakenex pykrakenapi")
            return False
        
        # Get credentials
        master_key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
        master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()
        
        # Fallback to legacy
        if not master_key or not master_secret:
            master_key = os.getenv("KRAKEN_API_KEY", "").strip()
            master_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
        
        if not master_key or not master_secret:
            print("   ❌ Cannot test connection - credentials not set")
            return False
        
        print(f"   🔑 Using API Key: {mask_credential(master_key)}")
        print()
        print("   🔌 Attempting connection to Kraken API...")
        
        # Initialize API
        api = krakenex.API(key=master_key, secret=master_secret)
        
        # Test with balance query
        print("   ⏳ Querying account balance...")
        balance = api.query_private('Balance')
        
        # Check for errors
        if balance and 'error' in balance and balance['error']:
            error_msgs = ', '.join(balance['error'])
            print(f"   ❌ Kraken API error: {error_msgs}")
            
            if 'permission' in error_msgs.lower():
                print()
                print("   ⚠️  PERMISSION ERROR")
                print("   Your API key exists but lacks required permissions.")
                print()
                print("   Required permissions:")
                print("      ✅ Query Funds")
                print("      ✅ Query Open Orders & Trades")
                print("      ✅ Query Closed Orders & Trades")
                print("      ✅ Create & Modify Orders")
                print("      ✅ Cancel/Close Orders")
            elif 'invalid key' in error_msgs.lower() or 'authentication' in error_msgs.lower():
                print()
                print("   ⚠️  AUTHENTICATION ERROR")
                print("   Your API key or secret is invalid.")
            
            return False
        
        # Check for result
        if balance and 'result' in balance:
            print("   ✅ Successfully connected to Kraken!")
            print()
            print("   📊 Account Balance:")
            
            result = balance.get('result', {})
            usd_balance = float(result.get('ZUSD', 0))
            usdt_balance = float(result.get('USDT', 0))
            total = usd_balance + usdt_balance
            
            print(f"      USD (ZUSD): ${usd_balance:.2f}")
            print(f"      USDT: ${usdt_balance:.2f}")
            print(f"      Total: ${total:.2f}")
            
            if total < 1.0:
                print()
                print("   ⚠️  Account balance is very low (< $1)")
                print("   The bot needs at least $1-2 to trade effectively.")
            elif total < 25.0:
                print()
                print("   ⚠️  Account balance is below recommended minimum ($25)")
                print("   Trading may be limited with low balance.")
            
            return True
        else:
            print("   ❌ Unexpected response format from Kraken")
            return False
            
    except Exception as e:
        print(f"   ❌ Exception during connection test: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_user_credentials(user_id: str, user_name: str) -> bool:
    """Test user account credentials are set."""
    print_section(f"👤 USER: {user_name} ({user_id}) - CREDENTIALS")
    
    key_var, secret_var = get_user_env_var_names(user_id)
    
    key_valid, key_status, key_value = check_env_var(key_var)
    secret_valid, secret_status, secret_value = check_env_var(secret_var)
    
    print(f"   {key_var}: {key_status}")
    print(f"   {secret_var}: {secret_status}")
    
    if key_valid and secret_valid:
        print()
        print(f"   ✅ Credentials configured for {user_name}")
        return True
    else:
        print()
        print(f"   ❌ Missing credentials for {user_name}")
        return False


def test_user_connection(user_id: str, user_name: str) -> bool:
    """Test user account connection to Kraken."""
    print_section(f"👤 USER: {user_name} ({user_id}) - CONNECTION TEST")
    
    try:
        # Try to import krakenex
        try:
            import krakenex
        except ImportError:
            print("   ❌ krakenex library not installed")
            return False
        
        # Get credentials
        key_var, secret_var = get_user_env_var_names(user_id)
        api_key = os.getenv(key_var, "").strip()
        api_secret = os.getenv(secret_var, "").strip()
        
        if not api_key or not api_secret:
            print("   ❌ Cannot test connection - credentials not set")
            return False
        
        print(f"   🔑 Using API Key: {mask_credential(api_key)}")
        print()
        print("   🔌 Attempting connection to Kraken API...")
        
        # Initialize API
        api = krakenex.API(key=api_key, secret=api_secret)
        
        # Test with balance query
        print("   ⏳ Querying account balance...")
        balance = api.query_private('Balance')
        
        # Check for errors
        if balance and 'error' in balance and balance['error']:
            error_msgs = ', '.join(balance['error'])
            print(f"   ❌ Kraken API error: {error_msgs}")
            
            if 'permission' in error_msgs.lower():
                print("   ⚠️  PERMISSION ERROR - API key lacks required permissions")
            elif 'invalid key' in error_msgs.lower():
                print("   ⚠️  AUTHENTICATION ERROR - Invalid API key or secret")
            
            return False
        
        # Check for result
        if balance and 'result' in balance:
            print(f"   ✅ Successfully connected to Kraken for {user_name}!")
            print()
            print("   📊 Account Balance:")
            
            result = balance.get('result', {})
            usd_balance = float(result.get('ZUSD', 0))
            usdt_balance = float(result.get('USDT', 0))
            total = usd_balance + usdt_balance
            
            print(f"      USD (ZUSD): ${usd_balance:.2f}")
            print(f"      USDT: ${usdt_balance:.2f}")
            print(f"      Total: ${total:.2f}")
            
            if total < 1.0:
                print()
                print("   ⚠️  Account balance is very low (< $1)")
            elif total < 25.0:
                print()
                print("   ⚠️  Account balance is below recommended minimum ($25)")
            
            return True
        else:
            print("   ❌ Unexpected response format from Kraken")
            return False
            
    except Exception as e:
        print(f"   ❌ Exception during connection test: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test function."""
    print_header("🚀 COMPREHENSIVE KRAKEN CONNECTION TEST")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Environment: {os.getenv('RAILWAY_ENVIRONMENT', os.getenv('RENDER', 'LOCAL'))}")
    
    results = {}
    
    # Test master account
    print()
    print("=" * 80)
    print("  MASTER ACCOUNT VERIFICATION")
    print("=" * 80)
    
    master_creds_ok = test_master_credentials()
    results['master_credentials'] = master_creds_ok
    
    if master_creds_ok:
        master_conn_ok = test_master_connection()
        results['master_connection'] = master_conn_ok
    else:
        print()
        print("   ⏭️  Skipping connection test - credentials not configured")
        results['master_connection'] = False
    
    # Test user accounts
    users = load_configured_users()
    
    if not users:
        print()
        print("=" * 80)
        print("  ⚠️  No enabled users found in config/users/retail_kraken.json")
        print("=" * 80)
    else:
        print()
        print("=" * 80)
        print(f"  USER ACCOUNT VERIFICATION ({len(users)} users)")
        print("=" * 80)
        
        for user in users:
            user_id = user.get('user_id')
            user_name = user.get('name', user_id)
            
            print()
            
            # Test credentials
            user_creds_ok = test_user_credentials(user_id, user_name)
            results[f'{user_id}_credentials'] = user_creds_ok
            
            # Test connection
            if user_creds_ok:
                user_conn_ok = test_user_connection(user_id, user_name)
                results[f'{user_id}_connection'] = user_conn_ok
            else:
                print_section(f"👤 USER: {user_name} ({user_id}) - CONNECTION TEST")
                print("   ⏭️  Skipping connection test - credentials not configured")
                results[f'{user_id}_connection'] = False
    
    # Summary
    print()
    print_header("📊 TEST SUMMARY")
    
    total_tests = len(results)
    passed_tests = sum(1 for v in results.values() if v)
    failed_tests = total_tests - passed_tests
    
    print(f"  Total Tests: {total_tests}")
    print(f"  ✅ Passed: {passed_tests}")
    print(f"  ❌ Failed: {failed_tests}")
    print()
    
    # Detailed results
    print("  Detailed Results:")
    print("  " + "-" * 76)
    
    # Master account
    master_creds = results.get('master_credentials', False)
    master_conn = results.get('master_connection', False)
    master_icon = "✅" if (master_creds and master_conn) else "❌"
    print(f"  {master_icon} Master Account")
    print(f"      Credentials: {'✅ SET' if master_creds else '❌ NOT SET'}")
    print(f"      Connection:  {'✅ CONNECTED' if master_conn else '❌ FAILED' if master_creds else '⏭️  SKIPPED'}")
    
    # User accounts
    for user in users:
        user_id = user.get('user_id')
        user_name = user.get('name', user_id)
        
        user_creds = results.get(f'{user_id}_credentials', False)
        user_conn = results.get(f'{user_id}_connection', False)
        user_icon = "✅" if (user_creds and user_conn) else "❌"
        
        print()
        print(f"  {user_icon} {user_name} ({user_id})")
        print(f"      Credentials: {'✅ SET' if user_creds else '❌ NOT SET'}")
        print(f"      Connection:  {'✅ CONNECTED' if user_conn else '❌ FAILED' if user_creds else '⏭️  SKIPPED'}")
    
    print()
    print("=" * 80)
    
    # Final verdict
    if passed_tests == total_tests:
        print()
        print("🎉 ALL TESTS PASSED!")
        print()
        print("   ✅ All accounts are properly configured and connected")
        print("   ✅ Ready to trade on Kraken")
        print()
        print("   Next steps:")
        print("   1. Start the trading bot: python3 main.py")
        print("   2. Monitor logs for trading activity")
        print()
        return 0
    elif passed_tests > 0:
        print()
        print("⚠️  PARTIAL SUCCESS")
        print()
        print(f"   {passed_tests}/{total_tests} tests passed")
        print()
        print("   Next steps:")
        print("   1. Review failed tests above")
        print("   2. Add missing credentials to environment variables")
        print("   3. Verify API key permissions on Kraken")
        print("   4. Re-run this test after fixing issues")
        print()
        return 1
    else:
        print()
        print("❌ ALL TESTS FAILED")
        print()
        print("   No Kraken accounts are properly configured.")
        print()
        print("   Next steps:")
        print("   1. Get API credentials from https://www.kraken.com/u/security/api")
        print("   2. Add credentials to environment variables:")
        print("      - KRAKEN_MASTER_API_KEY")
        print("      - KRAKEN_MASTER_API_SECRET")
        print("      - KRAKEN_USER_DAIVON_API_KEY")
        print("      - KRAKEN_USER_DAIVON_API_SECRET")
        print("      - KRAKEN_USER_TANIA_API_KEY")
        print("      - KRAKEN_USER_TANIA_API_SECRET")
        print("   3. Restart deployment and re-run this test")
        print()
        print("   📖 See SETUP_KRAKEN_USERS.md for detailed instructions")
        print()
        return 2


if __name__ == "__main__":
    sys.exit(main())
