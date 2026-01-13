#!/usr/bin/env python3
"""
NIJA Kraken User Connection Verification Script
================================================

This script verifies that Kraken API credentials are properly configured
for the master account and all user accounts.

It checks:
1. Environment variable presence
2. Environment variable validity (not empty/whitespace)
3. User configuration files
4. Credential format validation

This helps diagnose "NOT TRADING (Connection failed or not configured)" issues.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed, relying on system environment variables")


def check_env_var(var_name: str) -> Tuple[bool, str]:
    """
    Check if an environment variable is set and valid.
    
    Returns:
        Tuple of (is_valid, status_message)
    """
    value = os.getenv(var_name, "")
    
    if not value:
        return False, "❌ NOT SET"
    
    # Check if it's just whitespace
    if not value.strip():
        return False, "⚠️  SET but EMPTY (whitespace only)"
    
    # Check if it looks like a real credential (at least 10 chars)
    if len(value.strip()) < 10:
        return False, f"⚠️  TOO SHORT ({len(value.strip())} chars, need 10+)"
    
    return True, f"✅ VALID ({len(value.strip())} chars)"


def load_user_config(config_path: Path) -> List[Dict]:
    """Load user configuration from JSON file."""
    if not config_path.exists():
        return []
    
    try:
        with open(config_path, 'r') as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            return []
        
        return data
    except Exception as e:
        print(f"⚠️  Error loading {config_path}: {e}")
        return []


def main():
    """Main verification function."""
    print("=" * 80)
    print("🔍 NIJA KRAKEN USER CONNECTION VERIFICATION")
    print("=" * 80)
    print()
    
    all_valid = True
    
    # 1. Check Master Account Credentials
    print("1️⃣  MASTER ACCOUNT (NIJA System)")
    print("-" * 80)
    
    master_key_valid, master_key_status = check_env_var("KRAKEN_MASTER_API_KEY")
    master_secret_valid, master_secret_status = check_env_var("KRAKEN_MASTER_API_SECRET")
    
    print(f"   KRAKEN_MASTER_API_KEY:    {master_key_status}")
    print(f"   KRAKEN_MASTER_API_SECRET: {master_secret_status}")
    
    # Check legacy credentials as fallback
    if not (master_key_valid and master_secret_valid):
        print()
        print("   📌 Checking legacy credentials (fallback)...")
        legacy_key_valid, legacy_key_status = check_env_var("KRAKEN_API_KEY")
        legacy_secret_valid, legacy_secret_status = check_env_var("KRAKEN_API_SECRET")
        
        print(f"   KRAKEN_API_KEY:           {legacy_key_status}")
        print(f"   KRAKEN_API_SECRET:        {legacy_secret_status}")
        
        if legacy_key_valid and legacy_secret_valid:
            print("   ✅ Legacy credentials found - will be used for master account")
        else:
            print("   ❌ Neither master nor legacy credentials configured")
            all_valid = False
    else:
        print("   ✅ Master account credentials configured")
    
    print()
    
    # 2. Load and check user configurations
    config_dir = project_root / "config" / "users"
    
    print("2️⃣  USER ACCOUNTS")
    print("-" * 80)
    
    # Load Kraken users
    kraken_users_file = config_dir / "retail_kraken.json"
    kraken_users = load_user_config(kraken_users_file)
    
    if not kraken_users:
        print("   ⚪ No Kraken users configured in config/users/retail_kraken.json")
    else:
        print(f"   Found {len(kraken_users)} user(s) in {kraken_users_file.name}")
        print()
        
        for idx, user in enumerate(kraken_users, 1):
            user_id = user.get('user_id', 'unknown')
            user_name = user.get('name', 'Unknown')
            enabled = user.get('enabled', False)
            
            print(f"   User #{idx}: {user_name} ({user_id})")
            print(f"      Status: {'✅ ENABLED' if enabled else '⚪ DISABLED'}")
            
            if not enabled:
                print("      ⏭️  Skipping credential check (user disabled)")
                print()
                continue
            
            # Determine environment variable names
            # Convert user_id to uppercase, extract first part before underscore
            if '_' in user_id:
                user_env_name = user_id.split('_')[0].upper()
            else:
                user_env_name = user_id.upper()
            
            key_var = f"KRAKEN_USER_{user_env_name}_API_KEY"
            secret_var = f"KRAKEN_USER_{user_env_name}_API_SECRET"
            
            key_valid, key_status = check_env_var(key_var)
            secret_valid, secret_status = check_env_var(secret_var)
            
            print(f"      {key_var}: {key_status}")
            print(f"      {secret_var}: {secret_status}")
            
            if key_valid and secret_valid:
                print(f"      ✅ Credentials configured for {user_name}")
            else:
                print(f"      ❌ MISSING CREDENTIALS - {user_name} will NOT trade")
                all_valid = False
            
            print()
    
    # 3. Summary and recommendations
    print("=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    
    if all_valid:
        print("✅ ALL CHECKS PASSED")
        print()
        print("   All enabled users have valid Kraken credentials configured.")
        print("   The bot should be able to connect and trade on Kraken.")
    else:
        print("❌ ISSUES FOUND")
        print()
        print("   Some credentials are missing or invalid. Users without valid")
        print("   credentials will show as 'NOT TRADING' when the bot starts.")
        print()
        print("🔧 HOW TO FIX:")
        print()
        print("   1. Get API credentials from https://www.kraken.com/u/security/api")
        print("   2. Create API key with these permissions:")
        print("      ✓ Query Funds")
        print("      ✓ Query Open Orders & Trades")
        print("      ✓ Query Closed Orders & Trades")
        print("      ✓ Create & Modify Orders")
        print("      ✓ Cancel/Close Orders")
        print()
        print("   3. Add credentials to your deployment platform:")
        print()
        print("      Railway: Dashboard → Variables → Add Variable")
        print("      Render: Dashboard → Environment → Add Environment Variable")
        print("      Local: Add to .env file in project root")
        print()
        print("   4. Restart the bot after adding credentials")
        print()
        print("📖 See ENVIRONMENT_VARIABLES_GUIDE.md for detailed instructions")
    
    print("=" * 80)
    
    # Exit with appropriate code
    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()
