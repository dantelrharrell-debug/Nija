#!/usr/bin/env python3
"""
Verify User#1 and User#2 Are Ready for Trading

This script verifies that user#1 (Daivon Frazier) and user#2 (Tania Gilbert)
are properly configured and ready to start trading once credentials are provided.

Checks:
1. Users exist in configuration files
2. Users are enabled in configuration
3. Configuration file structure is correct
4. Environment variable requirements are documented

Usage:
    python3 verify_users_ready.py
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Add config directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'config'))


def print_banner():
    """Print verification banner"""
    print()
    print("=" * 80)
    print("VERIFY USER#1 AND USER#2 TRADING READINESS".center(80))
    print("=" * 80)
    print()
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()


def verify_user_configuration():
    """Verify user configuration files"""
    print("=" * 80)
    print("STEP 1: VERIFY USER CONFIGURATION FILES")
    print("=" * 80)
    print()
    
    config_file = Path('config/users/retail_kraken.json')
    
    if not config_file.exists():
        print(f"❌ Configuration file not found: {config_file}")
        return False
    
    print(f"✅ Configuration file exists: {config_file}")
    print()
    
    # Load and verify content
    try:
        with open(config_file, 'r') as f:
            users = json.load(f)
        
        if not isinstance(users, list):
            print("❌ Configuration file should contain a JSON array")
            return False
        
        print(f"✅ Configuration file is valid JSON")
        print(f"   Users configured: {len(users)}")
        print()
        
        # Find user#1 and user#2
        user1 = None
        user2 = None
        
        for user in users:
            if user.get('user_id') == 'daivon_frazier':
                user1 = user
            elif user.get('user_id') == 'tania_gilbert':
                user2 = user
        
        if not user1:
            print("❌ User #1 (daivon_frazier) not found in configuration")
            return False
        
        if not user2:
            print("❌ User #2 (tania_gilbert) not found in configuration")
            return False
        
        print("✅ User #1 (Daivon Frazier) found in configuration")
        print(f"   - user_id: {user1.get('user_id')}")
        print(f"   - name: {user1.get('name')}")
        print(f"   - account_type: {user1.get('account_type')}")
        print(f"   - broker_type: {user1.get('broker_type')}")
        print(f"   - enabled: {user1.get('enabled')}")
        print()
        
        print("✅ User #2 (Tania Gilbert) found in configuration")
        print(f"   - user_id: {user2.get('user_id')}")
        print(f"   - name: {user2.get('name')}")
        print(f"   - account_type: {user2.get('account_type')}")
        print(f"   - broker_type: {user2.get('broker_type')}")
        print(f"   - enabled: {user2.get('enabled')}")
        print()
        
        # Check if enabled
        if not user1.get('enabled'):
            print("⚠️  WARNING: User #1 is DISABLED in configuration")
            print("   To enable: Set 'enabled': true in config file")
            return False
        
        if not user2.get('enabled'):
            print("⚠️  WARNING: User #2 is DISABLED in configuration")
            print("   To enable: Set 'enabled': true in config file")
            return False
        
        print("✅ Both users are ENABLED in configuration")
        print()
        
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in configuration file: {e}")
        return False
    except Exception as e:
        print(f"❌ Error reading configuration file: {e}")
        return False


def verify_credential_requirements():
    """Verify credential requirements are documented"""
    print("=" * 80)
    print("STEP 2: CREDENTIAL REQUIREMENTS")
    print("=" * 80)
    print()
    
    print("To connect and start trading, the following environment variables are required:")
    print()
    
    print("User #1 (Daivon Frazier) - Kraken:")
    print("  KRAKEN_USER_DAIVON_API_KEY=<your_api_key>")
    print("  KRAKEN_USER_DAIVON_API_SECRET=<your_api_secret>")
    print()
    
    print("User #2 (Tania Gilbert) - Kraken:")
    print("  KRAKEN_USER_TANIA_API_KEY=<your_api_key>")
    print("  KRAKEN_USER_TANIA_API_SECRET=<your_api_secret>")
    print()
    
    # Check if credentials are set
    user1_key = os.getenv('KRAKEN_USER_DAIVON_API_KEY', '').strip()
    user1_secret = os.getenv('KRAKEN_USER_DAIVON_API_SECRET', '').strip()
    user2_key = os.getenv('KRAKEN_USER_TANIA_API_KEY', '').strip()
    user2_secret = os.getenv('KRAKEN_USER_TANIA_API_SECRET', '').strip()
    
    user1_configured = bool(user1_key and user1_secret)
    user2_configured = bool(user2_key and user2_secret)
    
    print("Current Status:")
    if user1_configured:
        print(f"  ✅ User #1 credentials: CONFIGURED")
    else:
        print(f"  ❌ User #1 credentials: NOT SET")
    
    if user2_configured:
        print(f"  ✅ User #2 credentials: CONFIGURED")
    else:
        print(f"  ❌ User #2 credentials: NOT SET")
    
    print()
    
    if not (user1_configured and user2_configured):
        print("To add credentials:")
        print("  1. Create/edit your .env file in the project root")
        print("  2. Add the environment variables listed above")
        print("  3. Get your API keys from: https://www.kraken.com/u/security/api")
        print("  4. Restart the bot after adding credentials")
        print()
    
    return user1_configured and user2_configured


def verify_system_readiness():
    """Verify system is ready to start users"""
    print("=" * 80)
    print("STEP 3: SYSTEM READINESS")
    print("=" * 80)
    print()
    
    # Check if user_loader module exists
    try:
        from user_loader import UserConfigLoader
        print("✅ User configuration loader module available")
        
        # Try loading users
        loader = UserConfigLoader()
        loaded = loader.load_all_users()
        
        if loaded:
            print(f"✅ Successfully loaded {len(loader.all_users)} user(s)")
            
            # Find our target users
            user1 = loader.get_user_by_id('daivon_frazier')
            user2 = loader.get_user_by_id('tania_gilbert')
            
            if user1 and user1.enabled:
                print(f"✅ User #1 ({user1.name}) ready in system")
            else:
                print(f"❌ User #1 not ready in system")
            
            if user2 and user2.enabled:
                print(f"✅ User #2 ({user2.name}) ready in system")
            else:
                print(f"❌ User #2 not ready in system")
            
            print()
            return bool(user1 and user2 and user1.enabled and user2.enabled)
        else:
            print("❌ No users loaded from configuration")
            return False
            
    except ImportError:
        print("❌ User configuration loader module not found")
        print("   Module: config/user_loader.py")
        return False
    except Exception as e:
        print(f"❌ Error loading user configuration: {e}")
        return False


def main():
    """Main verification"""
    print_banner()
    
    results = {
        'configuration': False,
        'credentials': False,
        'system': False
    }
    
    # Step 1: Verify configuration
    results['configuration'] = verify_user_configuration()
    
    # Step 2: Verify credentials
    results['credentials'] = verify_credential_requirements()
    
    # Step 3: Verify system
    results['system'] = verify_system_readiness()
    
    # Print final summary
    print("=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    print()
    
    print("Configuration Status:")
    print(f"  {'✅' if results['configuration'] else '❌'} User configuration files")
    print(f"  {'✅' if results['credentials'] else '❌'} API credentials")
    print(f"  {'✅' if results['system'] else '❌'} System readiness")
    print()
    
    all_ready = all(results.values())
    
    if all_ready:
        print("🎉 SUCCESS: Users are READY for trading!")
        print()
        print("Both User #1 and User #2 are:")
        print("  ✅ Configured in config/users/retail_kraken.json")
        print("  ✅ Enabled for trading")
        print("  ✅ Have valid API credentials")
        print("  ✅ Ready to connect and start trading")
        print()
        print("To start trading:")
        print("  python3 connect_and_enable_users.py")
        print()
        return 0
    elif results['configuration'] and results['system']:
        print("⚙️  CONFIGURATION READY - Credentials Required")
        print()
        print("Users are properly configured but need API credentials:")
        print("  ✅ User #1 (Daivon Frazier) - configured, enabled")
        print("  ✅ User #2 (Tania Gilbert) - configured, enabled")
        print("  ❌ API credentials not set")
        print()
        print("Once you add the API credentials to your .env file:")
        print("  python3 connect_and_enable_users.py")
        print()
        return 0
    else:
        print("❌ ISSUES DETECTED")
        print()
        print("Please review the errors above and:")
        print("  1. Fix configuration issues")
        print("  2. Add required API credentials")
        print("  3. Run this verification again")
        print()
        return 1


if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print()
        print("❌ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
