#!/usr/bin/env python3
"""
Enhanced Kraken Connection Diagnostic Tool

This script provides a comprehensive diagnosis of why Kraken is not connecting,
with actionable recommendations based on the current state.

Usage:
    python3 diagnose_kraken_connection.py

Features:
- Checks environment variables for all accounts
- Provides specific next steps based on what's missing
- Shows exact commands to run
- Generates ready-to-use environment variable exports
"""

import os
import sys


def print_header(title, char="="):
    """Print a formatted header"""
    width = 80
    print()
    print(char * width)
    print(title.center(width))
    print(char * width)
    print()


def print_section(title):
    """Print a section header"""
    print()
    print(f"{'─' * 80}")
    print(f"  {title}")
    print(f"{'─' * 80}")


def check_env_var(var_name):
    """Check if environment variable is set and return its value (masked)"""
    value = os.getenv(var_name, '').strip()
    if value:
        # Mask the value for security (show first 4 and last 4 chars)
        if len(value) > 12:
            masked = f"{value[:4]}...{value[-4:]}"
        else:
            masked = "***"
        return True, masked
    return False, None


def main():
    """Main diagnostic function"""
    
    print_header("🔍 KRAKEN CONNECTION DIAGNOSTIC")
    
    print("This tool will help you understand why Kraken is not connecting")
    print("and provide specific steps to fix the issue.")
    
    # Track what's configured
    issues_found = []
    recommendations = []
    
    # Check Master Account
    print_section("MASTER ACCOUNT (NIJA System)")
    
    master_key_set, master_key_val = check_env_var("KRAKEN_MASTER_API_KEY")
    master_secret_set, master_secret_val = check_env_var("KRAKEN_MASTER_API_SECRET")
    
    if master_key_set:
        print(f"  ✅ KRAKEN_MASTER_API_KEY: SET ({master_key_val})")
    else:
        print(f"  ❌ KRAKEN_MASTER_API_KEY: NOT SET")
        issues_found.append("Master API key missing")
    
    if master_secret_set:
        print(f"  ✅ KRAKEN_MASTER_API_SECRET: SET ({master_secret_val})")
    else:
        print(f"  ❌ KRAKEN_MASTER_API_SECRET: NOT SET")
        issues_found.append("Master API secret missing")
    
    master_configured = master_key_set and master_secret_set
    
    if master_configured:
        print(f"\n  ✅ RESULT: Master account is configured for Kraken")
    else:
        print(f"\n  ❌ RESULT: Master account CANNOT connect to Kraken")
        recommendations.append({
            'title': 'Configure Master Account',
            'steps': [
                '1. Create Kraken API key at https://www.kraken.com/u/security/api',
                '2. Enable these permissions:',
                '   • Query Funds',
                '   • Query Open Orders & Trades',
                '   • Query Closed Orders & Trades',
                '   • Create & Modify Orders',
                '   • Cancel/Close Orders',
                '3. Set environment variables (see commands below)',
                '4. Restart the bot/deployment'
            ]
        })
    
    # Check User #1 (Daivon)
    print_section("USER #1: Daivon Frazier (daivon_frazier)")
    
    daivon_key_set, daivon_key_val = check_env_var("KRAKEN_USER_DAIVON_API_KEY")
    daivon_secret_set, daivon_secret_val = check_env_var("KRAKEN_USER_DAIVON_API_SECRET")
    
    if daivon_key_set:
        print(f"  ✅ KRAKEN_USER_DAIVON_API_KEY: SET ({daivon_key_val})")
    else:
        print(f"  ❌ KRAKEN_USER_DAIVON_API_KEY: NOT SET")
    
    if daivon_secret_set:
        print(f"  ✅ KRAKEN_USER_DAIVON_API_SECRET: SET ({daivon_secret_val})")
    else:
        print(f"  ❌ KRAKEN_USER_DAIVON_API_SECRET: NOT SET")
    
    daivon_configured = daivon_key_set and daivon_secret_set
    
    if daivon_configured:
        print(f"\n  ✅ RESULT: User #1 (Daivon) is configured for Kraken")
    else:
        print(f"\n  ⚠️  RESULT: User #1 (Daivon) CANNOT trade on Kraken")
    
    # Check User #2 (Tania)
    print_section("USER #2: Tania Gilbert (tania_gilbert)")
    
    tania_key_set, tania_key_val = check_env_var("KRAKEN_USER_TANIA_API_KEY")
    tania_secret_set, tania_secret_val = check_env_var("KRAKEN_USER_TANIA_API_SECRET")
    
    if tania_key_set:
        print(f"  ✅ KRAKEN_USER_TANIA_API_KEY: SET ({tania_key_val})")
    else:
        print(f"  ❌ KRAKEN_USER_TANIA_API_KEY: NOT SET")
    
    if tania_secret_set:
        print(f"  ✅ KRAKEN_USER_TANIA_API_SECRET: SET ({tania_secret_val})")
    else:
        print(f"  ❌ KRAKEN_USER_TANIA_API_SECRET: NOT SET")
    
    tania_configured = tania_key_set and tania_secret_set
    
    if tania_configured:
        print(f"\n  ✅ RESULT: User #2 (Tania) is configured for Kraken")
    else:
        print(f"\n  ⚠️  RESULT: User #2 (Tania) CANNOT trade on Kraken")
    
    # Summary
    print_header("📊 DIAGNOSIS SUMMARY", "=")
    
    total_configured = sum([master_configured, daivon_configured, tania_configured])
    
    print(f"  Configured Accounts: {total_configured}/3\n")
    
    if master_configured:
        print("  ✅ Master account: Connected to Kraken")
    else:
        print("  ❌ Master account: NOT connected to Kraken")
    
    if daivon_configured:
        print("  ✅ User #1 (Daivon): Connected to Kraken")
    else:
        print("  ⚠️  User #1 (Daivon): NOT connected to Kraken")
    
    if tania_configured:
        print("  ✅ User #2 (Tania): Connected to Kraken")
    else:
        print("  ⚠️  User #2 (Tania): NOT connected to Kraken")
    
    print()
    
    # Provide recommendations
    if issues_found:
        print_header("🔧 RECOMMENDED ACTIONS", "=")
        
        for i, rec in enumerate(recommendations, 1):
            print(f"\n{rec['title']}:")
            for step in rec['steps']:
                print(f"  {step}")
        
        print()
        print_section("📋 COPY-PASTE COMMANDS")
        
        print("\n🔹 Local Development (.env file):\n")
        if not master_configured:
            print("# Add to .env file:")
            print("KRAKEN_MASTER_API_KEY=your-api-key-here")
            print("KRAKEN_MASTER_API_SECRET=your-api-secret-here")
            print()
        
        if not daivon_configured:
            print("# For User #1 (Daivon):")
            print("KRAKEN_USER_DAIVON_API_KEY=daivon-api-key")
            print("KRAKEN_USER_DAIVON_API_SECRET=daivon-api-secret")
            print()
        
        if not tania_configured:
            print("# For User #2 (Tania):")
            print("KRAKEN_USER_TANIA_API_KEY=tania-api-key")
            print("KRAKEN_USER_TANIA_API_SECRET=tania-api-secret")
            print()
        
        print("\n🔹 Bash Export (Linux/Mac):\n")
        if not master_configured:
            print("export KRAKEN_MASTER_API_KEY='your-api-key-here'")
            print("export KRAKEN_MASTER_API_SECRET='your-api-secret-here'")
        if not daivon_configured:
            print("export KRAKEN_USER_DAIVON_API_KEY='daivon-api-key'")
            print("export KRAKEN_USER_DAIVON_API_SECRET='daivon-api-secret'")
        if not tania_configured:
            print("export KRAKEN_USER_TANIA_API_KEY='tania-api-key'")
            print("export KRAKEN_USER_TANIA_API_SECRET='tania-api-secret'")
        
        print()
        print_section("☁️  RAILWAY/RENDER DEPLOYMENT")
        
        print("\n📦 Railway:")
        print("  1. Go to: https://railway.app/")
        print("  2. Select your project → Select your service")
        print("  3. Navigate to 'Variables' tab")
        print("  4. Click 'New Variable' and add each variable:")
        if not master_configured:
            print("     • KRAKEN_MASTER_API_KEY = your-api-key-here")
            print("     • KRAKEN_MASTER_API_SECRET = your-api-secret-here")
        if not daivon_configured:
            print("     • KRAKEN_USER_DAIVON_API_KEY = daivon-api-key")
            print("     • KRAKEN_USER_DAIVON_API_SECRET = daivon-api-secret")
        if not tania_configured:
            print("     • KRAKEN_USER_TANIA_API_KEY = tania-api-key")
            print("     • KRAKEN_USER_TANIA_API_SECRET = tania-api-secret")
        print("  5. Railway will automatically redeploy")
        
        print("\n📦 Render:")
        print("  1. Go to: https://dashboard.render.com/")
        print("  2. Select your web service")
        print("  3. Navigate to 'Environment' tab")
        print("  4. Add each variable:")
        if not master_configured:
            print("     • KRAKEN_MASTER_API_KEY = your-api-key-here")
            print("     • KRAKEN_MASTER_API_SECRET = your-api-secret-here")
        if not daivon_configured:
            print("     • KRAKEN_USER_DAIVON_API_KEY = daivon-api-key")
            print("     • KRAKEN_USER_DAIVON_API_SECRET = daivon-api-secret")
        if not tania_configured:
            print("     • KRAKEN_USER_TANIA_API_KEY = tania-api-key")
            print("     • KRAKEN_USER_TANIA_API_SECRET = tania-api-secret")
        print("  5. Click 'Save Changes'")
        print("  6. Manually deploy: 'Manual Deploy' → 'Deploy latest commit'")
        
        print()
        print_section("📖 ADDITIONAL RESOURCES")
        print()
        print("  • KRAKEN_NOT_CONNECTING_DIAGNOSIS.md - Complete diagnosis guide")
        print("  • KRAKEN_SETUP_GUIDE.md - Detailed Kraken setup instructions")
        print("  • MULTI_USER_SETUP_GUIDE.md - User account configuration")
        print("  • .env.example - Template with all environment variables")
        print()
        print("  Run these commands for more info:")
        print("    python3 check_kraken_status.py       # Quick status check")
        print("    python3 verify_kraken_enabled.py     # Verify code configuration")
        print()
    else:
        print_header("✅ ALL KRAKEN ACCOUNTS CONFIGURED!", "=")
        print()
        print("All Kraken accounts are properly configured with credentials.")
        print()
        print("If Kraken is still not connecting, check for:")
        print("  • API key permissions (must have trading permissions)")
        print("  • Network connectivity issues")
        print("  • Kraken API status: https://status.kraken.com/")
        print()
        print("Check the bot logs for specific connection error messages.")
        print()
    
    print("=" * 80)
    print()
    
    # Exit code based on configuration status
    if total_configured == 3:
        return 0  # All configured
    elif total_configured > 0:
        return 1  # Partial configuration
    else:
        return 2  # No configuration


if __name__ == "__main__":
    sys.exit(main())
