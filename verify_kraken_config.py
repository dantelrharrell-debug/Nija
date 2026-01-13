#!/usr/bin/env python3
"""
Kraken Configuration Validator for Railway Deployment

This script validates that:
1. Environment variables are properly set for Kraken trading
2. User configuration files are valid JSON and properly structured
3. Environment variable naming matches user_id patterns
4. All required credentials are present for enabled users

Run this script in Railway deployment environment or locally with .env file
to verify Kraken is properly configured before deploying.
"""

import os
import json
import sys
from pathlib import Path

# Color codes for terminal output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_header(text):
    """Print a header with formatting"""
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}{text}{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}")

def print_success(text):
    """Print success message"""
    print(f"{GREEN}✅ {text}{RESET}")

def print_warning(text):
    """Print warning message"""
    print(f"{YELLOW}⚠️  {text}{RESET}")

def print_error(text):
    """Print error message"""
    print(f"{RED}❌ {text}{RESET}")

def print_info(text):
    """Print info message"""
    print(f"{BLUE}ℹ️  {text}{RESET}")

def check_master_credentials():
    """Check if master Kraken credentials are set"""
    print_header("CHECKING MASTER ACCOUNT CREDENTIALS")
    
    # Check new format
    master_key = os.getenv("KRAKEN_MASTER_API_KEY")
    master_secret = os.getenv("KRAKEN_MASTER_API_SECRET")
    
    # Check legacy format
    legacy_key = os.getenv("KRAKEN_API_KEY")
    legacy_secret = os.getenv("KRAKEN_API_SECRET")
    
    has_new_creds = bool(master_key and master_secret)
    has_legacy_creds = bool(legacy_key and legacy_secret)
    
    if has_new_creds:
        print_success("Master credentials found (new format)")
        print(f"   KRAKEN_MASTER_API_KEY: {'*' * min(10, len(master_key))}{master_key[-10:] if len(master_key) > 10 else ''}")
        print(f"   KRAKEN_MASTER_API_SECRET: {'*' * 20}... ({len(master_secret)} chars)")
        return True
    elif has_legacy_creds:
        print_success("Master credentials found (legacy format)")
        print(f"   KRAKEN_API_KEY: {'*' * min(10, len(legacy_key))}{legacy_key[-10:] if len(legacy_key) > 10 else ''}")
        print(f"   KRAKEN_API_SECRET: {'*' * 20}... ({len(legacy_secret)} chars)")
        print_info("Consider migrating to KRAKEN_MASTER_API_KEY format")
        return True
    else:
        print_error("Master credentials NOT found")
        print_info("Set either:")
        print_info("  KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
        print_info("  OR")
        print_info("  KRAKEN_API_KEY and KRAKEN_API_SECRET (legacy)")
        return False

def load_user_config(file_path):
    """Load and validate user configuration file"""
    try:
        with open(file_path, 'r') as f:
            config = json.load(f)
        return config, None
    except FileNotFoundError:
        return None, f"File not found: {file_path}"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in {file_path}: {e}"
    except Exception as e:
        return None, f"Error loading {file_path}: {e}"

def get_env_var_prefix(user_id):
    """Extract the environment variable prefix from user_id"""
    # For user_id like 'daivon_frazier', extract 'DAIVON'
    if '_' in user_id:
        return user_id.split('_')[0].upper()
    return user_id.upper()

def check_user_credentials(user_id, broker_type):
    """Check if user credentials are set"""
    prefix = get_env_var_prefix(user_id)
    
    if broker_type.lower() == 'kraken':
        key_var = f"KRAKEN_USER_{prefix}_API_KEY"
        secret_var = f"KRAKEN_USER_{prefix}_API_SECRET"
    elif broker_type.lower() == 'alpaca':
        key_var = f"ALPACA_USER_{prefix}_API_KEY"
        secret_var = f"ALPACA_USER_{prefix}_API_SECRET"
    else:
        return False, f"Unsupported broker type: {broker_type}"
    
    key_value = os.getenv(key_var)
    secret_value = os.getenv(secret_var)
    
    if key_value and secret_value:
        return True, (key_var, secret_var, key_value, secret_value)
    elif key_value or secret_value:
        missing = secret_var if key_value else key_var
        return False, f"Incomplete credentials: {missing} is missing"
    else:
        return False, f"Credentials not found: {key_var} and {secret_var}"

def check_kraken_users():
    """Check Kraken user configurations and credentials"""
    print_header("CHECKING KRAKEN USER ACCOUNTS")
    
    # Check for user config files
    config_dir = Path(__file__).parent / "config" / "users"
    retail_kraken = config_dir / "retail_kraken.json"
    investor_kraken = config_dir / "investor_kraken.json"
    
    all_users = []
    issues = []
    
    # Load retail users
    if retail_kraken.exists():
        config, error = load_user_config(retail_kraken)
        if error:
            print_error(f"Retail Kraken config: {error}")
            issues.append(error)
        else:
            print_success(f"Loaded retail_kraken.json: {len(config)} user(s)")
            all_users.extend(config)
    else:
        print_warning(f"retail_kraken.json not found at {retail_kraken}")
    
    # Load investor users
    if investor_kraken.exists():
        config, error = load_user_config(investor_kraken)
        if error:
            print_error(f"Investor Kraken config: {error}")
            issues.append(error)
        else:
            if len(config) > 0:
                print_success(f"Loaded investor_kraken.json: {len(config)} user(s)")
                all_users.extend(config)
            else:
                print_info(f"investor_kraken.json is empty (no investors configured)")
    else:
        print_warning(f"investor_kraken.json not found at {investor_kraken}")
    
    if not all_users:
        print_warning("No Kraken users configured")
        return True  # Not an error, just no users
    
    # Check each user's credentials
    print(f"\n{BLUE}Checking credentials for {len(all_users)} user(s)...{RESET}")
    
    enabled_count = 0
    disabled_count = 0
    missing_creds_count = 0
    
    for user in all_users:
        user_id = user.get('user_id')
        name = user.get('name', 'Unknown')
        enabled = user.get('enabled', True)
        broker_type = user.get('broker_type', 'kraken')
        
        if not enabled:
            print_warning(f"User {name} ({user_id}): DISABLED in config")
            disabled_count += 1
            continue
        
        enabled_count += 1
        success, result = check_user_credentials(user_id, broker_type)
        
        if success:
            key_var, secret_var, key_val, secret_val = result
            print_success(f"User {name} ({user_id}): Credentials found")
            print(f"   {key_var}: {'*' * 10}{key_val[-10:] if len(key_val) > 10 else '***'}")
            print(f"   {secret_var}: {'*' * 20}... ({len(secret_val)} chars)")
        else:
            print_error(f"User {name} ({user_id}): {result}")
            missing_creds_count += 1
            issues.append(f"User {user_id}: {result}")
    
    print(f"\n{BLUE}Summary:{RESET}")
    print(f"   Total users in config: {len(all_users)}")
    print(f"   Enabled: {enabled_count}")
    print(f"   Disabled: {disabled_count}")
    print(f"   Missing credentials: {missing_creds_count}")
    
    return missing_creds_count == 0

def check_alpaca_users():
    """Check Alpaca user configurations and credentials"""
    print_header("CHECKING ALPACA USER ACCOUNTS")
    
    config_dir = Path(__file__).parent / "config" / "users"
    retail_alpaca = config_dir / "retail_alpaca.json"
    
    if not retail_alpaca.exists():
        print_info("retail_alpaca.json not found (Alpaca users not configured)")
        return True
    
    config, error = load_user_config(retail_alpaca)
    if error:
        print_error(f"Alpaca config: {error}")
        return False
    
    if len(config) == 0:
        print_info("retail_alpaca.json is empty (no Alpaca users configured)")
        return True
    
    print_success(f"Loaded retail_alpaca.json: {len(config)} user(s)")
    
    enabled_count = 0
    disabled_count = 0
    missing_creds_count = 0
    
    for user in config:
        user_id = user.get('user_id')
        name = user.get('name', 'Unknown')
        enabled = user.get('enabled', True)
        broker_type = user.get('broker_type', 'alpaca')
        
        if not enabled:
            print_warning(f"User {name} ({user_id}): DISABLED in config")
            disabled_count += 1
            continue
        
        enabled_count += 1
        success, result = check_user_credentials(user_id, broker_type)
        
        if success:
            key_var, secret_var, key_val, secret_val = result
            print_success(f"User {name} ({user_id}): Credentials found")
            print(f"   {key_var}: {'*' * min(10, len(key_val))}{key_val[-10:] if len(key_val) > 10 else ''}")
            print(f"   {secret_var}: {'*' * 20}... ({len(secret_val)} chars)")
            
            # Check paper trading flag
            prefix = get_env_var_prefix(user_id)
            paper_var = f"ALPACA_USER_{prefix}_PAPER"
            paper_value = os.getenv(paper_var, 'true')
            print(f"   {paper_var}: {paper_value}")
        else:
            print_error(f"User {name} ({user_id}): {result}")
            missing_creds_count += 1
    
    print(f"\n{BLUE}Summary:{RESET}")
    print(f"   Total users in config: {len(config)}")
    print(f"   Enabled: {enabled_count}")
    print(f"   Disabled: {disabled_count}")
    print(f"   Missing credentials: {missing_creds_count}")
    
    return missing_creds_count == 0

def check_coinbase_credentials():
    """Check if Coinbase credentials are set (optional)"""
    print_header("CHECKING COINBASE CREDENTIALS (OPTIONAL)")
    
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    if api_key and api_secret:
        print_success("Coinbase credentials found")
        # Mask the key for security
        if api_key.startswith("organizations/"):
            # New format - show org part but mask key ID
            parts = api_key.split('/')
            if len(parts) >= 4:
                masked = f"{parts[0]}/{parts[1]}/apiKeys/***{parts[3][-6:]}"
            else:
                masked = "***" + api_key[-10:]
            print(f"   COINBASE_API_KEY: {masked}")
        else:
            # Old format or unknown - mask it
            print(f"   COINBASE_API_KEY: {'*' * min(10, len(api_key))}{api_key[-10:] if len(api_key) > 10 else ''}")
        print(f"   COINBASE_API_SECRET: {'*' * 20}... ({len(api_secret)} chars)")
        return True
    else:
        print_info("Coinbase credentials not set (optional)")
        return True  # Not required

def check_trading_config():
    """Check trading configuration parameters"""
    print_header("CHECKING TRADING CONFIGURATION")
    
    params = {
        'LIVE_TRADING': os.getenv('LIVE_TRADING', '0'),
        'DEFAULT_TRADE_PERCENT': os.getenv('DEFAULT_TRADE_PERCENT', '0.05'),
        'MAX_CONCURRENT_POSITIONS': os.getenv('MAX_CONCURRENT_POSITIONS', '8'),
        'MIN_CASH_TO_BUY': os.getenv('MIN_CASH_TO_BUY', '5.00'),
        'MINIMUM_TRADING_BALANCE': os.getenv('MINIMUM_TRADING_BALANCE', '25.0'),
        'ALLOW_CONSUMER_USD': os.getenv('ALLOW_CONSUMER_USD', 'False'),
    }
    
    for key, value in params.items():
        print(f"   {key}: {value}")
    
    # Validate LIVE_TRADING
    if params['LIVE_TRADING'] == '1':
        print_warning("LIVE_TRADING is ENABLED - Real money will be used!")
    else:
        print_info("LIVE_TRADING is DISABLED - No actual trading will occur")
    
    return True

def main():
    """Main validation function"""
    print_header("NIJA KRAKEN CONFIGURATION VALIDATOR")
    print(f"{BLUE}Validating Kraken and multi-exchange configuration...{RESET}")
    
    # Try to load .env if available
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print_info("Loaded environment from .env file")
    except ImportError:
        print_info("python-dotenv not available, using system environment variables")
    
    # Run all checks
    checks = [
        ("Master Kraken Credentials", check_master_credentials),
        ("Kraken User Accounts", check_kraken_users),
        ("Alpaca User Accounts", check_alpaca_users),
        ("Coinbase Credentials", check_coinbase_credentials),
        ("Trading Configuration", check_trading_config),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print_error(f"Error during {name} check: {e}")
            results.append((name, False))
    
    # Print final summary
    print_header("VALIDATION SUMMARY")
    
    all_passed = True
    for name, passed in results:
        if passed:
            print_success(f"{name}: PASSED")
        else:
            print_error(f"{name}: FAILED")
            all_passed = False
    
    print()
    if all_passed:
        print_success("All validation checks passed!")
        print_success("NIJA is properly configured for Kraken trading")
        print_info("Deploy to Railway and check logs to verify connections")
        return 0
    else:
        print_error("Some validation checks failed")
        print_error("Fix the issues above before deploying to Railway")
        print_info("See RAILWAY_KRAKEN_SETUP.md for configuration instructions")
        return 1

if __name__ == "__main__":
    sys.exit(main())
