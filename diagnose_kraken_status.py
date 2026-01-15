#!/usr/bin/env python3
"""
KRAKEN CONNECTION DIAGNOSTIC TOOL
==================================

This script checks the current status of Kraken configuration and provides
specific guidance on what's missing and how to fix it.

Run this to understand why Kraken isn't connecting.
"""

import os
import sys

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def check_env_var(var_name):
    """Check if an environment variable is set and valid."""
    value = os.getenv(var_name, "")
    raw_value = os.getenv(var_name, None)
    
    if raw_value is None:
        return False, "NOT SET"
    elif value.strip() == "":
        return False, "SET but contains only whitespace (INVALID)"
    else:
        # Show first 8 and last 4 chars for verification
        masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
        return True, f"SET ({masked})"

def main():
    print("=" * 80)
    print("🔍 KRAKEN CONNECTION DIAGNOSTIC")
    print("=" * 80)
    print()
    
    # Check Master credentials
    print("📊 MASTER ACCOUNT (Required for Kraken to connect)")
    print("-" * 80)
    
    master_key_valid, master_key_status = check_env_var("KRAKEN_MASTER_API_KEY")
    master_secret_valid, master_secret_status = check_env_var("KRAKEN_MASTER_API_SECRET")
    
    print(f"   KRAKEN_MASTER_API_KEY:    {master_key_status}")
    print(f"   KRAKEN_MASTER_API_SECRET: {master_secret_status}")
    print()
    
    # Check legacy credentials (fallback)
    if not master_key_valid or not master_secret_valid:
        print("   Checking legacy credentials (fallback):")
        legacy_key_valid, legacy_key_status = check_env_var("KRAKEN_API_KEY")
        legacy_secret_valid, legacy_secret_status = check_env_var("KRAKEN_API_SECRET")
        print(f"   KRAKEN_API_KEY:           {legacy_key_status}")
        print(f"   KRAKEN_API_SECRET:        {legacy_secret_status}")
        print()
        
        if legacy_key_valid and legacy_secret_valid:
            master_configured = True
            print("   ✅ Master will use LEGACY credentials (KRAKEN_API_KEY)")
        else:
            master_configured = False
            print("   ❌ Master NOT configured (neither new nor legacy credentials)")
    else:
        master_configured = True
        print("   ✅ Master CONFIGURED")
    
    print()
    
    # Check User credentials
    print("👤 USER ACCOUNTS (Optional, but configured in code)")
    print("-" * 80)
    
    users = [
        ("daivon_frazier", "DAIVON", "Daivon Frazier"),
        ("tania_gilbert", "TANIA", "Tania Gilbert"),
    ]
    
    users_configured = []
    users_not_configured = []
    
    for user_id, env_name, display_name in users:
        print(f"   {display_name} ({user_id}):")
        key_var = f"KRAKEN_USER_{env_name}_API_KEY"
        secret_var = f"KRAKEN_USER_{env_name}_API_SECRET"
        
        key_valid, key_status = check_env_var(key_var)
        secret_valid, secret_status = check_env_var(secret_var)
        
        print(f"      {key_var}:    {key_status}")
        print(f"      {secret_var}: {secret_status}")
        
        if key_valid and secret_valid:
            print(f"      ✅ {display_name} CONFIGURED")
            users_configured.append(display_name)
        else:
            print(f"      ❌ {display_name} NOT configured")
            users_not_configured.append(display_name)
        print()
    
    # Check user config files
    print("📁 USER CONFIGURATION FILES")
    print("-" * 80)
    
    try:
        import json
        retail_kraken_file = "config/users/retail_kraken.json"
        
        if os.path.exists(retail_kraken_file):
            with open(retail_kraken_file, 'r') as f:
                retail_users = json.load(f)
            
            print(f"   {retail_kraken_file}:")
            if retail_users:
                for user in retail_users:
                    enabled = "✅ ENABLED" if user.get('enabled', True) else "⚪ DISABLED"
                    user_id = user.get('user_id', 'unknown')
                    name = user.get('name', 'unknown')
                    print(f"      • {name} ({user_id}): {enabled}")
            else:
                print("      ⚪ Empty (no users configured)")
        else:
            print(f"   ❌ {retail_kraken_file} not found")
        print()
        
        investor_kraken_file = "config/users/investor_kraken.json"
        if os.path.exists(investor_kraken_file):
            with open(investor_kraken_file, 'r') as f:
                investor_users = json.load(f)
            
            print(f"   {investor_kraken_file}:")
            if investor_users:
                for user in investor_users:
                    enabled = "✅ ENABLED" if user.get('enabled', True) else "⚪ DISABLED"
                    user_id = user.get('user_id', 'unknown')
                    name = user.get('name', 'unknown')
                    print(f"      • {name} ({user_id}): {enabled}")
            else:
                print("      ⚪ Empty (no investors configured)")
        else:
            print(f"   ⚪ {investor_kraken_file} not found")
        print()
    except Exception as e:
        print(f"   ⚠️  Error reading config files: {e}")
        print()
    
    # Summary
    print("=" * 80)
    print("📋 SUMMARY")
    print("=" * 80)
    print()
    
    if master_configured:
        print("✅ MASTER ACCOUNT: Ready to connect")
    else:
        print("❌ MASTER ACCOUNT: NOT configured (Kraken will NOT connect)")
        print()
        print("   🔧 To fix:")
        print("      1. Get API keys from https://www.kraken.com/u/security/api")
        print("      2. Add to Railway/Render environment variables:")
        print("         • KRAKEN_MASTER_API_KEY=<your-api-key>")
        print("         • KRAKEN_MASTER_API_SECRET=<your-private-key>")
        print("      3. Restart deployment")
        print()
    
    if users_configured:
        print(f"✅ USER ACCOUNTS: {len(users_configured)} configured ({', '.join(users_configured)})")
    
    if users_not_configured:
        print(f"❌ USER ACCOUNTS: {len(users_not_configured)} NOT configured ({', '.join(users_not_configured)})")
        print()
        print("   🔧 To fix:")
        for user_id, env_name, display_name in users:
            if display_name in users_not_configured:
                print(f"      {display_name}:")
                print(f"         1. Get API keys from {display_name}'s Kraken account")
                print(f"         2. Add to Railway/Render environment variables:")
                print(f"            • KRAKEN_USER_{env_name}_API_KEY=<api-key>")
                print(f"            • KRAKEN_USER_{env_name}_API_SECRET=<private-key>")
        print("      3. Restart deployment")
        print()
    
    print("=" * 80)
    print("🎯 WHAT THIS MEANS")
    print("=" * 80)
    print()
    
    if not master_configured and not users_configured:
        print("❌ KRAKEN WILL NOT CONNECT OR TRADE")
        print()
        print("   No Kraken credentials are configured. The bot will:")
        print("   • Skip Kraken master connection")
        print("   • Skip Kraken user connections")
        print("   • Trade only on other configured exchanges (e.g., Coinbase)")
        print()
        print("   📖 See KRAKEN_NOT_CONNECTED_SOLUTION.md for step-by-step fix")
        print()
    elif not master_configured:
        print("⚠️  KRAKEN MASTER WILL NOT CONNECT")
        print()
        print("   User credentials are configured but master is not.")
        print("   The bot will:")
        print("   • Skip Kraken master trading")
        print("   • Attempt to connect Kraken users (will succeed if credentials valid)")
        print("   • Users will trade if connected")
        print()
        print("   ℹ️  This is OK if you only want users to trade on Kraken")
        print("   📖 See KRAKEN_NOT_CONNECTED_SOLUTION.md to enable master trading")
        print()
    elif not users_configured:
        print("⚠️  KRAKEN USERS WILL NOT CONNECT")
        print()
        print("   Master credentials are configured but users are not.")
        print("   The bot will:")
        print("   • Connect Kraken master (will trade)")
        print("   • Skip Kraken user connections (credentials not found)")
        print()
        print("   ℹ️  This is OK if you only want master to trade on Kraken")
        print("   📖 See KRAKEN_NOT_CONNECTED_SOLUTION.md to enable user trading")
        print()
    else:
        print("✅ KRAKEN READY TO CONNECT")
        print()
        print("   All credentials are configured. The bot will:")
        print("   • Connect Kraken master (will trade)")
        print("   • Connect Kraken users (will trade)")
        print("   • Execute independent trading on Kraken for all accounts")
        print()
        print("   If Kraken is still not connecting after this, check:")
        print("   • API key permissions on Kraken.com (need Query Funds, Orders, etc.)")
        print("   • Deployment logs for connection errors")
        print("   • Run: python3 test_kraken_connection_live.py")
        print()
    
    print("=" * 80)
    print()
    print("📚 NEXT STEPS:")
    print()
    if not master_configured or not users_configured:
        print("   1. Read: KRAKEN_NOT_CONNECTED_SOLUTION.md")
        print("   2. Get API keys from Kraken.com")
        print("   3. Add to Railway/Render environment variables")
        print("   4. Restart deployment")
        print("   5. Re-run this diagnostic to verify")
    else:
        print("   1. Start/restart the bot")
        print("   2. Check logs for:")
        print("      ✅ Kraken Master credentials detected")
        print("      ✅ Kraken MASTER connected")
        print("      ✅ User broker added: daivon_frazier -> Kraken")
        print("      ✅ User broker added: tania_gilbert -> Kraken")
        print("   3. If you see connection errors, run:")
        print("      python3 test_kraken_connection_live.py")
    print()
    print("=" * 80)

if __name__ == "__main__":
    main()
