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
    """
    Check if environment variable is set and return its value (masked).
    
    Returns:
        tuple: (is_valid, masked_value, is_malformed)
            - is_valid: True if variable is set and has valid content after stripping
            - masked_value: Masked representation of the value for security
            - is_malformed: True if variable is set but contains only whitespace
    """
    value_raw = os.getenv(var_name, '')
    value_stripped = value_raw.strip()
    
    # Check if variable is set but becomes empty after stripping (malformed)
    is_malformed = (value_raw != '' and value_stripped == '')
    
    if value_stripped:
        # Mask the value for security (show first 4 and last 4 chars)
        if len(value_stripped) > 12:
            masked = f"{value_stripped[:4]}...{value_stripped[-4:]}"
        else:
            masked = "***"
        return True, masked, False
    elif is_malformed:
        # Variable is set but only contains whitespace
        return False, None, True
    else:
        # Variable is not set at all
        return False, None, False


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
    
    master_key_set, master_key_val, master_key_malformed = check_env_var("KRAKEN_MASTER_API_KEY")
    master_secret_set, master_secret_val, master_secret_malformed = check_env_var("KRAKEN_MASTER_API_SECRET")
    
    # Check legacy credentials as fallback
    legacy_key_set, legacy_key_val, legacy_key_malformed = check_env_var("KRAKEN_API_KEY")
    legacy_secret_set, legacy_secret_val, legacy_secret_malformed = check_env_var("KRAKEN_API_SECRET")
    
    # Legacy credentials are only valid if BOTH are set and valid
    legacy_configured = legacy_key_set and legacy_secret_set and not legacy_key_malformed and not legacy_secret_malformed
    
    if master_key_malformed:
        print(f"  ⚠️  KRAKEN_MASTER_API_KEY: SET BUT INVALID (contains only whitespace/invisible characters)")
        issues_found.append("Master API key is set but contains only whitespace")
    elif master_key_set:
        print(f"  ✅ KRAKEN_MASTER_API_KEY: SET ({master_key_val})")
    elif legacy_configured:
        print(f"  💡 KRAKEN_MASTER_API_KEY: NOT SET (will use legacy KRAKEN_API_KEY: {legacy_key_val})")
    else:
        print(f"  ❌ KRAKEN_MASTER_API_KEY: NOT SET")
        if legacy_key_set and legacy_key_malformed:
            print(f"     ⚠️  KRAKEN_API_KEY (legacy) is SET BUT INVALID (whitespace only)")
            issues_found.append("Legacy API key is set but contains only whitespace")
        elif legacy_key_set and not legacy_secret_set:
            print(f"     ⚠️  KRAKEN_API_KEY (legacy) is set but KRAKEN_API_SECRET is missing")
        elif not legacy_key_set:
            issues_found.append("Master API key missing")
    
    if master_secret_malformed:
        print(f"  ⚠️  KRAKEN_MASTER_API_SECRET: SET BUT INVALID (contains only whitespace/invisible characters)")
        issues_found.append("Master API secret is set but contains only whitespace")
    elif master_secret_set:
        print(f"  ✅ KRAKEN_MASTER_API_SECRET: SET ({master_secret_val})")
    elif legacy_configured:
        print(f"  💡 KRAKEN_MASTER_API_SECRET: NOT SET (will use legacy KRAKEN_API_SECRET: {legacy_secret_val})")
    else:
        print(f"  ❌ KRAKEN_MASTER_API_SECRET: NOT SET")
        if legacy_secret_set and legacy_secret_malformed:
            print(f"     ⚠️  KRAKEN_API_SECRET (legacy) is SET BUT INVALID (whitespace only)")
            issues_found.append("Legacy API secret is set but contains only whitespace")
        elif legacy_secret_set and not legacy_key_set:
            print(f"     ⚠️  KRAKEN_API_SECRET (legacy) is set but KRAKEN_API_KEY is missing")
        elif not legacy_secret_set:
            issues_found.append("Master API secret missing")
    
    master_configured = master_key_set and master_secret_set
    master_has_malformed = master_key_malformed or master_secret_malformed
    
    if master_configured:
        print(f"\n  ✅ RESULT: Master account is configured for Kraken")
    elif master_has_malformed:
        print(f"\n  ⚠️  RESULT: Master account credentials are SET but INVALID")
        print(f"     The environment variables contain only whitespace or invisible characters")
        recommendations.append({
            'title': 'Fix Malformed Master Credentials',
            'steps': [
                '1. Go to your deployment platform (Railway/Render)',
                '2. Navigate to Environment Variables settings',
                '3. Check KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET',
                '4. Remove any leading/trailing spaces or newlines',
                '5. Ensure values contain only the actual API key/secret (no extra whitespace)',
                '6. Save and re-deploy',
                '',
                '⚠️  Common issues:',
                '   • Accidentally pasted newline characters from text editor',
                '   • Extra spaces before or after the value',
                '   • Tab characters mixed with the value',
                '   • Copy-paste artifacts from formatted documents'
            ]
        })
    elif legacy_configured:
        print(f"\n  ✅ RESULT: Master account will use LEGACY credentials (KRAKEN_API_KEY)")
        print(f"     Legacy credentials detected - bot will automatically use them")
        print(f"     💡 TIP: Consider renaming to KRAKEN_MASTER_API_KEY for clarity")
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
    
    daivon_key_set, daivon_key_val, daivon_key_malformed = check_env_var("KRAKEN_USER_DAIVON_API_KEY")
    daivon_secret_set, daivon_secret_val, daivon_secret_malformed = check_env_var("KRAKEN_USER_DAIVON_API_SECRET")
    
    if daivon_key_malformed:
        print(f"  ⚠️  KRAKEN_USER_DAIVON_API_KEY: SET BUT INVALID (contains only whitespace/invisible characters)")
    elif daivon_key_set:
        print(f"  ✅ KRAKEN_USER_DAIVON_API_KEY: SET ({daivon_key_val})")
    else:
        print(f"  ❌ KRAKEN_USER_DAIVON_API_KEY: NOT SET")
    
    if daivon_secret_malformed:
        print(f"  ⚠️  KRAKEN_USER_DAIVON_API_SECRET: SET BUT INVALID (contains only whitespace/invisible characters)")
    elif daivon_secret_set:
        print(f"  ✅ KRAKEN_USER_DAIVON_API_SECRET: SET ({daivon_secret_val})")
    else:
        print(f"  ❌ KRAKEN_USER_DAIVON_API_SECRET: NOT SET")
    
    daivon_configured = daivon_key_set and daivon_secret_set
    daivon_has_malformed = daivon_key_malformed or daivon_secret_malformed
    
    if daivon_configured:
        print(f"\n  ✅ RESULT: User #1 (Daivon) is configured for Kraken")
    elif daivon_has_malformed:
        print(f"\n  ⚠️  RESULT: User #1 (Daivon) credentials are SET but INVALID (whitespace only)")
    else:
        print(f"\n  ⚠️  RESULT: User #1 (Daivon) CANNOT trade on Kraken")
    
    # Check User #2 (Tania)
    print_section("USER #2: Tania Gilbert (tania_gilbert)")
    
    tania_key_set, tania_key_val, tania_key_malformed = check_env_var("KRAKEN_USER_TANIA_API_KEY")
    tania_secret_set, tania_secret_val, tania_secret_malformed = check_env_var("KRAKEN_USER_TANIA_API_SECRET")
    
    if tania_key_malformed:
        print(f"  ⚠️  KRAKEN_USER_TANIA_API_KEY: SET BUT INVALID (contains only whitespace/invisible characters)")
    elif tania_key_set:
        print(f"  ✅ KRAKEN_USER_TANIA_API_KEY: SET ({tania_key_val})")
    else:
        print(f"  ❌ KRAKEN_USER_TANIA_API_KEY: NOT SET")
    
    if tania_secret_malformed:
        print(f"  ⚠️  KRAKEN_USER_TANIA_API_SECRET: SET BUT INVALID (contains only whitespace/invisible characters)")
    elif tania_secret_set:
        print(f"  ✅ KRAKEN_USER_TANIA_API_SECRET: SET ({tania_secret_val})")
    else:
        print(f"  ❌ KRAKEN_USER_TANIA_API_SECRET: NOT SET")
    
    tania_configured = tania_key_set and tania_secret_set
    tania_has_malformed = tania_key_malformed or tania_secret_malformed
    
    if tania_configured:
        print(f"\n  ✅ RESULT: User #2 (Tania) is configured for Kraken")
    elif tania_has_malformed:
        print(f"\n  ⚠️  RESULT: User #2 (Tania) credentials are SET but INVALID (whitespace only)")
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
