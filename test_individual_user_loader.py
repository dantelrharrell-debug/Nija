#!/usr/bin/env python3
"""
Test script for individual user config loader with hard fail mode.

This demonstrates:
1. Hard fail when required users are missing
2. Hard fail when API keys are missing
3. Auto-enable when API keys exist
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed, using system environment")


def test_soft_fail_mode():
    """Test soft fail mode (won't fail, just warns)."""
    print()
    print("=" * 70)
    print("🧪 TESTING INDIVIDUAL USER LOADER - SOFT FAIL MODE")
    print("=" * 70)
    print()
    
    try:
        # Import fresh for each test
        from config.individual_user_loader import IndividualUserConfigLoader
        loader = IndividualUserConfigLoader()
        loader.load_all_users(hard_fail=False, require_api_keys=False)
        
        print()
        print("✅ PASSED: Loader completed (soft fail)")
        print(f"   Total users: {len(loader.users)}")
        print(f"   Enabled users: {len(loader.enabled_users)}")
        for user_id, user in loader.users.items():
            status = "✅" if user.enabled else "⚪"
            api_keys = "🔑" if user.has_api_keys() else "❌"
            print(f"   {status} {api_keys} {user.name} ({user.broker})")
        return True
    except Exception as e:
        print()
        print(f"❌ FAILED: {e}")
        return False


def test_hard_fail_mode():
    """Test hard fail mode (will fail if API keys missing)."""
    print()
    print("=" * 70)
    print("🧪 TESTING INDIVIDUAL USER LOADER - HARD FAIL MODE")
    print("=" * 70)
    print()
    
    try:
        # Import fresh for each test
        from config.individual_user_loader import IndividualUserConfigLoader
        loader = IndividualUserConfigLoader()
        loader.load_all_users(hard_fail=True, require_api_keys=True)
        
        print()
        print("✅ PASSED: All users loaded successfully")
        print(f"   Enabled users: {len(loader.enabled_users)}")
        for user in loader.enabled_users:
            print(f"   - {user.name} ({user.broker})")
        return True
    except FileNotFoundError as e:
        print()
        print(f"❌ FAILED (Missing Files): {e}")
        return False
    except ValueError as e:
        print()
        print(f"❌ FAILED (Invalid Config/API Keys): {e}")
        return False
    except Exception as e:
        print()
        print(f"❌ FAILED (Unexpected): {e}")
        return False


def check_environment_variables():
    """Check which user API keys are configured."""
    print()
    print("=" * 70)
    print("🔍 CHECKING ENVIRONMENT VARIABLES")
    print("=" * 70)
    print()
    
    users = ['daivon_frazier', 'tania_gilbert']
    broker = 'kraken'
    
    for user_id in users:
        # Validate and extract firstname (same logic as has_api_keys)
        parts = user_id.split('_')
        if not parts or not parts[0]:
            print(f"User: {user_id}")
            print(f"  ❌ Invalid user_id format")
            print()
            continue
        
        firstname = parts[0].upper()
        api_key_var = f"{broker.upper()}_USER_{firstname}_API_KEY"
        api_secret_var = f"{broker.upper()}_USER_{firstname}_API_SECRET"
        
        api_key = os.getenv(api_key_var, "")
        api_secret = os.getenv(api_secret_var, "")
        
        has_key = bool(api_key.strip())
        has_secret = bool(api_secret.strip())
        
        print(f"User: {user_id}")
        print(f"  {api_key_var}: {'✅ SET' if has_key else '❌ NOT SET'}")
        print(f"  {api_secret_var}: {'✅ SET' if has_secret else '❌ NOT SET'}")
        print()


if __name__ == "__main__":
    print()
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "INDIVIDUAL USER LOADER TEST" + " " * 25 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    # Check environment first
    check_environment_variables()
    
    # Test soft fail mode first (won't crash)
    soft_passed = test_soft_fail_mode()
    
    # Test hard fail mode (may crash if requirements not met)
    hard_passed = test_hard_fail_mode()
    
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Soft fail mode: {'✅ PASSED' if soft_passed else '❌ FAILED'}")
    print(f"Hard fail mode: {'✅ PASSED' if hard_passed else '❌ FAILED'}")
    print("=" * 70)
    print()
    
    # Determine exit code
    exit_code = 0
    
    if not hard_passed:
        print("⚠️  TO FIX HARD FAIL MODE:")
        print("1. Ensure config files exist:")
        print("   - config/users/daivon_frazier.json")
        print("   - config/users/tania_gilbert.json")
        print()
        print("2. Set environment variables:")
        print("   - KRAKEN_USER_DAIVON_API_KEY")
        print("   - KRAKEN_USER_DAIVON_API_SECRET")
        print("   - KRAKEN_USER_TANIA_API_KEY")
        print("   - KRAKEN_USER_TANIA_API_SECRET")
        print()
        print("3. Restart the bot")
        print()
        exit_code = 1
    else:
        print("✅ All tests passed! Users are ready for trading.")
        exit_code = 0
    
    sys.exit(exit_code)
