#!/usr/bin/env python3
"""
Kraken Credentials Checker
Verifies which Kraken API credentials are configured and provides actionable feedback.
"""

import os
import sys

def check_env_var(var_name):
    """Check if an environment variable is set and not empty."""
    value = os.getenv(var_name)
    if value and value.strip():
        return True, "SET"
    elif value is not None and not value.strip():
        return False, "SET but EMPTY"
    else:
        return False, "NOT SET"

def main():
    print("=" * 80)
    print("  KRAKEN CREDENTIALS CHECK")
    print("=" * 80)
    print()
    
    # Define required credentials
    credentials = {
        "Master Account": [
            "KRAKEN_MASTER_API_KEY",
            "KRAKEN_MASTER_API_SECRET"
        ],
        "Daivon Frazier": [
            "KRAKEN_USER_DAIVON_API_KEY",
            "KRAKEN_USER_DAIVON_API_SECRET"
        ],
        "Tania Gilbert": [
            "KRAKEN_USER_TANIA_API_KEY",
            "KRAKEN_USER_TANIA_API_SECRET"
        ]
    }
    
    # Check each account
    all_configured = True
    configured_count = 0
    total_accounts = len(credentials)
    
    for account_name, vars_list in credentials.items():
        print(f"📊 {account_name}:")
        account_configured = True
        
        for var_name in vars_list:
            is_set, status = check_env_var(var_name)
            
            if is_set:
                print(f"   ✅ {var_name}: {status}")
            else:
                print(f"   ❌ {var_name}: {status}")
                account_configured = False
                all_configured = False
        
        if account_configured:
            print(f"   ✅ {account_name} is READY TO TRADE")
            configured_count += 1
        else:
            print(f"   ❌ {account_name} CANNOT TRADE - missing credentials")
        print()
    
    # Summary
    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  • Accounts configured: {configured_count}/{total_accounts}")
    print()
    
    if all_configured:
        print("✅ ALL ACCOUNTS CONFIGURED - Ready to trade!")
        print()
        print("Next steps:")
        print("  1. Restart your deployment (if not already restarted)")
        print("  2. Check logs for connection messages")
        print("  3. Verify trading activity begins")
        print()
        print("Verification commands:")
        print("  python3 test_kraken_users.py")
        print("  python3 display_broker_status.py")
        return 0
    else:
        print("❌ INCOMPLETE CONFIGURATION")
        print()
        print("Missing credentials detected. To fix:")
        print()
        print("Step 1: Get API keys from Kraken")
        print("  • Go to: https://www.kraken.com/u/security/api")
        print("  • Create separate keys for each account")
        print("  • Enable permissions: Query Funds, Query Orders, Create Orders, Cancel Orders")
        print()
        print("Step 2: Add to your deployment platform")
        print()
        print("  For Railway:")
        print("    1. Go to https://railway.app/dashboard")
        print("    2. Select your NIJA project")
        print("    3. Click 'Variables' tab")
        print("    4. Add the missing environment variables above")
        print()
        print("  For Render:")
        print("    1. Go to https://dashboard.render.com")
        print("    2. Select your NIJA service")
        print("    3. Click 'Environment' tab")
        print("    4. Add the missing environment variables above")
        print()
        print("Step 3: Restart and verify")
        print("  • Deployment will auto-restart when you save variables")
        print("  • Check logs for connection confirmations")
        print("  • Run this script again to verify")
        print()
        print("📖 Complete guide: KRAKEN_USER_SETUP_SOLUTION_JAN_18_2026.md")
        return 1
    
    print("=" * 80)

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
