#!/usr/bin/env python3
"""
Kraken Deployment Verification Script for Railway & Render

This script verifies if Kraken API credentials are properly configured
in the deployment environment variables for production use.

Usage:
    python3 verify_deployment_kraken.py
    ./verify_deployment_kraken.py

Exit codes:
    0 = All credentials configured and ready for production
    1 = Partial configuration (some accounts missing)
    2 = No credentials configured (not ready for production)
"""

import os
import sys


def check_env_var(var_name):
    """Check if environment variable is set and not empty"""
    value = os.getenv(var_name, '').strip()
    is_set = bool(value)
    
    # Mask the value for security (show first 4 and last 4 chars only)
    if is_set and len(value) > 8:
        masked_value = f"{value[:4]}...{value[-4:]}"
    elif is_set:
        masked_value = "****"
    else:
        masked_value = None
    
    return is_set, masked_value


def print_header(title, width=80):
    """Print a formatted header"""
    print()
    print("=" * width)
    print(title.center(width))
    print("=" * width)


def print_section(title, width=80):
    """Print a formatted section header"""
    print()
    print(title)
    print("-" * width)


def print_credential_status(account_name, key_var, secret_var):
    """Print the status of a credential pair"""
    key_set, key_value = check_env_var(key_var)
    secret_set, secret_value = check_env_var(secret_var)
    
    print(f"\n{account_name}:")
    
    # API Key status
    if key_set:
        print(f"  ✅ {key_var}: SET ({key_value})")
    else:
        print(f"  ❌ {key_var}: NOT SET")
    
    # API Secret status
    if secret_set:
        print(f"  ✅ {secret_var}: SET ({secret_value})")
    else:
        print(f"  ❌ {secret_var}: NOT SET")
    
    # Overall status
    configured = key_set and secret_set
    if configured:
        print(f"  Status: ✅ CONFIGURED - Ready to trade")
    else:
        print(f"  Status: ❌ NOT CONFIGURED - Cannot trade")
    
    return configured


def detect_platform():
    """Detect which deployment platform we're running on"""
    if os.getenv('RAILWAY_ENVIRONMENT'):
        return 'Railway'
    elif os.getenv('RENDER'):
        return 'Render'
    elif os.getenv('DYNO'):
        return 'Heroku'
    else:
        return 'Unknown/Local'


def main():
    """Main verification function"""
    
    print_header("KRAKEN DEPLOYMENT VERIFICATION")
    
    # Detect platform
    platform = detect_platform()
    print()
    print(f"🖥️  Detected Platform: {platform}")
    
    # Check all credentials
    print_section("🔍 CHECKING KRAKEN API CREDENTIALS")
    
    # Master account
    master_configured = print_credential_status(
        "🔑 Master Account (NIJA System)",
        "KRAKEN_MASTER_API_KEY",
        "KRAKEN_MASTER_API_SECRET"
    )
    
    # User #1 (Daivon Frazier)
    user1_configured = print_credential_status(
        "👤 User #1 (Daivon Frazier)",
        "KRAKEN_USER_DAIVON_API_KEY",
        "KRAKEN_USER_DAIVON_API_SECRET"
    )
    
    # User #2 (Tania Gilbert)
    user2_configured = print_credential_status(
        "👤 User #2 (Tania Gilbert)",
        "KRAKEN_USER_TANIA_API_KEY",
        "KRAKEN_USER_TANIA_API_SECRET"
    )
    
    # Summary
    print_header("📊 DEPLOYMENT READINESS SUMMARY")
    
    total_configured = sum([master_configured, user1_configured, user2_configured])
    
    print()
    print(f"  Configured Accounts: {total_configured}/3")
    print()
    
    # Account status table
    accounts = [
        ("Master Account", master_configured),
        ("User #1 (Daivon Frazier)", user1_configured),
        ("User #2 (Tania Gilbert)", user2_configured)
    ]
    
    for account_name, is_configured in accounts:
        icon = "✅" if is_configured else "❌"
        status = "READY to trade on Kraken" if is_configured else "NOT READY (missing credentials)"
        print(f"  {icon} {account_name}: {status}")
    
    # Deployment status
    print_header("🚀 DEPLOYMENT STATUS")
    
    if total_configured == 3:
        print()
        print("  ✅ ALL ACCOUNTS CONFIGURED")
        print()
        print(f"  Your {platform} deployment is ready for Kraken trading!")
        print()
        print("  All three accounts will connect to Kraken when the bot starts:")
        print("    • Master account: Will trade on Kraken")
        print("    • User #1 (Daivon): Will trade on Kraken")
        print("    • User #2 (Tania): Will trade on Kraken")
        print()
        print("  Next Steps:")
        print("    1. Deploy or redeploy your application")
        print("    2. Check deployment logs for Kraken connection confirmations")
        print("    3. Look for: ✅ Connected to Kraken Pro API (MASTER)")
        print("    4. Look for: ✅ User #1 Kraken connected")
        print("    5. Look for: ✅ User #2 Kraken connected")
        print()
        exit_code = 0
        
    elif total_configured > 0:
        print()
        print(f"  ⚠️  PARTIAL CONFIGURATION: {total_configured}/3 accounts")
        print()
        print("  Some accounts are ready, but not all:")
        print()
        
        # Show what's configured
        if master_configured or user1_configured or user2_configured:
            print("  Configured accounts:")
            if master_configured:
                print("    ✅ Master account: Will trade on Kraken")
            if user1_configured:
                print("    ✅ User #1 (Daivon): Will trade on Kraken")
            if user2_configured:
                print("    ✅ User #2 (Tania): Will trade on Kraken")
            print()
        
        # Show what's missing
        print("  Missing accounts (add these to enable):")
        if not master_configured:
            print("    ❌ Master account:")
            print("       Add: KRAKEN_MASTER_API_KEY")
            print("       Add: KRAKEN_MASTER_API_SECRET")
        if not user1_configured:
            print("    ❌ User #1 (Daivon):")
            print("       Add: KRAKEN_USER_DAIVON_API_KEY")
            print("       Add: KRAKEN_USER_DAIVON_API_SECRET")
        if not user2_configured:
            print("    ❌ User #2 (Tania):")
            print("       Add: KRAKEN_USER_TANIA_API_KEY")
            print("       Add: KRAKEN_USER_TANIA_API_SECRET")
        print()
        exit_code = 1
        
    else:
        print()
        print("  ❌ NO ACCOUNTS CONFIGURED")
        print()
        print(f"  Your {platform} deployment is NOT configured for Kraken trading.")
        print()
        print("  None of the Kraken API credentials are set in environment variables.")
        print()
        print("  To enable Kraken trading, add these environment variables:")
        print()
        print("  Master Account:")
        print("    KRAKEN_MASTER_API_KEY=<your-api-key>")
        print("    KRAKEN_MASTER_API_SECRET=<your-api-secret>")
        print()
        print("  User #1 (Daivon Frazier):")
        print("    KRAKEN_USER_DAIVON_API_KEY=<daivon-api-key>")
        print("    KRAKEN_USER_DAIVON_API_SECRET=<daivon-api-secret>")
        print()
        print("  User #2 (Tania Gilbert):")
        print("    KRAKEN_USER_TANIA_API_KEY=<tania-api-key>")
        print("    KRAKEN_USER_TANIA_API_SECRET=<tania-api-secret>")
        print()
        exit_code = 2
    
    # Platform-specific instructions
    print_header("📝 HOW TO ADD CREDENTIALS")
    
    print()
    if platform == 'Railway':
        print("  For Railway Deployment:")
        print("    1. Go to https://railway.app")
        print("    2. Open your NIJA bot project")
        print("    3. Click on your service")
        print("    4. Navigate to 'Variables' tab")
        print("    5. Click '+ New Variable' for each credential")
        print("    6. Railway will auto-redeploy with new variables")
        print()
    elif platform == 'Render':
        print("  For Render Deployment:")
        print("    1. Go to https://render.com")
        print("    2. Open your NIJA bot service")
        print("    3. Navigate to 'Environment' tab")
        print("    4. Click 'Add Environment Variable' for each credential")
        print("    5. Click 'Save Changes' when done")
        print("    6. Render will auto-redeploy")
        print()
    else:
        print("  For Railway:")
        print("    Dashboard → Service → Variables → + New Variable")
        print()
        print("  For Render:")
        print("    Dashboard → Service → Environment → Add Environment Variable")
        print()
    
    print("  📖 Detailed instructions: See DEPLOYMENT_KRAKEN_STATUS.md")
    print()
    
    print("=" * 80)
    print()
    
    # Security reminder
    if total_configured < 3:
        print("🔒 Security Reminder:")
        print("   • Never commit API keys to git")
        print("   • Always use environment variables for credentials")
        print("   • Enable 2FA on all Kraken accounts")
        print("   • Use IP whitelisting on API keys when possible")
        print()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
