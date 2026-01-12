#!/usr/bin/env python3
"""
Verify Kraken Trading Configuration

This script verifies that Kraken trading is enabled in the NIJA bot configuration.
It checks both the code configuration and environment variables.
"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def print_header(text):
    """Print a formatted header"""
    print()
    print("=" * 80)
    print(f"  {text}")
    print("=" * 80)
    print()

def print_section(text):
    """Print a section divider"""
    print()
    print("-" * 80)
    print(f"  {text}")
    print("-" * 80)

def check_code_configuration():
    """Check if Kraken is configured in the code"""
    print_section("STEP 1: Checking Code Configuration")
    
    try:
        from broker_manager import BrokerType
        
        # Check if Kraken broker type exists
        has_kraken = hasattr(BrokerType, 'KRAKEN')
        
        if has_kraken:
            print(f"  ✅ BrokerType.KRAKEN is defined")
            print(f"     Enum: {BrokerType.KRAKEN}")
            print(f"     Value: '{BrokerType.KRAKEN.value}'")
            return True
        else:
            print(f"  ❌ BrokerType.KRAKEN is NOT defined")
            return False
            
    except ImportError as e:
        print(f"  ❌ Cannot import broker_manager: {e}")
        return False

def check_environment_variables():
    """Check if Kraken credentials are configured"""
    print_section("STEP 2: Checking Environment Variables")
    
    env_vars = [
        ('KRAKEN_MASTER_API_KEY', 'Master account API key'),
        ('KRAKEN_MASTER_API_SECRET', 'Master account API secret'),
        ('KRAKEN_USER_DAIVON_API_KEY', 'User #1 (Daivon Frazier) API key'),
        ('KRAKEN_USER_DAIVON_API_SECRET', 'User #1 (Daivon Frazier) API secret'),
        ('KRAKEN_USER_TANIA_API_KEY', 'User #2 (Tania Gilbert) API key'),
        ('KRAKEN_USER_TANIA_API_SECRET', 'User #2 (Tania Gilbert) API secret'),
    ]
    
    configured_count = 0
    total_count = len(env_vars)
    
    for var_name, description in env_vars:
        value = os.getenv(var_name, '').strip()
        if value:
            # Hide the actual value for security
            masked_value = value[:4] + '...' + value[-4:] if len(value) > 8 else '***'
            print(f"  ✅ {var_name:<35} SET ({masked_value})")
            configured_count += 1
        else:
            print(f"  ⏸️  {var_name:<35} NOT SET")
    
    print()
    print(f"  Configured: {configured_count}/{total_count} environment variables")
    
    return configured_count, total_count

def check_code_usage():
    """Check if trading_strategy.py is configured to use Kraken"""
    print_section("STEP 3: Checking Trading Strategy Configuration")
    
    strategy_file = os.path.join(os.path.dirname(__file__), 'bot', 'trading_strategy.py')
    
    try:
        with open(strategy_file, 'r') as f:
            content = f.read()
        
        # Check for Kraken usage in the code
        checks = [
            ('user1_broker_type = BrokerType.KRAKEN', 'User #1 configured for Kraken'),
            ('user2_broker_type = BrokerType.KRAKEN', 'User #2 configured for Kraken'),
            ('KrakenBroker(account_type=AccountType.MASTER)', 'Master account Kraken initialization'),
        ]
        
        results = []
        for check_string, description in checks:
            if check_string in content:
                print(f"  ✅ {description}")
                results.append(True)
            else:
                print(f"  ❌ {description} - NOT FOUND")
                results.append(False)
        
        return all(results)
        
    except FileNotFoundError:
        print(f"  ❌ Cannot find trading_strategy.py at {strategy_file}")
        return False
    except Exception as e:
        print(f"  ❌ Error reading trading_strategy.py: {e}")
        return False

def main():
    """Main verification function"""
    print_header("KRAKEN TRADING CONFIGURATION VERIFICATION")
    
    # Step 1: Check code configuration
    code_configured = check_code_configuration()
    
    # Step 2: Check environment variables
    env_count, total_env = check_environment_variables()
    env_configured = (env_count == total_env)
    
    # Step 3: Check code usage
    code_usage_ok = check_code_usage()
    
    # Summary
    print_section("VERIFICATION SUMMARY")
    
    print()
    print("  Configuration Status:")
    print()
    
    if code_configured:
        print("  ✅ BrokerType.KRAKEN exists in code")
    else:
        print("  ❌ BrokerType.KRAKEN missing from code")
    
    if code_usage_ok:
        print("  ✅ Kraken is configured for all users in trading_strategy.py")
    else:
        print("  ❌ Kraken is NOT properly configured in trading_strategy.py")
    
    if env_configured:
        print("  ✅ All Kraken API credentials are set")
    else:
        print(f"  ⏸️  Kraken API credentials incomplete ({env_count}/{total_env} set)")
    
    print()
    print("  Account Status:")
    print()
    
    if code_configured and code_usage_ok:
        if env_configured:
            print("  ✅ Master account: ENABLED with credentials")
            print("  ✅ User #1 (Daivon): ENABLED with credentials")
            print("  ✅ User #2 (Tania): ENABLED with credentials")
            print()
            print("  🎉 RESULT: Kraken trading is FULLY ENABLED and ready to trade!")
        else:
            print("  ⚙️  Master account: ENABLED in code (credentials needed)")
            print("  ⚙️  User #1 (Daivon): ENABLED in code (credentials needed)")
            print("  ⚙️  User #2 (Tania): ENABLED in code (credentials needed)")
            print()
            print("  ✅ RESULT: Kraken trading is ENABLED in code")
            print("  📝 Next step: Add Kraken API credentials")
            print()
            print("  See KRAKEN_SETUP_GUIDE.md for detailed setup instructions:")
            print("    1. Create API keys at https://www.kraken.com/u/security/api")
            print("    2. Set environment variables (KRAKEN_MASTER_API_KEY, etc.)")
            print("    3. Restart the bot")
            print()
    else:
        print("  ❌ RESULT: Kraken trading is NOT properly enabled")
        print()
        print("  This is unexpected. Please check:")
        print("    - bot/broker_manager.py contains BrokerType.KRAKEN")
        print("    - bot/trading_strategy.py uses BrokerType.KRAKEN for users")
        print()
    
    print_header("Verification Complete")
    
    # Exit code
    if code_configured and code_usage_ok:
        if env_configured:
            sys.exit(0)  # Fully enabled
        else:
            sys.exit(1)  # Code ready, credentials needed
    else:
        sys.exit(2)  # Configuration issue

if __name__ == "__main__":
    main()
