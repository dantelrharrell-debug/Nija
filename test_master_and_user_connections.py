#!/usr/bin/env python3
"""
Master and User Account Connection Test
=========================================

Comprehensive test script to verify connection status for:
1. Master trading account (NIJA system account)
2. All configured user accounts (Daivon, Tania, etc.)
3. All supported exchanges (Coinbase, Kraken, Alpaca, OKX, Binance)

This script:
- Checks if credentials are configured
- Tests actual API connections
- Verifies account access and permissions
- Reports detailed status for each account/exchange combination

Usage:
    python3 test_master_and_user_connections.py
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Optional

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed (using system env vars)")


def print_banner():
    """Print test banner"""
    print()
    print("=" * 80)
    print("MASTER AND USER ACCOUNT CONNECTION TEST".center(80))
    print("=" * 80)
    print()
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()


def check_exchange_credentials(exchange_name: str, account_type: str, 
                               user_id: Optional[str] = None) -> Dict:
    """
    Check if credentials are configured for an exchange account.
    
    Args:
        exchange_name: Name of exchange (COINBASE, KRAKEN, etc.)
        account_type: MASTER or USER
        user_id: User identifier for user accounts (e.g., 'daivon', 'tania')
    
    Returns:
        dict: {
            'configured': bool,
            'api_key': str (masked),
            'api_secret': str (masked),
            'missing_vars': list
        }
    """
    result = {
        'configured': False,
        'api_key': None,
        'api_secret': None,
        'missing_vars': []
    }
    
    # Determine environment variable names
    if account_type == 'MASTER':
        key_var = f"{exchange_name}_MASTER_API_KEY"
        secret_var = f"{exchange_name}_MASTER_API_SECRET"
        
        # Check legacy format (no _MASTER)
        legacy_key_var = f"{exchange_name}_API_KEY"
        legacy_secret_var = f"{exchange_name}_API_SECRET"
    else:  # USER
        # Normalize user_id: replace spaces/dashes with underscores, uppercase
        normalized_user_id = user_id.replace(' ', '_').replace('-', '_').upper()
        key_var = f"{exchange_name}_USER_{normalized_user_id}_API_KEY"
        secret_var = f"{exchange_name}_USER_{normalized_user_id}_API_SECRET"
        legacy_key_var = None
        legacy_secret_var = None
    
    # Check credentials
    api_key = os.getenv(key_var, "").strip()
    api_secret = os.getenv(secret_var, "").strip()
    
    # Check legacy format for master accounts
    if not api_key and legacy_key_var:
        api_key = os.getenv(legacy_key_var, "").strip()
    if not api_secret and legacy_secret_var:
        api_secret = os.getenv(legacy_secret_var, "").strip()
    
    # Check if configured
    if api_key and api_secret:
        result['configured'] = True
        result['api_key'] = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        result['api_secret'] = "***CONFIGURED***"
    else:
        if not api_key:
            result['missing_vars'].append(key_var)
        if not api_secret:
            result['missing_vars'].append(secret_var)
    
    return result


def test_exchange_connection(exchange_name: str, account_type: str,
                             user_id: Optional[str] = None) -> Dict:
    """
    Test actual connection to exchange API.
    
    Returns:
        dict: {
            'connected': bool,
            'error': str (if failed),
            'account_info': dict (if successful)
        }
    """
    result = {
        'connected': False,
        'error': None,
        'account_info': None
    }
    
    try:
        # Import broker manager
        try:
            from broker_manager import BrokerType, AccountType, MultiBrokerManager
        except ImportError:
            result['error'] = "broker_manager module not found"
            return result
        
        # Map exchange name to BrokerType
        broker_type_map = {
            'COINBASE': BrokerType.COINBASE,
            'KRAKEN': BrokerType.KRAKEN,
            'ALPACA': BrokerType.ALPACA,
            'OKX': BrokerType.OKX,
            'BINANCE': BrokerType.BINANCE
        }
        
        broker_type = broker_type_map.get(exchange_name)
        if not broker_type:
            result['error'] = f"Unknown exchange: {exchange_name}"
            return result
        
        # Initialize broker manager
        manager = MultiBrokerManager()
        
        # Determine account type
        acct_type = AccountType.MASTER if account_type == 'MASTER' else AccountType.USER
        
        # Add broker
        broker = manager.add_broker(
            broker_type=broker_type,
            account_type=acct_type,
            user_id=user_id
        )
        
        if not broker:
            result['error'] = "Failed to initialize broker"
            return result
        
        # Test connection by getting account balance
        balance = broker.get_account_balance()
        
        if balance is not None and 'total_balance' in balance:
            result['connected'] = True
            result['account_info'] = {
                'balance': balance.get('total_balance', 0.0),
                'available': balance.get('available_balance', 0.0),
                'currency': balance.get('currency', 'USD')
            }
        else:
            result['error'] = "Failed to retrieve account balance"
            
    except Exception as e:
        result['error'] = str(e)
    
    return result


def test_master_accounts():
    """Test all master account connections"""
    print("=" * 80)
    print("MASTER ACCOUNT TESTING".center(80))
    print("=" * 80)
    print()
    
    exchanges = ['COINBASE', 'KRAKEN', 'ALPACA', 'OKX', 'BINANCE']
    results = {}
    
    for exchange in exchanges:
        print(f"─" * 80)
        print(f"  {exchange} MASTER ACCOUNT")
        print(f"─" * 80)
        
        # Check credentials
        creds = check_exchange_credentials(exchange, 'MASTER')
        
        print(f"  Credentials:")
        if creds['configured']:
            print(f"    ✅ API Key: {creds['api_key']}")
            print(f"    ✅ API Secret: {creds['api_secret']}")
        else:
            print(f"    ❌ Missing variables:")
            for var in creds['missing_vars']:
                print(f"       - {var}")
        print()
        
        # Test connection if credentials exist
        if creds['configured']:
            print(f"  Connection Test:")
            conn = test_exchange_connection(exchange, 'MASTER')
            
            if conn['connected']:
                print(f"    ✅ Connected successfully")
                print(f"    💰 Balance: ${conn['account_info']['balance']:.2f} {conn['account_info']['currency']}")
                print(f"    💵 Available: ${conn['account_info']['available']:.2f}")
            else:
                print(f"    ❌ Connection failed")
                print(f"    Error: {conn['error']}")
        else:
            print(f"  Connection Test:")
            print(f"    ⏭️  Skipped - credentials not configured")
        
        print()
        
        results[f"{exchange}_MASTER"] = {
            'credentials': creds,
            'connection': test_exchange_connection(exchange, 'MASTER') if creds['configured'] else None
        }
    
    return results


def load_user_configs():
    """Load user configurations from config files"""
    users = []
    
    # Check for user config files
    config_dir = os.path.join(os.path.dirname(__file__), 'config', 'users')
    
    if not os.path.exists(config_dir):
        return users
    
    # Load each config file
    for filename in os.listdir(config_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(config_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    config = json.load(f)
                    
                    # Extract user info
                    if isinstance(config, dict) and 'user_id' in config:
                        users.append({
                            'user_id': config['user_id'],
                            'name': config.get('name', config['user_id']),
                            'broker': config.get('broker', 'UNKNOWN'),
                            'enabled': config.get('enabled', False)
                        })
                    elif isinstance(config, list):
                        users.extend(config)
            except Exception as e:
                print(f"⚠️  Warning: Could not load {filename}: {e}")
    
    return users


def test_user_accounts():
    """Test all user account connections"""
    print("=" * 80)
    print("USER ACCOUNT TESTING".center(80))
    print("=" * 80)
    print()
    
    users = load_user_configs()
    
    if not users:
        print("⚠️  No user configurations found in config/users/")
        print()
        return {}
    
    print(f"Found {len(users)} configured user(s)")
    print()
    
    results = {}
    
    for user in users:
        user_id = user['user_id']
        name = user.get('name', user_id)
        broker = user.get('broker', 'KRAKEN').upper()
        enabled = user.get('enabled', False)
        
        print(f"─" * 80)
        print(f"  USER: {name} ({user_id})")
        print(f"─" * 80)
        print(f"  Broker: {broker}")
        print(f"  Enabled: {'✅ Yes' if enabled else '❌ No'}")
        print()
        
        # Check credentials
        creds = check_exchange_credentials(broker, 'USER', user_id)
        
        print(f"  Credentials:")
        if creds['configured']:
            print(f"    ✅ API Key: {creds['api_key']}")
            print(f"    ✅ API Secret: {creds['api_secret']}")
        else:
            print(f"    ❌ Missing variables:")
            for var in creds['missing_vars']:
                print(f"       - {var}")
        print()
        
        # Test connection if credentials exist and user is enabled
        if creds['configured'] and enabled:
            print(f"  Connection Test:")
            conn = test_exchange_connection(broker, 'USER', user_id)
            
            if conn['connected']:
                print(f"    ✅ Connected successfully")
                print(f"    💰 Balance: ${conn['account_info']['balance']:.2f} {conn['account_info']['currency']}")
                print(f"    💵 Available: ${conn['account_info']['available']:.2f}")
            else:
                print(f"    ❌ Connection failed")
                print(f"    Error: {conn['error']}")
        else:
            print(f"  Connection Test:")
            if not enabled:
                print(f"    ⏭️  Skipped - user disabled")
            else:
                print(f"    ⏭️  Skipped - credentials not configured")
        
        print()
        
        results[f"{broker}_{user_id}"] = {
            'user': user,
            'credentials': creds,
            'connection': test_exchange_connection(broker, 'USER', user_id) if (creds['configured'] and enabled) else None
        }
    
    return results


def print_summary(master_results: Dict, user_results: Dict):
    """Print test summary"""
    print("=" * 80)
    print("TEST SUMMARY".center(80))
    print("=" * 80)
    print()
    
    # Count results
    master_configured = sum(1 for r in master_results.values() if r['credentials']['configured'])
    master_connected = sum(1 for r in master_results.values() if r['connection'] and r['connection']['connected'])
    
    user_configured = sum(1 for r in user_results.values() if r['credentials']['configured'])
    user_connected = sum(1 for r in user_results.values() if r['connection'] and r['connection']['connected'])
    
    total_configured = master_configured + user_configured
    total_connected = master_connected + user_connected
    total_accounts = len(master_results) + len(user_results)
    
    # Print summary
    print(f"  Total Accounts Tested: {total_accounts}")
    print(f"  ├─ Master Accounts: {len(master_results)}")
    print(f"  └─ User Accounts: {len(user_results)}")
    print()
    
    print(f"  Credentials Configured: {total_configured}/{total_accounts}")
    print(f"  ├─ Master: {master_configured}/{len(master_results)}")
    print(f"  └─ Users: {user_configured}/{len(user_results)}")
    print()
    
    print(f"  Connections Successful: {total_connected}/{total_configured}")
    print(f"  ├─ Master: {master_connected}/{master_configured if master_configured > 0 else 'N/A'}")
    print(f"  └─ Users: {user_connected}/{user_configured if user_configured > 0 else 'N/A'}")
    print()
    
    # Overall status
    if total_connected == 0:
        print("❌ OVERALL STATUS: NO ACCOUNTS CONNECTED")
        print()
        print("   Action Required:")
        print("   1. Configure API credentials for at least one exchange")
        print("   2. See .env.example for required environment variables")
        print("   3. Run this test again after configuration")
    elif total_connected < total_configured:
        print("⚠️  OVERALL STATUS: SOME ACCOUNTS CONNECTED")
        print()
        print("   Some accounts have credentials but failed to connect.")
        print("   Check error messages above for details.")
    else:
        print("✅ OVERALL STATUS: ALL CONFIGURED ACCOUNTS CONNECTED")
        print()
        print("   All accounts with credentials connected successfully!")
        print("   Ready for trading operations.")
    
    print()


def main():
    """Main test execution"""
    print_banner()
    
    # Test master accounts
    master_results = test_master_accounts()
    
    # Test user accounts
    user_results = test_user_accounts()
    
    # Print summary
    print_summary(master_results, user_results)
    
    # Save results to file
    results = {
        'timestamp': datetime.now().isoformat(),
        'master_accounts': master_results,
        'user_accounts': user_results
    }
    
    output_file = 'connection_test_results.json'
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"📝 Results saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
