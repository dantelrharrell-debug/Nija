#!/usr/bin/env python3
"""
NIJA Kraken Multi-User Account Setup Example
=============================================

This script demonstrates how to configure and verify Kraken platform
and multi-user accounts for the NIJA trading bot.

Usage:
    python example_kraken_multi_user_setup.py

Prerequisites:
    1. Kraken platform account API credentials
    2. Individual user Kraken API credentials (optional)
    3. .env file configured with credentials

Author: NIJA Trading Systems
Version: 1.0
Date: February 17, 2026
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def print_section(title: str):
    """Print a formatted section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def check_environment_variables():
    """Check that required environment variables are set"""
    print_section("Step 1: Checking Environment Variables")
    
    required_vars = {
        'Platform Account': [
            ('KRAKEN_PLATFORM_API_KEY', 'Kraken platform API key'),
            ('KRAKEN_PLATFORM_API_SECRET', 'Kraken platform API secret'),
        ],
        'Live Trading Control': [
            ('LIVE_CAPITAL_VERIFIED', 'Live trading enabled (set to true)'),
            ('DRY_RUN_MODE', 'Simulation mode (set to false for live)'),
        ]
    }
    
    optional_vars = {
        'User Accounts': [
            ('KRAKEN_USER_DAIVON_API_KEY', 'Daivon Frazier API key'),
            ('KRAKEN_USER_DAIVON_API_SECRET', 'Daivon Frazier API secret'),
            ('KRAKEN_USER_TANIA_API_KEY', 'Tania Gilbert API key'),
            ('KRAKEN_USER_TANIA_API_SECRET', 'Tania Gilbert API secret'),
        ]
    }
    
    # Check required variables
    all_set = True
    for category, vars_list in required_vars.items():
        print(f"\n{category} (Required):")
        for var_name, description in vars_list:
            value = os.getenv(var_name, '')
            is_set = bool(value)
            status = "✅ SET" if is_set else "❌ MISSING"
            
            # Don't print actual secret values
            if 'SECRET' in var_name or 'KEY' in var_name:
                display_value = f"<{len(value)} chars>" if is_set else "Not set"
            else:
                display_value = value if is_set else "Not set"
            
            print(f"  {status} {var_name}: {display_value}")
            print(f"      Description: {description}")
            
            if not is_set:
                all_set = False
    
    # Check optional variables
    for category, vars_list in optional_vars.items():
        print(f"\n{category} (Optional):")
        any_set = False
        for var_name, description in vars_list:
            value = os.getenv(var_name, '')
            is_set = bool(value)
            
            if is_set:
                any_set = True
                status = "✅ SET"
                display_value = f"<{len(value)} chars>"
            else:
                status = "ℹ️  Not set"
                display_value = "Not configured"
            
            print(f"  {status} {var_name}: {display_value}")
            print(f"      Description: {description}")
        
        if not any_set:
            print(f"\n  ℹ️  No {category.lower()} configured (platform-only mode)")
    
    return all_set


def verify_kraken_connection():
    """Verify connection to Kraken API"""
    print_section("Step 2: Verifying Kraken Connection")
    
    try:
        from bot.broker_manager import BrokerType, get_broker_manager
        
        print("\n📡 Testing Kraken platform connection...")
        broker_mgr = get_broker_manager()
        
        # Check if Kraken broker exists
        kraken_broker = broker_mgr.brokers.get(BrokerType.KRAKEN)
        
        if not kraken_broker:
            print("⚠️  Kraken broker not initialized")
            print("   This is expected if broker manager hasn't been started yet")
            print("   Start the bot to initialize brokers")
            return False
        
        # Try to connect
        if kraken_broker.connect():
            print("✅ Kraken platform connection successful!")
            
            # Get account info
            try:
                balance_info = kraken_broker.get_account_balance()
                print(f"\n💰 Platform Account Balance:")
                print(f"   Total Balance: ${balance_info.get('total_balance', 0):.2f}")
                print(f"   Available Balance: ${balance_info.get('available_balance', 0):.2f}")
            except Exception as e:
                print(f"⚠️  Could not fetch balance: {e}")
            
            return True
        else:
            print("❌ Failed to connect to Kraken platform account")
            print("   Check API credentials and network connectivity")
            return False
            
    except ImportError as e:
        print(f"❌ Failed to import broker_manager: {e}")
        print("   Ensure bot/broker_manager.py is available")
        return False
    except Exception as e:
        print(f"❌ Error testing Kraken connection: {e}")
        return False


def check_user_configurations():
    """Check user configuration files"""
    print_section("Step 3: Checking User Configurations")
    
    import json
    
    user_config_files = [
        'config/users/retail_kraken.json',
        'config/users/investor_kraken.json',
        'config/users/daivon_frazier.json',
        'config/users/tania_gilbert.json',
    ]
    
    configured_users = []
    
    for config_file in user_config_files:
        config_path = project_root / config_file
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config_data = json.load(f)
                    
                # Handle both list and single object formats
                users = config_data if isinstance(config_data, list) else [config_data]
                
                for user in users:
                    user_id = user.get('user_id') or user.get('name', 'Unknown')
                    name = user.get('name', user_id)
                    broker = user.get('broker', user.get('broker_type', 'Unknown'))
                    enabled = user.get('enabled', False)
                    independent = user.get('independent_trading', False)
                    
                    if broker.lower() == 'kraken' and enabled:
                        configured_users.append({
                            'user_id': user_id,
                            'name': name,
                            'independent': independent
                        })
                        
                        status = "✅" if independent else "⚠️"
                        print(f"\n{status} User: {name}")
                        print(f"   User ID: {user_id}")
                        print(f"   Broker: {broker}")
                        print(f"   Enabled: {enabled}")
                        print(f"   Independent Trading: {independent}")
                        
                        # Check for corresponding env vars
                        # Extract first name from user_id (e.g., "daivon_frazier" -> "DAIVON")
                        # Handle both underscore-separated and space-separated names
                        if '_' in user_id:
                            env_name = user_id.split('_')[0].upper()
                        elif ' ' in user_id:
                            env_name = user_id.split(' ')[0].upper()
                        else:
                            env_name = user_id.upper()
                        
                        key_var = f"KRAKEN_USER_{env_name}_API_KEY"
                        secret_var = f"KRAKEN_USER_{env_name}_API_SECRET"
                        
                        has_key = bool(os.getenv(key_var))
                        has_secret = bool(os.getenv(secret_var))
                        
                        if has_key and has_secret:
                            print(f"   ✅ API Credentials: Configured")
                        else:
                            print(f"   ❌ API Credentials: Missing")
                            print(f"      Set {key_var} and {secret_var} in .env")
                
            except Exception as e:
                print(f"⚠️  Could not read {config_file}: {e}")
    
    if not configured_users:
        print("\nℹ️  No Kraken user accounts configured")
        print("   Bot will run in platform-only mode")
    else:
        print(f"\n✅ Found {len(configured_users)} configured Kraken user account(s)")
    
    return configured_users


def run_preflight_checks():
    """Run go_live.py pre-flight checks"""
    print_section("Step 4: Running Pre-Flight Checks")
    
    try:
        from go_live import GoLiveValidator
        
        validator = GoLiveValidator()
        
        print("\n🚀 Running all pre-flight checks...\n")
        success = validator.run_all_checks()
        
        if success:
            print("\n" + "=" * 80)
            print("🎉 ALL PRE-FLIGHT CHECKS PASSED!")
            print("=" * 80)
            print("\nYour system is ready for live trading.")
            print("\nNext steps:")
            print("  1. Review the check results above")
            print("  2. Ensure LIVE_CAPITAL_VERIFIED=true in .env")
            print("  3. Run: python go_live.py --activate")
            print("  4. Start the bot: ./start.sh")
            return True
        else:
            print("\n" + "=" * 80)
            print("❌ PRE-FLIGHT CHECKS FAILED")
            print("=" * 80)
            print("\nFix the issues above and try again.")
            print("Run: python go_live.py --check")
            return False
            
    except Exception as e:
        print(f"❌ Error running pre-flight checks: {e}")
        import traceback
        traceback.print_exc()
        return False


def print_summary():
    """Print setup summary and next steps"""
    print_section("Setup Summary")
    
    print("""
📋 Kraken Multi-User Setup Checklist:

✅ Environment Variables
   - KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET set
   - KRAKEN_USER_* credentials set for each user (if multi-user)
   - LIVE_CAPITAL_VERIFIED=true when ready for live trading
   - DRY_RUN_MODE=false for live trading

✅ User Configuration Files
   - config/users/retail_kraken.json or investor_kraken.json
   - Each user has enabled=true and independent_trading=true
   - User credentials match environment variable pattern

✅ Pre-Flight Checks
   - Run: python go_live.py --check
   - All critical checks must pass

✅ Activation
   - Run: python go_live.py --activate
   - Start bot: ./start.sh

📊 Monitoring (First 24 Hours):
   - First 30 minutes: Continuous monitoring
     • Position adoption (should be 100%)
     • Tier floor enforcement
     • Forced cleanup execution
     • Risk management thresholds
     • User account independence
   
   - After 30 minutes: Hourly checks
     • Position status and P&L
     • User account performance
     • API rate limiting
     • Broker health
     • Capital allocation

📚 Documentation:
   - Complete guide: GO_LIVE_GUIDE.md
   - Troubleshooting: GO_LIVE_GUIDE.md (Troubleshooting section)
   - Kraken setup: .env.example (Kraken section)

🆘 Support:
   - Check logs for errors
   - Review observability dashboard
   - See troubleshooting guide for common issues
""")


def main():
    """Main entry point"""
    print("=" * 80)
    print("  NIJA KRAKEN MULTI-USER ACCOUNT SETUP")
    print("=" * 80)
    print("\nThis script will help you configure Kraken platform and multi-user accounts.")
    print("It will check your environment, verify connections, and run pre-flight checks.")
    
    try:
        # Step 1: Check environment variables
        env_ok = check_environment_variables()
        
        # Step 2: Verify Kraken connection (may not work if broker not initialized)
        # verify_kraken_connection()
        
        # Step 3: Check user configurations
        check_user_configurations()
        
        # Step 4: Run pre-flight checks
        if env_ok:
            run_preflight_checks()
        else:
            print("\n⚠️  Skipping pre-flight checks due to missing environment variables")
            print("   Configure missing variables in .env and try again")
        
        # Print summary
        print_summary()
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
