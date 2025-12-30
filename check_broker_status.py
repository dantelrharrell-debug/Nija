#!/usr/bin/env python3
"""
NIJA Broker Connection Status Checker
======================================

This script checks the connection status of all supported brokerages
and displays which ones are connected and ready to trade.

Supported Brokers:
- Coinbase Advanced Trade (Primary)
- Kraken Pro
- OKX
- Binance
- Alpaca (Stocks)

Usage:
    python3 check_broker_status.py
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def print_header(title):
    """Print a formatted header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_section(title):
    """Print a formatted section title"""
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80)

def check_credentials(broker_name, required_vars):
    """Check if required environment variables are set for a broker
    
    Args:
        broker_name: Name of the broker
        required_vars: Either a list of required variables, or a list of lists 
                      representing alternative credential sets
    
    Returns:
        (credentials_ok, missing_vars_or_alternatives)
    """
    # Handle alternative credential sets (e.g., Coinbase can use JWT or API key)
    if required_vars and isinstance(required_vars[0], list):
        # Check each alternative set
        for var_set in required_vars:
            missing = []
            for var in var_set:
                if not os.getenv(var):
                    missing.append(var)
            if len(missing) == 0:
                # Found a complete credential set
                return True, []
        # None of the alternatives were complete
        return False, required_vars
    else:
        # Single set of required variables
        missing = []
        for var in required_vars:
            if not os.getenv(var):
                missing.append(var)
        return len(missing) == 0, missing

def test_broker_connection(broker_name, broker_class):
    """Test connection to a specific broker"""
    try:
        broker = broker_class()
        if broker.connect():
            # Try to get balance to verify connection works
            try:
                balance = broker.get_account_balance()
                return True, f"${balance:,.2f}", None
            except Exception as e:
                return True, "Connected (balance unavailable)", str(e)
        else:
            return False, None, "Connection returned False"
    except Exception as e:
        return False, None, str(e)

def main():
    """Main function to check all broker statuses"""
    print_header("NIJA Multi-Broker Connection Status Report")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Import broker classes
    try:
        from broker_manager import (
            CoinbaseBroker, KrakenBroker, OKXBroker, 
            BinanceBroker, AlpacaBroker
        )
    except ImportError as e:
        print(f"\n❌ Error importing broker classes: {e}")
        sys.exit(1)
    
    # Define broker configurations
    brokers = [
        {
            'name': 'Coinbase Advanced Trade',
            'class': CoinbaseBroker,
            # Check for either new JWT format or old API key format
            'credentials': [
                ['COINBASE_JWT_PEM', 'COINBASE_JWT_KID', 'COINBASE_JWT_ISSUER'],
                ['COINBASE_API_KEY', 'COINBASE_API_SECRET']
            ],
            'icon': '🟦',
            'primary': True,
            'type': 'Crypto'
        },
        {
            'name': 'Kraken Pro',
            'class': KrakenBroker,
            'credentials': ['KRAKEN_API_KEY', 'KRAKEN_API_SECRET'],
            'icon': '🟪',
            'primary': False,
            'type': 'Crypto'
        },
        {
            'name': 'OKX',
            'class': OKXBroker,
            'credentials': ['OKX_API_KEY', 'OKX_API_SECRET', 'OKX_PASSPHRASE'],
            'icon': '⬛',
            'primary': False,
            'type': 'Crypto'
        },
        {
            'name': 'Binance',
            'class': BinanceBroker,
            'credentials': ['BINANCE_API_KEY', 'BINANCE_API_SECRET'],
            'icon': '🟨',
            'primary': False,
            'type': 'Crypto'
        },
        {
            'name': 'Alpaca',
            'class': AlpacaBroker,
            'credentials': ['ALPACA_API_KEY', 'ALPACA_API_SECRET'],
            'icon': '🟩',
            'primary': False,
            'type': 'Stocks'
        }
    ]
    
    # Track results
    connected = []
    not_connected = []
    no_credentials = []
    total_balance = 0.0
    
    # Check each broker
    print_section("Checking Broker Connections")
    
    for broker_config in brokers:
        name = broker_config['name']
        icon = broker_config['icon']
        broker_class = broker_config['class']
        credentials = broker_config['credentials']
        primary = broker_config['primary']
        asset_type = broker_config['type']
        
        print(f"\n{icon} {name} ({asset_type})" + (" [PRIMARY]" if primary else ""))
        
        # Check credentials
        creds_ok, missing = check_credentials(name, credentials)
        
        if not creds_ok:
            print(f"   ⚠️  Credentials not configured")
            # Handle alternative credential sets display
            if missing and isinstance(missing[0], list):
                print(f"   Need one of:")
                for i, var_set in enumerate(missing, 1):
                    print(f"     Option {i}: {', '.join(var_set)}")
            else:
                print(f"   Missing: {', '.join(missing)}")
            no_credentials.append({
                'name': name,
                'icon': icon,
                'missing': missing,
                'type': asset_type
            })
            continue
        
        print(f"   ✅ Credentials configured")
        
        # Test connection
        print(f"   🔄 Testing connection...")
        is_connected, balance, error = test_broker_connection(name, broker_class)
        
        if is_connected:
            print(f"   ✅ Connected successfully")
            if balance:
                print(f"   💰 Balance: {balance}")
                # Try to extract numeric value for total
                try:
                    if balance.startswith('$'):
                        balance_value = float(balance.replace('$', '').replace(',', ''))
                        total_balance += balance_value
                except:
                    pass
            
            connected.append({
                'name': name,
                'icon': icon,
                'balance': balance,
                'primary': primary,
                'type': asset_type
            })
        else:
            print(f"   ❌ Connection failed")
            if error:
                print(f"   Error: {error[:100]}")
            not_connected.append({
                'name': name,
                'icon': icon,
                'error': error,
                'type': asset_type
            })
    
    # Print summary
    print_header("SUMMARY")
    
    if connected:
        print(f"\n✅ {len(connected)} BROKER(S) CONNECTED AND READY TO TRADE:")
        for broker in connected:
            primary_tag = " [PRIMARY]" if broker.get('primary') else ""
            balance_info = f" - {broker['balance']}" if broker.get('balance') else ""
            print(f"   {broker['icon']} {broker['name']}{primary_tag}{balance_info}")
        
        if total_balance > 0:
            print(f"\n💰 Total Combined Balance: ${total_balance:,.2f}")
    else:
        print("\n❌ NO BROKERS CONNECTED")
    
    if not_connected:
        print(f"\n⚠️  {len(not_connected)} BROKER(S) WITH FAILED CONNECTIONS:")
        for broker in not_connected:
            print(f"   {broker['icon']} {broker['name']}")
            if broker.get('error'):
                error_msg = broker['error'][:80] + "..." if len(broker['error']) > 80 else broker['error']
                print(f"      Error: {error_msg}")
    
    if no_credentials:
        print(f"\n📝 {len(no_credentials)} BROKER(S) NOT CONFIGURED:")
        for broker in no_credentials:
            print(f"   {broker['icon']} {broker['name']} ({broker['type']})")
            missing = broker['missing']
            if missing and isinstance(missing[0], list):
                print(f"      Need one of:")
                for i, var_set in enumerate(missing, 1):
                    print(f"        Option {i}: {', '.join(var_set)}")
            else:
                print(f"      Set: {', '.join(missing)}")
    
    # Trading readiness
    print_section("Trading Readiness Status")
    
    if connected:
        print("\n✅ NIJA IS READY TO TRADE")
        print(f"\n   Active Brokers: {len(connected)}")
        print(f"   Trading Capabilities:")
        
        # Show capabilities by asset type
        crypto_brokers = [b for b in connected if b['type'] == 'Crypto']
        stock_brokers = [b for b in connected if b['type'] == 'Stocks']
        
        if crypto_brokers:
            print(f"      • Cryptocurrency: {len(crypto_brokers)} exchange(s)")
            for b in crypto_brokers:
                print(f"        - {b['name']}")
        
        if stock_brokers:
            print(f"      • Stocks: {len(stock_brokers)} broker(s)")
            for b in stock_brokers:
                print(f"        - {b['name']}")
        
        # Find primary broker
        primary = next((b for b in connected if b.get('primary')), connected[0])
        print(f"\n   Primary Trading Broker: {primary['name']}")
        
        if total_balance > 0:
            print(f"   Total Available Capital: ${total_balance:,.2f}")
        
        print("\n   🚀 The bot can execute trades on the connected exchanges.")
    else:
        print("\n❌ NIJA IS NOT READY TO TRADE")
        print("\n   No brokers are currently connected.")
        print("   Please configure at least one broker's credentials in the .env file.")
    
    # Next steps
    if no_credentials or not_connected:
        print_section("Next Steps")
        
        if no_credentials:
            print("\n📝 To configure additional brokers:")
            print("   1. Copy .env.example to .env (if not done already)")
            print("   2. Add API credentials for the brokers you want to use")
            print("   3. See BROKER_INTEGRATION_GUIDE.md for detailed setup instructions")
        
        if not_connected:
            print("\n🔧 To fix connection issues:")
            print("   1. Verify your API credentials are correct")
            print("   2. Check that API keys have required permissions")
            print("   3. For testnet accounts, ensure *_USE_TESTNET is set correctly")
            print("   4. Review error messages above for specific issues")
    
    print("\n" + "=" * 80 + "\n")
    
    # Exit code based on connection status
    if connected:
        sys.exit(0)  # Success - at least one broker connected
    else:
        sys.exit(1)  # Failure - no brokers connected

if __name__ == "__main__":
    main()
