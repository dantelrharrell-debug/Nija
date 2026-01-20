#!/usr/bin/env python3
"""
Verify Kraken User Credentials - Test Connection for Daivon & Tania

This script validates the locked Kraken credentials and tests the connection
for both user accounts before deployment.

Usage:
    python3 verify_kraken_user_credentials.py
"""

import os
import sys
import time

# Try to load environment variables from locked credentials file
try:
    from dotenv import load_dotenv
    # Load locked credentials if available
    if os.path.exists('.env.kraken_users_locked'):
        load_dotenv('.env.kraken_users_locked')
        print("✅ Loaded credentials from .env.kraken_users_locked")
    elif os.path.exists('.env'):
        load_dotenv('.env')
        print("✅ Loaded credentials from .env")
    else:
        print("⚠️  No .env file found, using system environment variables")
except ImportError:
    print("⚠️  python-dotenv not installed, using system environment variables")

def print_header():
    """Print validation header"""
    print()
    print("=" * 80)
    print("    KRAKEN USER CREDENTIALS VALIDATION")
    print("    Users: Daivon Frazier & Tania Gilbert")
    print("=" * 80)
    print()

def check_credential_format(api_key, api_secret, user_name):
    """
    Validate credential format for Kraken API keys
    
    Args:
        api_key: The API key string
        api_secret: The API secret string
        user_name: Name of the user (for logging)
    
    Returns:
        tuple: (is_valid, message)
    """
    issues = []
    
    # Check API Key
    if not api_key:
        issues.append("API Key is empty")
    elif len(api_key.strip()) < 50:
        issues.append(f"API Key is too short ({len(api_key)} chars, expected 50+)")
    elif api_key != api_key.strip():
        issues.append("API Key has leading/trailing whitespace")
    
    # Check API Secret
    if not api_secret:
        issues.append("API Secret is empty")
    elif len(api_secret.strip()) < 80:
        issues.append(f"API Secret is too short ({len(api_secret)} chars, expected 80+)")
    elif api_secret != api_secret.strip():
        issues.append("API Secret has leading/trailing whitespace")
    
    if issues:
        return False, "; ".join(issues)
    else:
        return True, f"Format OK (Key: {len(api_key)} chars, Secret: {len(api_secret)} chars)"

def test_kraken_connection(api_key, api_secret, user_name):
    """
    Test actual connection to Kraken API
    
    Args:
        api_key: The API key string
        api_secret: The API secret string
        user_name: Name of the user (for logging)
    
    Returns:
        tuple: (is_connected, message, balance_info)
    """
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        
        # Create Kraken API client
        kraken = krakenex.API(key=api_key, secret=api_secret)
        k = KrakenAPI(kraken)
        
        # Test connection by fetching balance
        print(f"      🔄 Testing connection to Kraken API...")
        balance = k.get_account_balance()
        
        # Calculate total balance value
        if not balance.empty:
            balance_info = {}
            for currency in balance.index:
                amount = float(balance.loc[currency, 'vol'])
                if amount > 0:
                    balance_info[currency] = amount
            
            total_assets = len(balance_info)
            balance_str = ", ".join([f"{curr}: {amt:.4f}" for curr, amt in list(balance_info.items())[:3]])
            if total_assets > 3:
                balance_str += f" ... (+{total_assets - 3} more)"
            
            return True, "Connection successful", balance_info
        else:
            return True, "Connection successful (empty balance)", {}
    
    except ImportError:
        return False, "Kraken SDK not installed (krakenex, pykrakenapi required)", None
    except Exception as e:
        error_msg = str(e)
        # Check for common errors
        if "Invalid key" in error_msg or "API key" in error_msg:
            return False, "Invalid API credentials", None
        elif "Permission denied" in error_msg:
            return False, "API key lacks required permissions", None
        elif "Invalid nonce" in error_msg or "nonce" in error_msg.lower():
            return False, "Nonce error (may resolve on retry)", None
        else:
            return False, f"Connection error: {error_msg[:100]}", None

def validate_user_credentials(user_id, user_name, env_key, env_secret):
    """
    Validate credentials for a single user
    
    Args:
        user_id: User identifier (e.g., 'daivon_frazier')
        user_name: Display name (e.g., 'Daivon Frazier')
        env_key: Environment variable name for API key
        env_secret: Environment variable name for API secret
    
    Returns:
        bool: True if validation successful
    """
    print(f"👤 USER: {user_name} (ID: {user_id})")
    print("-" * 80)
    
    # Get credentials from environment
    api_key = os.getenv(env_key, '').strip()
    api_secret = os.getenv(env_secret, '').strip()
    
    # Step 1: Check if credentials exist
    if not api_key or not api_secret:
        print(f"   ❌ CREDENTIALS NOT FOUND")
        print(f"      Missing: {env_key if not api_key else env_secret}")
        print(f"      Required environment variables:")
        print(f"         {env_key}=<api-key>")
        print(f"         {env_secret}=<api-secret>")
        print()
        return False
    
    print(f"   ✅ Credentials found in environment")
    
    # Step 2: Validate format
    is_valid, format_msg = check_credential_format(api_key, api_secret, user_name)
    if not is_valid:
        print(f"   ❌ FORMAT ERROR: {format_msg}")
        print()
        return False
    
    print(f"   ✅ Format validation: {format_msg}")
    
    # Step 3: Test connection
    is_connected, conn_msg, balance_info = test_kraken_connection(api_key, api_secret, user_name)
    
    if is_connected:
        print(f"   ✅ Connection test: {conn_msg}")
        if balance_info:
            print(f"   💰 Account balance:")
            for currency, amount in balance_info.items():
                print(f"      {currency}: {amount:.4f}")
    else:
        print(f"   ❌ Connection test FAILED: {conn_msg}")
        print()
        return False
    
    print()
    return True

def main():
    """Main validation function"""
    print_header()
    
    # User definitions
    users = [
        {
            'user_id': 'daivon_frazier',
            'name': 'Daivon Frazier',
            'env_key': 'KRAKEN_USER_DAIVON_API_KEY',
            'env_secret': 'KRAKEN_USER_DAIVON_API_SECRET'
        },
        {
            'user_id': 'tania_gilbert',
            'name': 'Tania Gilbert',
            'env_key': 'KRAKEN_USER_TANIA_API_KEY',
            'env_secret': 'KRAKEN_USER_TANIA_API_SECRET'
        }
    ]
    
    # Validate each user
    results = {}
    for user in users:
        success = validate_user_credentials(
            user['user_id'],
            user['name'],
            user['env_key'],
            user['env_secret']
        )
        results[user['name']] = success
    
    # Print summary
    print("=" * 80)
    print("    VALIDATION SUMMARY")
    print("=" * 80)
    print()
    
    all_passed = all(results.values())
    
    for user_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"   {user_name}: {status}")
    
    print()
    print("-" * 80)
    
    if all_passed:
        print()
        print("✅ ALL CREDENTIALS VALIDATED SUCCESSFULLY")
        print()
        print("🚀 READY FOR DEPLOYMENT")
        print()
        print("Next Steps:")
        print("   1. Copy credentials from .env.kraken_users_locked to deployment platform")
        print("   2. Deploy to Railway/Render")
        print("   3. Check logs for 'USER: [Name]: TRADING (Broker: KRAKEN)'")
        print()
        return 0
    else:
        print()
        print("❌ VALIDATION FAILED")
        print()
        print("Action Required:")
        print("   1. Check that credentials are correctly set in .env.kraken_users_locked")
        print("   2. Verify API keys at https://www.kraken.com/u/security/api")
        print("   3. Ensure API keys have required permissions:")
        print("      ✅ Query Funds")
        print("      ✅ Query Open Orders & Trades")
        print("      ✅ Query Closed Orders & Trades")
        print("      ✅ Create & Modify Orders")
        print("      ✅ Cancel/Close Orders")
        print("   4. Re-run this validation script")
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())
