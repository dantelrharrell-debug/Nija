#!/usr/bin/env python3
"""
NIJA Environment Variables Validation Tool
==========================================

Comprehensive validation of all environment variables required for NIJA trading bot.
This script checks:
- Required credentials for all supported exchanges (Coinbase, Kraken, Alpaca, OKX, Binance)
- Master account credentials
- User account credentials (from config/users/*.json files)
- Configuration variables
- Provides actionable guidance for fixing any issues

Usage:
    python3 validate_all_env_vars.py
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def check_env_var(var_name: str, required: bool = False, allow_empty: bool = False) -> Tuple[bool, str, Optional[str]]:
    """
    Check if an environment variable is set and valid.
    
    Args:
        var_name: Name of the environment variable
        required: Whether this variable is required for operation
        allow_empty: Whether empty string is valid (default: False)
    
    Returns:
        Tuple of (is_valid, status_message, value_or_none)
    """
    value = os.getenv(var_name)
    
    if value is None:
        if required:
            return False, f"{Colors.RED}❌ NOT SET (REQUIRED){Colors.RESET}", None
        else:
            return True, f"{Colors.YELLOW}⚪ Not set (optional){Colors.RESET}", None
    
    # Check for whitespace-only values
    if value.strip() == "":
        if allow_empty:
            return True, f"{Colors.YELLOW}⚪ Empty (allowed){Colors.RESET}", value
        else:
            return False, f"{Colors.RED}❌ SET BUT EMPTY{Colors.RESET}", value
    
    # Variable is set and has non-whitespace content
    value_preview = value[:50] + "..." if len(value) > 50 else value
    char_count = len(value)
    return True, f"{Colors.GREEN}✅ Set ({char_count} chars){Colors.RESET}", value


def validate_coinbase_credentials() -> Dict:
    """Validate Coinbase credentials."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}📊 COINBASE ADVANCED TRADE (MASTER ACCOUNT){Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    
    result = {
        'name': 'Coinbase',
        'valid': False,
        'issues': []
    }
    
    # Check API Key
    api_key_valid, api_key_status, api_key_value = check_env_var("COINBASE_API_KEY", required=False)
    print(f"   COINBASE_API_KEY:        {api_key_status}")
    
    # Check API Secret
    api_secret_valid, api_secret_status, api_secret_value = check_env_var("COINBASE_API_SECRET", required=False)
    print(f"   COINBASE_API_SECRET:     {api_secret_status}")
    
    # Optional: Portfolio ID
    portfolio_id_valid, portfolio_id_status, _ = check_env_var("COINBASE_RETAIL_PORTFOLIO_ID", required=False, allow_empty=True)
    print(f"   PORTFOLIO_ID:            {portfolio_id_status}")
    
    # Both must be set AND valid (not just empty/whitespace)
    if api_key_valid and api_secret_valid and api_key_value and api_secret_value:
        result['valid'] = True
        print(f"\n   {Colors.GREEN}✅ Coinbase credentials are configured{Colors.RESET}")
    else:
        result['issues'].append("Missing or invalid Coinbase credentials")
        print(f"\n   {Colors.RED}❌ Coinbase credentials NOT configured{Colors.RESET}")
        print(f"   {Colors.YELLOW}To enable Coinbase trading:{Colors.RESET}")
        print(f"   1. Get credentials from https://portal.cdp.coinbase.com/")
        print(f"   2. Set environment variables:")
        print(f"      COINBASE_API_KEY=organizations/.../apiKeys/...")
        print(f"      COINBASE_API_SECRET='-----BEGIN EC PRIVATE KEY-----...")
    
    return result


def validate_kraken_master_credentials() -> Dict:
    """Validate Kraken MASTER account credentials."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}📊 KRAKEN PRO (MASTER ACCOUNT){Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    
    result = {
        'name': 'Kraken Master',
        'valid': False,
        'issues': []
    }
    
    # Check KRAKEN_MASTER credentials
    api_key_valid, api_key_status, api_key_value = check_env_var("KRAKEN_MASTER_API_KEY", required=False)
    print(f"   KRAKEN_MASTER_API_KEY:    {api_key_status}")
    
    api_secret_valid, api_secret_status, api_secret_value = check_env_var("KRAKEN_MASTER_API_SECRET", required=False)
    print(f"   KRAKEN_MASTER_API_SECRET: {api_secret_status}")
    
    # Check legacy credentials as fallback
    legacy_key_valid, legacy_key_status, _ = check_env_var("KRAKEN_API_KEY", required=False)
    legacy_secret_valid, legacy_secret_status, _ = check_env_var("KRAKEN_API_SECRET", required=False)
    
    if legacy_key_valid or legacy_secret_valid:
        print(f"\n   {Colors.CYAN}Legacy credentials detected:{Colors.RESET}")
        print(f"   KRAKEN_API_KEY:           {legacy_key_status}")
        print(f"   KRAKEN_API_SECRET:        {legacy_secret_status}")
    
    # Either new or legacy credentials are valid (both key AND secret must have values)
    has_new_creds = api_key_valid and api_secret_valid and api_key_value and api_secret_value
    has_legacy_creds = legacy_key_valid and legacy_secret_valid and legacy_key_status != f"{Colors.YELLOW}⚪ Not set (optional){Colors.RESET}"
    
    if has_new_creds or has_legacy_creds:
        result['valid'] = True
        print(f"\n   {Colors.GREEN}✅ Kraken MASTER credentials are configured{Colors.RESET}")
    else:
        result['issues'].append("Missing or invalid Kraken MASTER credentials")
        print(f"\n   {Colors.RED}❌ Kraken MASTER credentials NOT configured{Colors.RESET}")
        print(f"   {Colors.YELLOW}To enable Kraken MASTER trading:{Colors.RESET}")
        print(f"   1. Get credentials from https://www.kraken.com/u/security/api")
        print(f"   2. Ensure API key has these permissions:")
        print(f"      ✅ Query Funds")
        print(f"      ✅ Query Open Orders & Trades")
        print(f"      ✅ Query Closed Orders & Trades")
        print(f"      ✅ Create & Modify Orders")
        print(f"      ✅ Cancel/Close Orders")
        print(f"   3. Set environment variables:")
        print(f"      KRAKEN_MASTER_API_KEY=<your-api-key>")
        print(f"      KRAKEN_MASTER_API_SECRET=<your-api-secret>")
    
    return result


def validate_alpaca_master_credentials() -> Dict:
    """Validate Alpaca MASTER account credentials."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}📊 ALPACA TRADING (MASTER ACCOUNT){Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    
    result = {
        'name': 'Alpaca Master',
        'valid': False,
        'issues': []
    }
    
    # Check credentials
    api_key_valid, api_key_status, _ = check_env_var("ALPACA_API_KEY", required=False)
    print(f"   ALPACA_API_KEY:          {api_key_status}")
    
    api_secret_valid, api_secret_status, _ = check_env_var("ALPACA_API_SECRET", required=False)
    print(f"   ALPACA_API_SECRET:       {api_secret_status}")
    
    paper_valid, paper_status, paper_value = check_env_var("ALPACA_PAPER", required=False, allow_empty=True)
    print(f"   ALPACA_PAPER:            {paper_status}")
    
    if paper_value:
        mode = "PAPER" if paper_value.lower() == "true" else "LIVE"
        print(f"   Trading Mode:            {Colors.CYAN}{mode}{Colors.RESET}")
    
    # Check that both key and secret are actually set with values
    api_key_set = api_key_valid and api_key_status != f"{Colors.YELLOW}⚪ Not set (optional){Colors.RESET}"
    api_secret_set = api_secret_valid and api_secret_status != f"{Colors.YELLOW}⚪ Not set (optional){Colors.RESET}"
    
    if api_key_set and api_secret_set:
        result['valid'] = True
        print(f"\n   {Colors.GREEN}✅ Alpaca MASTER credentials are configured{Colors.RESET}")
    else:
        result['issues'].append("Missing or invalid Alpaca MASTER credentials")
        print(f"\n   {Colors.RED}❌ Alpaca MASTER credentials NOT configured{Colors.RESET}")
        print(f"   {Colors.YELLOW}To enable Alpaca MASTER trading:{Colors.RESET}")
        print(f"   1. Get credentials from https://alpaca.markets/")
        print(f"   2. Set environment variables:")
        print(f"      ALPACA_API_KEY=<your-api-key>")
        print(f"      ALPACA_API_SECRET=<your-api-secret>")
        print(f"      ALPACA_PAPER=true  # or false for live trading")
    
    return result


def validate_user_credentials(config_dir: Path = Path("config/users")) -> Dict:
    """
    Validate user account credentials by loading config files and checking env vars.
    
    Args:
        config_dir: Path to directory containing user config JSON files
    
    Returns:
        Dict with validation results
    """
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}👤 USER ACCOUNTS (FROM CONFIG FILES){Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    
    result = {
        'name': 'User Accounts',
        'valid': True,
        'issues': [],
        'users': []
    }
    
    if not config_dir.exists():
        print(f"   {Colors.YELLOW}⚠️  Config directory not found: {config_dir}{Colors.RESET}")
        return result
    
    # Load all user config files
    user_configs = []
    for json_file in config_dir.glob("*.json"):
        try:
            with open(json_file, 'r') as f:
                users = json.load(f)
                if isinstance(users, list):
                    user_configs.extend(users)
        except Exception as e:
            print(f"   {Colors.YELLOW}⚠️  Error loading {json_file}: {e}{Colors.RESET}")
    
    if not user_configs:
        print(f"   {Colors.YELLOW}⚪ No user accounts configured{Colors.RESET}")
        return result
    
    # Check credentials for each enabled user
    for user_config in user_configs:
        if not user_config.get('enabled', False):
            continue
        
        user_id = user_config.get('user_id', 'unknown')
        user_name = user_config.get('name', 'Unknown')
        broker_type = user_config.get('broker_type', '').lower()
        
        print(f"\n   {Colors.CYAN}User: {user_name} ({user_id}){Colors.RESET}")
        print(f"   Broker: {broker_type.upper()}")
        
        # Extract first name from user_id for env var naming
        # e.g., 'daivon_frazier' -> 'DAIVON'
        first_name = user_id.split('_')[0].upper() if '_' in user_id else user_id.upper()
        
        user_result = {
            'user_id': user_id,
            'user_name': user_name,
            'broker': broker_type,
            'valid': False
        }
        
        if broker_type == 'kraken':
            # Check KRAKEN_USER_{FIRSTNAME}_API_KEY and SECRET
            key_var = f"KRAKEN_USER_{first_name}_API_KEY"
            secret_var = f"KRAKEN_USER_{first_name}_API_SECRET"
            
            key_valid, key_status, key_value = check_env_var(key_var, required=False)
            secret_valid, secret_status, secret_value = check_env_var(secret_var, required=False)
            
            print(f"   {key_var}: {key_status}")
            print(f"   {secret_var}: {secret_status}")
            
            # Both must be set with actual values
            if key_valid and secret_valid and key_value and secret_value:
                user_result['valid'] = True
                print(f"   {Colors.GREEN}✅ Credentials configured{Colors.RESET}")
            else:
                result['valid'] = False
                result['issues'].append(f"Missing credentials for {user_name}")
                print(f"   {Colors.RED}❌ Credentials NOT configured{Colors.RESET}")
                print(f"   {Colors.YELLOW}Set: {key_var}=<api-key>{Colors.RESET}")
                print(f"   {Colors.YELLOW}Set: {secret_var}=<api-secret>{Colors.RESET}")
        
        elif broker_type == 'alpaca':
            # Check ALPACA_USER_{FIRSTNAME}_API_KEY, SECRET, and PAPER
            key_var = f"ALPACA_USER_{first_name}_API_KEY"
            secret_var = f"ALPACA_USER_{first_name}_API_SECRET"
            paper_var = f"ALPACA_USER_{first_name}_PAPER"
            
            key_valid, key_status, key_value = check_env_var(key_var, required=False)
            secret_valid, secret_status, secret_value = check_env_var(secret_var, required=False)
            paper_valid, paper_status, paper_value = check_env_var(paper_var, required=False, allow_empty=True)
            
            print(f"   {key_var}: {key_status}")
            print(f"   {secret_var}: {secret_status}")
            print(f"   {paper_var}: {paper_status}")
            
            if paper_value:
                mode = "PAPER" if paper_value.lower() == "true" else "LIVE"
                print(f"   Trading Mode: {Colors.CYAN}{mode}{Colors.RESET}")
            
            # Both key and secret must be set with actual values
            if key_valid and secret_valid and key_value and secret_value:
                user_result['valid'] = True
                print(f"   {Colors.GREEN}✅ Credentials configured{Colors.RESET}")
            else:
                result['valid'] = False
                result['issues'].append(f"Missing credentials for {user_name}")
                print(f"   {Colors.RED}❌ Credentials NOT configured{Colors.RESET}")
                print(f"   {Colors.YELLOW}Set: {key_var}=<api-key>{Colors.RESET}")
                print(f"   {Colors.YELLOW}Set: {secret_var}=<api-secret>{Colors.RESET}")
                print(f"   {Colors.YELLOW}Set: {paper_var}=true{Colors.RESET}")
        
        result['users'].append(user_result)
    
    return result


def validate_optional_exchanges() -> Dict:
    """Validate optional exchange credentials (OKX, Binance)."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}📊 OPTIONAL EXCHANGES{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    
    result = {
        'name': 'Optional Exchanges',
        'exchanges': []
    }
    
    # OKX
    print(f"\n   {Colors.CYAN}OKX Exchange:{Colors.RESET}")
    okx_key_valid, okx_key_status, okx_key_value = check_env_var("OKX_API_KEY", required=False)
    okx_secret_valid, okx_secret_status, okx_secret_value = check_env_var("OKX_API_SECRET", required=False)
    okx_pass_valid, okx_pass_status, okx_pass_value = check_env_var("OKX_PASSPHRASE", required=False)
    
    print(f"   OKX_API_KEY:       {okx_key_status}")
    print(f"   OKX_API_SECRET:    {okx_secret_status}")
    print(f"   OKX_PASSPHRASE:    {okx_pass_status}")
    
    if okx_key_valid and okx_secret_valid and okx_pass_valid and okx_key_value and okx_secret_value and okx_pass_value:
        print(f"   {Colors.GREEN}✅ OKX configured{Colors.RESET}")
        result['exchanges'].append('OKX')
    else:
        print(f"   {Colors.YELLOW}⚪ OKX not configured (optional){Colors.RESET}")
    
    # Binance
    print(f"\n   {Colors.CYAN}Binance Exchange:{Colors.RESET}")
    binance_key_valid, binance_key_status, binance_key_value = check_env_var("BINANCE_API_KEY", required=False)
    binance_secret_valid, binance_secret_status, binance_secret_value = check_env_var("BINANCE_API_SECRET", required=False)
    
    print(f"   BINANCE_API_KEY:    {binance_key_status}")
    print(f"   BINANCE_API_SECRET: {binance_secret_status}")
    
    if binance_key_valid and binance_secret_valid and binance_key_value and binance_secret_value:
        print(f"   {Colors.GREEN}✅ Binance configured{Colors.RESET}")
        result['exchanges'].append('Binance')
    else:
        print(f"   {Colors.YELLOW}⚪ Binance not configured (optional){Colors.RESET}")
    
    return result


def validate_bot_configuration() -> Dict:
    """Validate bot configuration variables."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}🔧 BOT CONFIGURATION{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    
    result = {
        'name': 'Bot Configuration',
        'valid': True,
        'issues': []
    }
    
    # Check configuration variables
    configs = [
        ("MIN_CASH_TO_BUY", "5.50", "Minimum cash required to place a buy order"),
        ("MINIMUM_TRADING_BALANCE", "25.0", "Minimum account balance for trading"),
        ("MAX_CONCURRENT_POSITIONS", "7", "Maximum number of open positions"),
        ("MULTI_BROKER_INDEPENDENT", "true", "Enable independent multi-broker trading"),
    ]
    
    for var_name, default_val, description in configs:
        valid, status, value = check_env_var(var_name, required=False, allow_empty=True)
        actual_value = value if value is not None else default_val
        print(f"   {var_name:30s} = {actual_value:10s} # {description}")
    
    print(f"\n   {Colors.GREEN}✅ Bot configuration loaded{Colors.RESET}")
    
    return result


def print_summary(results: List[Dict]):
    """Print validation summary."""
    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}📋 VALIDATION SUMMARY{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.RESET}\n")
    
    # Count configured exchanges
    configured_master = []
    issues_found = []
    
    for r in results:
        if r.get('valid', False):
            if 'Master' in r['name'] or r['name'] in ['Coinbase', 'Kraken Master', 'Alpaca Master']:
                configured_master.append(r['name'])
        if r.get('issues'):
            issues_found.extend(r['issues'])
    
    # Print master account status
    print(f"{Colors.BOLD}Master Account Exchanges:{Colors.RESET}")
    if configured_master:
        for exchange in configured_master:
            print(f"   {Colors.GREEN}✅ {exchange}{Colors.RESET}")
    else:
        print(f"   {Colors.RED}❌ No master exchanges configured{Colors.RESET}")
    
    # Print user account status
    user_results = next((r for r in results if r['name'] == 'User Accounts'), None)
    if user_results and user_results.get('users'):
        print(f"\n{Colors.BOLD}User Accounts:{Colors.RESET}")
        for user in user_results['users']:
            status = f"{Colors.GREEN}✅" if user['valid'] else f"{Colors.RED}❌"
            print(f"   {status} {user['user_name']} ({user['broker'].upper()}){Colors.RESET}")
    
    # Print issues
    if issues_found:
        print(f"\n{Colors.BOLD}{Colors.RED}⚠️  Issues Found:{Colors.RESET}")
        for issue in issues_found:
            print(f"   {Colors.RED}• {issue}{Colors.RESET}")
    
    # Trading readiness
    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.RESET}")
    if configured_master:
        print(f"{Colors.BOLD}{Colors.GREEN}✅ NIJA IS READY TO TRADE{Colors.RESET}")
        print(f"   Master account can trade on: {', '.join(configured_master)}")
        
        if issues_found:
            print(f"\n   {Colors.YELLOW}⚠️  Some user accounts have issues (see above){Colors.RESET}")
            print(f"   {Colors.YELLOW}Master account will trade independently{Colors.RESET}")
    else:
        print(f"{Colors.BOLD}{Colors.RED}❌ NIJA CANNOT TRADE - NO MASTER EXCHANGES CONFIGURED{Colors.RESET}")
        print(f"\n   {Colors.YELLOW}Action Required:{Colors.RESET}")
        print(f"   Configure at least one master exchange (Coinbase, Kraken, or Alpaca)")
        print(f"   See the detailed output above for specific instructions")
    
    print(f"{Colors.BOLD}{'=' * 70}{Colors.RESET}\n")


def main():
    """Main validation function."""
    print(f"{Colors.BOLD}{Colors.CYAN}")
    print("=" * 70)
    print("    NIJA TRADING BOT - ENVIRONMENT VALIDATION")
    print("=" * 70)
    print(f"{Colors.RESET}\n")
    
    # Try to load .env file if present
    try:
        from dotenv import load_dotenv
        if os.path.exists('.env'):
            load_dotenv()
            print(f"{Colors.GREEN}✅ Loaded environment variables from .env file{Colors.RESET}\n")
        else:
            print(f"{Colors.YELLOW}⚠️  No .env file found - using system environment variables{Colors.RESET}\n")
    except ImportError:
        print(f"{Colors.YELLOW}⚠️  python-dotenv not installed - using system environment variables{Colors.RESET}\n")
    
    # Run all validations
    results = []
    
    results.append(validate_coinbase_credentials())
    results.append(validate_kraken_master_credentials())
    results.append(validate_alpaca_master_credentials())
    results.append(validate_user_credentials())
    results.append(validate_optional_exchanges())
    results.append(validate_bot_configuration())
    
    # Print summary
    print_summary(results)
    
    # Exit code
    any_master_configured = any(r.get('valid', False) for r in results 
                                if 'Master' in r.get('name', '') or r.get('name') in ['Coinbase', 'Kraken Master', 'Alpaca Master'])
    
    if any_master_configured:
        return 0  # Success
    else:
        return 1  # Failure - no master exchanges configured


if __name__ == "__main__":
    sys.exit(main())
