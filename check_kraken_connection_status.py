#!/usr/bin/env python3
"""
NIJA Kraken Connection Status Checker
======================================

This script checks whether NIJA is currently connected to Kraken Pro
and provides detailed information about the current broker configuration.

Usage:
    python3 check_kraken_connection_status.py
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def print_header(title):
    """Print a formatted header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_section(title):
    """Print a formatted section title"""
    print("\n" + "-" * 70)
    print(f"  {title}")
    print("-" * 70)

def check_kraken_credentials():
    """Check if Kraken API credentials are configured"""
    api_key = os.getenv("KRAKEN_API_KEY")
    api_secret = os.getenv("KRAKEN_API_SECRET")
    
    print_section("Kraken API Credentials")
    
    if api_key and api_secret:
        print(f"  ✅ KRAKEN_API_KEY: Set ({len(api_key)} characters)")
        print(f"  ✅ KRAKEN_API_SECRET: Set ({len(api_secret)} characters)")
        return True
    else:
        if not api_key:
            print("  ❌ KRAKEN_API_KEY: Not set")
        if not api_secret:
            print("  ❌ KRAKEN_API_SECRET: Not set")
        return False

def test_kraken_connection():
    """Test actual connection to Kraken Pro API"""
    print_section("Kraken Connection Test")
    
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        
        api_key = os.getenv("KRAKEN_API_KEY")
        api_secret = os.getenv("KRAKEN_API_SECRET")
        
        if not api_key or not api_secret:
            print("  ❌ Cannot test connection: Credentials not found")
            return False
        
        # Initialize Kraken API
        api = krakenex.API(key=api_key, secret=api_secret)
        
        # Test connection by fetching account balance
        print("  🔄 Testing connection to Kraken Pro...")
        balance = api.query_private('Balance')
        
        if balance and 'error' in balance:
            if balance['error']:
                error_msgs = ', '.join(balance['error'])
                print(f"  ❌ Connection failed: {error_msgs}")
                return False
        
        if balance and 'result' in balance:
            print("  ✅ Successfully connected to Kraken Pro!")
            
            # Display balance
            result = balance.get('result', {})
            usd_balance = float(result.get('ZUSD', 0))
            usdt_balance = float(result.get('USDT', 0))
            
            print(f"\n  Account Balance:")
            print(f"    USD:  ${usd_balance:.2f}")
            print(f"    USDT: ${usdt_balance:.2f}")
            print(f"    Total: ${usd_balance + usdt_balance:.2f}")
            
            # List other assets if any
            other_assets = {k: v for k, v in result.items() if k not in ['ZUSD', 'USDT']}
            if other_assets:
                print(f"\n  Other assets:")
                for asset, amount in other_assets.items():
                    print(f"    {asset}: {amount}")
            
            return True
        else:
            print("  ❌ Connection failed: No balance data returned")
            return False
            
    except ImportError:
        print("  ❌ Kraken SDK not installed")
        print("     Install with: pip install krakenex pykrakenapi")
        return False
    except Exception as e:
        print(f"  ❌ Connection error: {e}")
        return False

def check_current_broker_config():
    """Check which broker is currently configured in the bot"""
    print_section("Current NIJA Broker Configuration")
    
    # Check trading_strategy.py to see which broker is being used
    try:
        with open('bot/trading_strategy.py', 'r') as f:
            content = f.read()
            
        if 'CoinbaseBroker()' in content and 'self.broker = CoinbaseBroker()' in content:
            print("  📍 Active Broker: Coinbase Advanced Trade")
            print("  📝 Location: bot/trading_strategy.py (line ~131)")
            print("  🔗 Using: dantelrharrell@gmail.com account")
            return "coinbase"
        elif 'KrakenBroker()' in content and 'self.broker = KrakenBroker()' in content:
            print("  📍 Active Broker: Kraken Pro")
            return "kraken"
        else:
            print("  ⚠️  Could not determine active broker from code")
            return "unknown"
            
    except Exception as e:
        print(f"  ❌ Error reading configuration: {e}")
        return "error"

def check_kraken_code_status():
    """Check if Kraken integration code is present and ready"""
    print_section("Kraken Integration Code Status")
    
    try:
        # Check broker_manager.py for KrakenBroker class
        with open('bot/broker_manager.py', 'r') as f:
            content = f.read()
            
        if 'class KrakenBroker' in content:
            print("  ✅ KrakenBroker class: Implemented in bot/broker_manager.py")
            print("     - Supports spot trading (USD/USDT pairs)")
            print("     - Market and limit orders supported")
            print("     - Real-time account balance")
            print("     - Historical candle data (OHLCV)")
        else:
            print("  ❌ KrakenBroker class: Not found")
            
        # Check if it's imported in apex_live_trading.py
        with open('bot/apex_live_trading.py', 'r') as f:
            content = f.read()
            
        if 'from broker_manager import' in content and 'KrakenBroker' in content:
            print("  ✅ KrakenBroker import: Available in apex_live_trading.py")
            
            # Check if it's being used
            if '# kraken = KrakenBroker()' in content:
                print("  ⚠️  Kraken initialization: Commented out (not active)")
                print("     Lines 323-325 in apex_live_trading.py")
            elif 'kraken = KrakenBroker()' in content:
                print("  ✅ Kraken initialization: Active")
        
    except Exception as e:
        print(f"  ❌ Error checking code: {e}")

def main():
    """Main function"""
    print_header("NIJA Kraken Pro Connection Status Report")
    print(f"  Generated: {os.popen('date').read().strip()}")
    
    # Check current broker
    current_broker = check_current_broker_config()
    
    # Check Kraken credentials
    creds_ok = check_kraken_credentials()
    
    # Check Kraken integration code
    check_kraken_code_status()
    
    # Test Kraken connection if credentials are set
    if creds_ok:
        connection_ok = test_kraken_connection()
    else:
        connection_ok = False
    
    # Print summary
    print_header("SUMMARY")
    
    if current_broker == "coinbase":
        print("\n  🔴 NIJA IS NOT CONNECTED TO KRAKEN PRO")
        print("\n  Current Status:")
        print("    • Active Broker: Coinbase Advanced Trade")
        print("    • Account: dantelrharrell@gmail.com")
        print("    • All trades are being executed on Coinbase")
        
        if creds_ok and connection_ok:
            print("\n  ✅ Kraken Pro is configured and credentials are valid")
            print("     but the bot is NOT using it for trading.")
            print("\n  📝 To switch to Kraken Pro:")
            print("     1. Edit bot/trading_strategy.py")
            print("     2. Replace 'self.broker = CoinbaseBroker()' with 'self.broker = KrakenBroker()'")
            print("     3. Import KrakenBroker from broker_manager")
            print("     4. Redeploy the bot")
        elif creds_ok and not connection_ok:
            print("\n  ⚠️  Kraken credentials are set but connection failed")
            print("     Check credentials and API permissions")
        else:
            print("\n  ℹ️  Kraken credentials are not configured")
            print("     If you want to use Kraken, set KRAKEN_API_KEY and KRAKEN_API_SECRET")
    
    elif current_broker == "kraken":
        print("\n  🟢 NIJA IS CONNECTED TO KRAKEN PRO")
        print("\n  Current Status:")
        print("    • Active Broker: Kraken Pro")
        print("    • All trades are being executed on Kraken")
        
        if connection_ok:
            print("    • Connection status: Active and working")
        else:
            print("    • Connection status: Configured but connection failed")
    
    else:
        print("\n  ⚠️  UNABLE TO DETERMINE BROKER STATUS")
        print("     Please check bot/trading_strategy.py manually")
    
    print("\n" + "=" * 70 + "\n")

if __name__ == "__main__":
    main()
