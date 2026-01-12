#!/usr/bin/env python3
"""
NIJA Environment Setup Helper
==============================

This script helps you create a `.env` file with the required configuration
for running NIJA locally or deploying to production.

Usage:
    python3 setup_env.py
    ./setup_env.py

The script will:
1. Check if .env already exists
2. Copy .env.example to .env if needed
3. Guide you through setting up Kraken credentials
4. Validate the configuration
"""

import os
import sys
import shutil


def print_header(title, width=80):
    """Print a formatted header"""
    print()
    print("=" * width)
    print(title.center(width))
    print("=" * width)
    print()


def print_section(title):
    """Print a formatted section header"""
    print()
    print(title)
    print("-" * len(title))


def main():
    """Main setup function"""
    
    print_header("NIJA ENVIRONMENT SETUP")
    
    # Check if .env already exists
    env_file = ".env"
    env_example = ".env.example"
    
    if not os.path.exists(env_example):
        print("❌ Error: .env.example file not found!")
        print("   Make sure you're running this script from the repository root.")
        return 1
    
    if os.path.exists(env_file):
        print(f"⚠️  Warning: {env_file} already exists!")
        response = input("   Do you want to overwrite it? (y/N): ").strip().lower()
        if response not in ['y', 'yes']:
            print("   Aborted. Your existing .env file was not modified.")
            return 0
        print("   Creating backup...")
        shutil.copy(env_file, f"{env_file}.backup")
        print(f"   ✅ Backup created: {env_file}.backup")
    
    # Copy .env.example to .env
    print(f"\n📋 Creating {env_file} from {env_example}...")
    shutil.copy(env_example, env_file)
    print(f"✅ Created {env_file}")
    
    print_section("📖 NEXT STEPS")
    
    print("""
To complete the setup, you need to configure your API credentials:

1. **Coinbase (Required for basic trading)**
   - Get credentials from: https://www.coinbase.com/
   - Set in .env: COINBASE_ORG_ID, COINBASE_JWT_PEM, COINBASE_JWT_KID, COINBASE_JWT_ISSUER

2. **Kraken Master Account (Optional - for Kraken trading)**
   - Get credentials from: https://www.kraken.com/u/security/api
   - Set in .env: KRAKEN_MASTER_API_KEY, KRAKEN_MASTER_API_SECRET

3. **Kraken User Accounts (Optional - for multi-user trading)**
   
   For User #1 (Daivon Frazier):
   - Get credentials from: https://www.kraken.com/u/security/api
   - Set in .env: KRAKEN_USER_DAIVON_API_KEY, KRAKEN_USER_DAIVON_API_SECRET
   
   For User #2 (Tania Gilbert):
   - Get credentials from: https://www.kraken.com/u/security/api
   - Set in .env: KRAKEN_USER_TANIA_API_KEY, KRAKEN_USER_TANIA_API_SECRET

4. **Open .env in your editor and fill in the values:**
   ```
   nano .env
   # or
   vim .env
   # or
   code .env  # VS Code
   ```

5. **Verify your configuration:**
   ```
   python3 kraken_deployment_verify.py
   ```

6. **Security Reminders:**
   ⚠️  Never commit .env file to git (it's already in .gitignore)
   ⚠️  Never share your API keys publicly
   ⚠️  Enable 2FA on all exchange accounts
   ⚠️  Use API key restrictions (IP whitelisting, permissions)
""")
    
    print_header("✅ SETUP COMPLETE")
    
    print("Your .env file is ready for configuration!")
    print(f"Edit {env_file} to add your API credentials.")
    print()
    print("📖 For detailed instructions, see:")
    print("   - KRAKEN_ENV_VARS_REFERENCE.md")
    print("   - MULTI_USER_SETUP_GUIDE.md")
    print("   - README.md")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
