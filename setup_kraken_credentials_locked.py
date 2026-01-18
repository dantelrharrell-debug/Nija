#!/usr/bin/env python3
"""
Kraken Credentials Setup and Verification Script
================================================

This script ensures Kraken API credentials are properly configured
and persisted in the environment for Railway/Render deployments.

Created: January 18, 2026
Purpose: Lock in Kraken credentials to prevent recurring setup issues
"""

import os
import sys
from pathlib import Path

def ensure_env_file():
    """Ensure .env file exists with Kraken credentials."""
    env_path = Path(__file__).parent / ".env"
    
    # Expected credentials
    expected_vars = {
        "KRAKEN_MASTER_API_KEY": "HXtf6Bgj9kYsTxwYkY6meCeAABnVD8k2Ivsq/Ulc1dYljm8LK7d4OHmz",
        "KRAKEN_MASTER_API_SECRET": "DuYJAPy+7TLIoOSYHhmK4sBQz2fZz8PJyFH6x/OqLpc6bOiwXHvTC5UW0stAFoejMDDI/Ek0uoVcGxTCIuau8g==",
        "KRAKEN_USER_DAIVON_API_KEY": "HSo/f1zjeQALCM/rri9bjTB5JisQ/SPgurCRTx8W7kLD7psjcv2PXEf+",
        "KRAKEN_USER_DAIVON_API_SECRET": "6WOxnBLq+r4ln2Zz7nT0Nvv8CMkaolHtjYdOgTm7NWIq/mJqV8KbDA2XaThP65bHK9QvpEabRr1u38FrBJntaQ==",
        "KRAKEN_USER_TANIA_API_KEY": "XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/",
        "KRAKEN_USER_TANIA_API_SECRET": "iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==",
    }
    
    # Check if .env exists and has correct values
    if env_path.exists():
        with open(env_path, 'r') as f:
            content = f.read()
        
        missing = []
        for var, value in expected_vars.items():
            if f"{var}={value}" not in content:
                missing.append(var)
        
        if missing:
            print(f"⚠️  .env file exists but missing or has incorrect values for: {', '.join(missing)}")
            return False
        else:
            print("✅ .env file exists and all Kraken credentials are correct")
            return True
    else:
        print("❌ .env file does not exist")
        return False


def verify_environment():
    """Verify credentials are loaded in environment."""
    print("\n" + "="*70)
    print("🔍 Verifying Kraken Credentials in Environment")
    print("="*70 + "\n")
    
    # Load from .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ Loaded .env file with python-dotenv\n")
    except ImportError:
        print("⚠️  python-dotenv not installed, checking system environment\n")
    
    credentials = [
        ("KRAKEN_MASTER_API_KEY", "Master Account"),
        ("KRAKEN_MASTER_API_SECRET", "Master Account"),
        ("KRAKEN_USER_DAIVON_API_KEY", "Daivon Frazier"),
        ("KRAKEN_USER_DAIVON_API_SECRET", "Daivon Frazier"),
        ("KRAKEN_USER_TANIA_API_KEY", "Tania Gilbert"),
        ("KRAKEN_USER_TANIA_API_SECRET", "Tania Gilbert"),
    ]
    
    all_present = True
    for var_name, account in credentials:
        value = os.getenv(var_name, "")
        if value:
            obscured = value[:8] + "..." + value[-8:] if len(value) > 16 else "***"
            print(f"✅ {var_name}: {obscured} ({account})")
        else:
            print(f"❌ {var_name}: NOT SET ({account})")
            all_present = False
    
    print("")
    if all_present:
        print("✅ All Kraken credentials are configured!")
        return True
    else:
        print("❌ Some Kraken credentials are missing!")
        return False


def print_deployment_instructions():
    """Print instructions for deployment platforms."""
    print("\n" + "="*70)
    print("📋 Deployment Platform Setup Instructions")
    print("="*70 + "\n")
    
    print("For Railway/Render deployments, set these environment variables:\n")
    
    credentials = [
        ("KRAKEN_MASTER_API_KEY", "HXtf6Bgj9kYsTxwYkY6meCeAABnVD8k2Ivsq/Ulc1dYljm8LK7d4OHmz"),
        ("KRAKEN_MASTER_API_SECRET", "DuYJAPy+7TLIoOSYHhmK4sBQz2fZz8PJyFH6x/OqLpc6bOiwXHvTC5UW0stAFoejMDDI/Ek0uoVcGxTCIuau8g=="),
        ("KRAKEN_USER_DAIVON_API_KEY", "HSo/f1zjeQALCM/rri9bjTB5JisQ/SPgurCRTx8W7kLD7psjcv2PXEf+"),
        ("KRAKEN_USER_DAIVON_API_SECRET", "6WOxnBLq+r4ln2Zz7nT0Nvv8CMkaolHtjYdOgTm7NWIq/mJqV8KbDA2XaThP65bHK9QvpEabRr1u38FrBJntaQ=="),
        ("KRAKEN_USER_TANIA_API_KEY", "XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/"),
        ("KRAKEN_USER_TANIA_API_SECRET", "iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw=="),
    ]
    
    for var_name, value in credentials:
        print(f"{var_name}={value}")
    
    print("\n⚠️  SECURITY NOTE:")
    print("   - Never commit these values to git")
    print("   - Only set in deployment platform environment variables")
    print("   - Local .env file is already in .gitignore")


def main():
    """Main setup and verification."""
    print("="*70)
    print("🔧 NIJA Kraken Credentials Setup")
    print("="*70 + "\n")
    
    # Check .env file
    env_ok = ensure_env_file()
    
    # Verify environment
    env_vars_ok = verify_environment()
    
    # Print deployment instructions if needed
    if not env_vars_ok:
        print_deployment_instructions()
    
    print("\n" + "="*70)
    if env_ok and env_vars_ok:
        print("✅ Setup Complete - Kraken credentials are locked in!")
        print("="*70)
        print("\n📊 Next Steps:")
        print("   1. Ensure .env file is never committed (already in .gitignore)")
        print("   2. Set environment variables in Railway/Render for deployment")
        print("   3. Restart deployment to activate Kraken trading")
        print("   4. Run: python3 kraken_trades_diagnostic.py to verify\n")
        return 0
    else:
        print("⚠️  Setup Incomplete - See instructions above")
        print("="*70 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
