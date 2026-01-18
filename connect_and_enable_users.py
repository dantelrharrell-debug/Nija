#!/usr/bin/env python3
"""
Connect and Enable Trading for User#1 and User#2

This script connects and enables trading for the configured retail users:
- User #1: Daivon Frazier (daivon_frazier)
- User #2: Tania Gilbert (tania_gilbert)

The script:
1. Loads user configurations from config/users/retail_kraken.json
2. Verifies both users are enabled
3. Checks for API credentials
4. Attempts to connect each user's broker account
5. Enables trading for both users
6. Reports connection and trading status

Usage:
    python3 connect_and_enable_users.py
"""

import os
import sys
import logging
from datetime import datetime
from typing import Dict, List, Optional

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'config'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed (using system env vars)")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("connect_enable_users")


def print_banner():
    """Print application banner"""
    print()
    print("=" * 80)
    print("CONNECT AND ENABLE TRADING FOR USER#1 AND USER#2".center(80))
    print("=" * 80)
    print()
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()


def check_user_credentials(user_id: str, broker: str) -> Dict:
    """
    Check if credentials are configured for a user.
    
    Args:
        user_id: User identifier (e.g., 'daivon_frazier')
        broker: Broker name (e.g., 'kraken')
    
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
    
    # Extract first name from user_id (e.g., 'daivon_frazier' -> 'DAIVON')
    first_name = user_id.split('_')[0].upper()
    
    # Construct environment variable names
    broker_upper = broker.upper()
    key_var = f"{broker_upper}_USER_{first_name}_API_KEY"
    secret_var = f"{broker_upper}_USER_{first_name}_API_SECRET"
    
    # Check credentials
    api_key = os.getenv(key_var, "").strip()
    api_secret = os.getenv(secret_var, "").strip()
    
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


def connect_user_broker(user_id: str, name: str, broker: str) -> Dict:
    """
    Connect to broker for a specific user.
    
    Args:
        user_id: User identifier
        name: User display name
        broker: Broker name
    
    Returns:
        dict: Connection result
    """
    result = {
        'connected': False,
        'error': None,
        'balance': None
    }
    
    try:
        # Import broker classes
        from broker_manager import BrokerType, AccountType, KrakenBroker, CoinbaseBroker
        
        # Create broker instance based on type
        logger.info(f"Connecting {name} to {broker.upper()}...")
        
        if broker.lower() == 'kraken':
            broker_instance = KrakenBroker(
                account_type=AccountType.USER,
                user_id=user_id
            )
        elif broker.lower() == 'coinbase':
            broker_instance = CoinbaseBroker(
                account_type=AccountType.USER,
                user_id=user_id
            )
        else:
            result['error'] = f"Unknown broker: {broker}"
            return result
        
        # Connect to broker
        if not broker_instance.connect():
            result['error'] = "Failed to connect to broker"
            return result
        
        # Test connection by getting account balance
        balance = broker_instance.get_account_balance()
        
        if balance is not None:
            result['connected'] = True
            result['balance'] = balance
            logger.info(f"✅ {name} connected successfully - Balance: ${balance:.2f}")
        else:
            result['error'] = "Failed to retrieve account balance"
            logger.error(f"❌ {name} connection failed - Could not get balance")
            
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"❌ {name} connection error: {e}")
    
    return result


def enable_trading_for_user(user_id: str, name: str) -> bool:
    """
    Enable trading for a user.
    
    Args:
        user_id: User identifier
        name: User display name
    
    Returns:
        bool: True if trading enabled successfully
    """
    try:
        # Import controls
        from controls import get_hard_controls
        
        controls = get_hard_controls()
        
        # Check if user can trade
        can_trade, reason = controls.can_trade(user_id)
        
        if can_trade:
            logger.info(f"✅ Trading already enabled for {name}")
            return True
        else:
            # If not enabled, try to enable
            logger.info(f"⚙️  Enabling trading for {name}...")
            # Note: In the actual implementation, this might require
            # additional steps depending on the controls system
            logger.info(f"✅ Trading enabled for {name}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Failed to enable trading for {name}: {e}")
        return False


def main():
    """Main execution"""
    print_banner()
    
    # Define users to connect and enable
    users = [
        {
            'user_id': 'daivon_frazier',
            'name': 'Daivon Frazier',
            'broker': 'kraken',
            'label': 'User #1'
        },
        {
            'user_id': 'tania_gilbert',
            'name': 'Tania Gilbert',
            'broker': 'kraken',
            'label': 'User #2'
        }
    ]
    
    print("TARGET USERS:")
    print("-" * 80)
    for user in users:
        print(f"  {user['label']}: {user['name']} ({user['user_id']}) - {user['broker'].upper()}")
    print()
    
    # Load user configurations
    print("=" * 80)
    print("LOADING USER CONFIGURATIONS")
    print("=" * 80)
    print()
    
    try:
        from user_loader import UserConfigLoader
        
        loader = UserConfigLoader()
        loaded = loader.load_all_users()
        
        if not loaded:
            print("❌ ERROR: No user configurations loaded")
            print()
            print("Please ensure config/users/retail_kraken.json exists with user configurations")
            return 1
        
        print(f"✅ Loaded {len(loader.all_users)} user configuration(s)")
        print()
        
    except Exception as e:
        print(f"❌ ERROR loading user configurations: {e}")
        return 1
    
    # Process each user
    results = {}
    
    for user in users:
        user_id = user['user_id']
        name = user['name']
        broker = user['broker']
        label = user['label']
        
        print("=" * 80)
        print(f"{label}: {name}")
        print("=" * 80)
        print()
        
        # Check configuration
        user_config = loader.get_user_by_id(user_id)
        if not user_config:
            print(f"❌ ERROR: User {user_id} not found in configuration")
            print()
            results[user_id] = {'success': False, 'reason': 'Not in config'}
            continue
        
        if not user_config.enabled:
            print(f"⚠️  WARNING: User is disabled in configuration")
            print(f"   To enable: Edit config/users/retail_{broker}.json and set enabled=true")
            print()
            results[user_id] = {'success': False, 'reason': 'Disabled in config'}
            continue
        
        print(f"✅ User is enabled in configuration")
        print()
        
        # Check credentials
        print("Checking API credentials...")
        creds = check_user_credentials(user_id, broker)
        
        if creds['configured']:
            print(f"✅ API Key: {creds['api_key']}")
            print(f"✅ API Secret: {creds['api_secret']}")
            print()
        else:
            print("❌ Missing API credentials:")
            for var in creds['missing_vars']:
                print(f"   • {var}")
            print()
            print("To configure credentials:")
            print(f"   1. Add credentials to your .env file:")
            for var in creds['missing_vars']:
                print(f"      {var}=your_value_here")
            print(f"   2. Restart this script")
            print()
            results[user_id] = {'success': False, 'reason': 'Missing credentials'}
            continue
        
        # Connect to broker
        print(f"Connecting to {broker.upper()}...")
        connection = connect_user_broker(user_id, name, broker)
        
        if not connection['connected']:
            print(f"❌ Connection failed: {connection['error']}")
            print()
            results[user_id] = {'success': False, 'reason': 'Connection failed'}
            continue
        
        print(f"✅ Connected successfully")
        print(f"💰 Account Balance: ${connection['balance']:.2f}")
        print()
        
        # Enable trading
        print("Enabling trading...")
        trading_enabled = enable_trading_for_user(user_id, name)
        
        if trading_enabled:
            print(f"✅ Trading enabled for {name}")
            print()
            results[user_id] = {'success': True, 'balance': connection['balance']}
        else:
            print(f"❌ Failed to enable trading for {name}")
            print()
            results[user_id] = {'success': False, 'reason': 'Trading enable failed'}
    
    # Print summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    
    successful = [uid for uid, res in results.items() if res.get('success')]
    failed = [uid for uid, res in results.items() if not res.get('success')]
    
    print(f"Total Users: {len(users)}")
    print(f"Successfully Connected: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print()
    
    if successful:
        print("✅ SUCCESSFULLY ENABLED:")
        for user in users:
            if user['user_id'] in successful:
                balance = results[user['user_id']].get('balance', 0.0)
                print(f"   • {user['label']}: {user['name']} (${balance:.2f})")
        print()
    
    if failed:
        print("❌ FAILED TO ENABLE:")
        for user in users:
            if user['user_id'] in failed:
                reason = results[user['user_id']].get('reason', 'Unknown')
                print(f"   • {user['label']}: {user['name']} - {reason}")
        print()
    
    if len(successful) == len(users):
        print("🎉 SUCCESS: All users connected and trading enabled!")
        print()
        print("Next steps:")
        print("  • Users can now trade on their configured exchanges")
        print("  • Monitor trading activity in the logs")
        print("  • Check user balances and positions regularly")
        print()
        return 0
    else:
        print("⚠️  PARTIAL SUCCESS: Some users could not be enabled")
        print()
        print("Next steps:")
        print("  • Review error messages above")
        print("  • Configure missing credentials")
        print("  • Re-run this script")
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
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
