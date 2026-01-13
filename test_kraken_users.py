#!/usr/bin/env python3
"""
Quick Kraken User Connection Test
==================================

Tests Kraken API connection for master account and all user accounts.
Provides immediate feedback on connection status.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Tuple

# Try to load .env file if available (for local testing)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, env vars should be set externally

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


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


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

def test_master_connection():
    """Test Kraken master account connection."""
    print("\n" + "="*80)
    print("🔍 Testing MASTER Account Connection")
    print("="*80)
    
    try:
        from bot.broker_manager import KrakenBroker, AccountType
        
        broker = KrakenBroker(account_type=AccountType.MASTER)
        
        if broker.connect():
            print("✅ MASTER account connected successfully")
            
            try:
                balance = broker.get_account_balance()
                print(f"💰 Master balance: ${balance:,.2f}")
                return True
            except Exception as e:
                print(f"⚠️  Connected but could not fetch balance: {e}")
                return True
        else:
            print("❌ MASTER account connection FAILED")
            print()
            print("   Possible causes:")
            print("   1. Missing credentials (KRAKEN_MASTER_API_KEY/SECRET not set)")
            print("   2. Invalid API key/secret")
            print("   3. Insufficient permissions on API key")
            print()
            print("   Fix: See SETUP_KRAKEN_USERS.md for instructions")
            return False
            
    except Exception as e:
        print(f"❌ Error testing master connection: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_user_connection(user_id: str, user_name: str):
    """Test Kraken connection for a specific user."""
    print("\n" + "="*80)
    print(f"🔍 Testing USER Account: {user_name} ({user_id})")
    print("="*80)
    
    try:
        from bot.broker_manager import KrakenBroker, AccountType
        
        broker = KrakenBroker(account_type=AccountType.USER, user_id=user_id)
        
        if broker.connect():
            print(f"✅ {user_name} connected successfully")
            
            try:
                balance = broker.get_account_balance()
                print(f"💰 {user_name} balance: ${balance:,.2f}")
                return True
            except Exception as e:
                print(f"⚠️  Connected but could not fetch balance: {e}")
                return True
        else:
            print(f"❌ {user_name} connection FAILED")
            print()
            
            # Get environment variable names using shared utility
            key_var, secret_var = get_user_env_var_names(user_id)
            
            print("   Possible causes:")
            print(f"   1. Missing credentials ({key_var}/SECRET not set)")
            print("   2. Invalid API key/secret")
            print("   3. Insufficient permissions on API key")
            print()
            print("   Fix: See SETUP_KRAKEN_USERS.md for instructions")
            return False
            
    except Exception as e:
        print(f"❌ Error testing {user_name} connection: {e}")
        import traceback
        traceback.print_exc()
        return False


def load_configured_users():
    """Load configured users from config files."""
    import json
    
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


def main():
    """Main test function."""
    print("\n" + "="*80)
    print("🚀 NIJA KRAKEN CONNECTION TEST")
    print("="*80)
    print()
    print("This script will test Kraken API connections for:")
    print("  • Master account (NIJA system)")
    print("  • All enabled user accounts")
    print()
    
    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    results = {}
    
    # Test master account
    results['master'] = test_master_connection()
    
    # Test user accounts
    users = load_configured_users()
    
    if not users:
        print("\n" + "="*80)
        print("ℹ️  No enabled users found in config/users/retail_kraken.json")
        print("="*80)
    else:
        for user in users:
            user_id = user.get('user_id')
            user_name = user.get('name', user_id)
            
            results[user_id] = test_user_connection(user_id, user_name)
    
    # Summary
    print("\n" + "="*80)
    print("📊 CONNECTION TEST SUMMARY")
    print("="*80)
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed
    
    print(f"   Total accounts tested: {total}")
    print(f"   ✅ Connected: {passed}")
    print(f"   ❌ Failed: {failed}")
    print()
    
    if failed == 0:
        print("🎉 ALL ACCOUNTS CONNECTED SUCCESSFULLY!")
        print()
        print("   Your users should now show as 'TRADING' when the bot starts.")
        print("   Run the main bot to start trading:")
        print("   $ python3 main.py")
    else:
        print("⚠️  SOME ACCOUNTS FAILED TO CONNECT")
        print()
        print("   Review the error messages above and:")
        print("   1. Verify credentials are set correctly")
        print("   2. Check API key permissions on Kraken")
        print("   3. See SETUP_KRAKEN_USERS.md for detailed instructions")
        print()
        print("   Quick verification:")
        print("   $ python3 verify_kraken_users.py")
    
    print("="*80)
    print()
    
    # Exit with appropriate code
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
