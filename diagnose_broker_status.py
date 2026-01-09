#!/usr/bin/env python3
"""
Broker Connection Diagnostic Tool
==================================

This script helps diagnose broker connection issues by:
1. Checking if credentials are configured
2. Testing connections to each broker
3. Providing actionable guidance for fixing issues
"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def check_env_var(name, description):
    """Check if an environment variable is set."""
    value = os.getenv(name, "").strip()
    if value:
        # Show length instead of value for security
        print(f"  ✅ {name}: Configured ({len(value)} chars)")
        return True
    else:
        print(f"  ❌ {name}: NOT SET")
        print(f"     Set this to enable {description}")
        return False


def diagnose_credentials():
    """Diagnose credential configuration for all brokers."""
    print("\n" + "="*70)
    print("CREDENTIAL CONFIGURATION CHECK")
    print("="*70)
    
    results = {}
    
    # Coinbase
    print("\n📊 COINBASE ADVANCED TRADE")
    has_key = check_env_var("COINBASE_API_KEY", "Coinbase trading")
    has_secret = check_env_var("COINBASE_API_SECRET", "Coinbase trading")
    results['coinbase'] = has_key and has_secret
    
    # Kraken MASTER
    print("\n📊 KRAKEN PRO (MASTER ACCOUNT)")
    has_key = check_env_var("KRAKEN_MASTER_API_KEY", "Kraken MASTER trading")
    has_secret = check_env_var("KRAKEN_MASTER_API_SECRET", "Kraken MASTER trading")
    results['kraken_master'] = has_key and has_secret
    
    # Alpaca
    print("\n📊 ALPACA")
    has_key = check_env_var("ALPACA_API_KEY", "Alpaca trading")
    has_secret = check_env_var("ALPACA_API_SECRET", "Alpaca trading")
    paper_mode = os.getenv("ALPACA_PAPER", "true")
    print(f"  ℹ️  ALPACA_PAPER: {paper_mode} ({'Paper trading' if paper_mode.lower() == 'true' else 'Live trading'})")
    results['alpaca'] = has_key and has_secret
    
    # OKX
    print("\n📊 OKX EXCHANGE")
    has_key = check_env_var("OKX_API_KEY", "OKX trading")
    has_secret = check_env_var("OKX_API_SECRET", "OKX trading")
    has_pass = check_env_var("OKX_PASSPHRASE", "OKX trading")
    testnet = os.getenv("OKX_USE_TESTNET", "false")
    print(f"  ℹ️  OKX_USE_TESTNET: {testnet} ({'Testnet' if testnet.lower() == 'true' else 'Live'})")
    results['okx'] = has_key and has_secret and has_pass
    
    # Binance
    print("\n📊 BINANCE")
    has_key = check_env_var("BINANCE_API_KEY", "Binance trading")
    has_secret = check_env_var("BINANCE_API_SECRET", "Binance trading")
    testnet = os.getenv("BINANCE_USE_TESTNET", "false")
    print(f"  ℹ️  BINANCE_USE_TESTNET: {testnet} ({'Testnet' if testnet.lower() == 'true' else 'Live'})")
    results['binance'] = has_key and has_secret
    
    return results


def test_connections(cred_results):
    """Test actual connections to configured brokers."""
    print("\n" + "="*70)
    print("CONNECTION TESTS")
    print("="*70)
    print("\nNOTE: This will attempt to connect to brokers with configured credentials.")
    print("Connection failures may indicate rate limiting, invalid credentials, or network issues.")
    print()
    
    from broker_manager import CoinbaseBroker, KrakenBroker, AlpacaBroker, OKXBroker, BinanceBroker, AccountType
    
    connection_results = {}
    
    # Test Coinbase
    if cred_results.get('coinbase'):
        print("📊 Testing Coinbase connection...")
        try:
            coinbase = CoinbaseBroker()
            if coinbase.connect():
                print("  ✅ Coinbase: Connected successfully")
                try:
                    balance = coinbase.get_account_balance()
                    print(f"     Balance: ${balance:,.2f}")
                except Exception as e:
                    print(f"     Warning: Could not fetch balance: {e}")
                connection_results['coinbase'] = True
            else:
                print("  ❌ Coinbase: Connection failed")
                connection_results['coinbase'] = False
        except Exception as e:
            print(f"  ❌ Coinbase: Error during connection: {e}")
            connection_results['coinbase'] = False
    else:
        print("⚪ Skipping Coinbase (credentials not configured)")
        connection_results['coinbase'] = None
    
    # Test Kraken
    if cred_results.get('kraken_master'):
        print("\n📊 Testing Kraken (MASTER) connection...")
        try:
            kraken = KrakenBroker(account_type=AccountType.MASTER)
            if kraken.connect():
                print("  ✅ Kraken: Connected successfully")
                try:
                    balance = kraken.get_account_balance()
                    print(f"     Balance: ${balance:,.2f}")
                except Exception as e:
                    print(f"     Warning: Could not fetch balance: {e}")
                connection_results['kraken'] = True
            else:
                print("  ❌ Kraken: Connection failed")
                connection_results['kraken'] = False
        except Exception as e:
            print(f"  ❌ Kraken: Error during connection: {e}")
            connection_results['kraken'] = False
    else:
        print("⚪ Skipping Kraken (credentials not configured)")
        connection_results['kraken'] = None
    
    # Test Alpaca
    if cred_results.get('alpaca'):
        print("\n📊 Testing Alpaca connection...")
        try:
            alpaca = AlpacaBroker()
            if alpaca.connect():
                print("  ✅ Alpaca: Connected successfully")
                try:
                    balance = alpaca.get_account_balance()
                    print(f"     Balance: ${balance:,.2f}")
                except Exception as e:
                    print(f"     Warning: Could not fetch balance: {e}")
                connection_results['alpaca'] = True
            else:
                print("  ❌ Alpaca: Connection failed")
                connection_results['alpaca'] = False
        except Exception as e:
            print(f"  ❌ Alpaca: Error during connection: {e}")
            connection_results['alpaca'] = False
    else:
        print("⚪ Skipping Alpaca (credentials not configured)")
        connection_results['alpaca'] = None
    
    # Test OKX
    if cred_results.get('okx'):
        print("\n📊 Testing OKX connection...")
        try:
            okx = OKXBroker()
            if okx.connect():
                print("  ✅ OKX: Connected successfully")
                try:
                    balance = okx.get_account_balance()
                    print(f"     Balance: ${balance:,.2f}")
                except Exception as e:
                    print(f"     Warning: Could not fetch balance: {e}")
                connection_results['okx'] = True
            else:
                print("  ❌ OKX: Connection failed")
                connection_results['okx'] = False
        except Exception as e:
            print(f"  ❌ OKX: Error during connection: {e}")
            connection_results['okx'] = False
    else:
        print("⚪ Skipping OKX (credentials not configured)")
        connection_results['okx'] = None
    
    # Test Binance
    if cred_results.get('binance'):
        print("\n📊 Testing Binance connection...")
        try:
            binance = BinanceBroker()
            if binance.connect():
                print("  ✅ Binance: Connected successfully")
                try:
                    balance = binance.get_account_balance()
                    print(f"     Balance: ${balance:,.2f}")
                except Exception as e:
                    print(f"     Warning: Could not fetch balance: {e}")
                connection_results['binance'] = True
            else:
                print("  ❌ Binance: Connection failed")
                connection_results['binance'] = False
        except Exception as e:
            print(f"  ❌ Binance: Error during connection: {e}")
            connection_results['binance'] = False
    else:
        print("⚪ Skipping Binance (credentials not configured)")
        connection_results['binance'] = None
    
    return connection_results


def provide_guidance(cred_results, connection_results):
    """Provide actionable guidance based on test results."""
    print("\n" + "="*70)
    print("RECOMMENDATIONS")
    print("="*70)
    
    # Count configured and connected brokers
    configured = sum(1 for v in cred_results.values() if v)
    connected = sum(1 for v in connection_results.values() if v is True)
    
    print(f"\n📊 Summary: {configured} broker(s) configured, {connected} broker(s) connected")
    
    if connected > 0:
        print("\n✅ SUCCESS! At least one broker is connected and ready to trade.")
        print("\n💡 The bot will use the following brokers for trading:")
        for broker, status in connection_results.items():
            if status is True:
                print(f"   • {broker.upper()}")
    else:
        print("\n⚠️  WARNING: No brokers are currently connected!")
        print("\n🔧 To fix this:")
        
        # Check if Coinbase failed to connect
        if cred_results.get('coinbase') and connection_results.get('coinbase') is False:
            print("\n1. COINBASE CONNECTION FAILED:")
            print("   This is often due to temporary rate limiting (403 errors).")
            print("   The bot has improved retry logic that should handle this automatically.")
            print("   ")
            print("   If the problem persists:")
            print("   • Verify your API key has 'view' and 'trade' permissions")
            print("   • Check that your API key is from Coinbase Advanced Trade (not Coinbase Pro)")
            print("   • Wait 5-10 minutes and try again (API rate limits reset)")
        
        # Check if credentials are missing
        if not cred_results.get('coinbase'):
            print("\n1. CONFIGURE COINBASE CREDENTIALS:")
            print("   Set these environment variables:")
            print("   export COINBASE_API_KEY='your-api-key'")
            print("   export COINBASE_API_SECRET='your-api-secret'")
        
        if not cred_results.get('kraken_master'):
            print("\n2. OPTIONAL - CONFIGURE KRAKEN (for additional broker):")
            print("   Set these environment variables:")
            print("   export KRAKEN_MASTER_API_KEY='your-api-key'")
            print("   export KRAKEN_MASTER_API_SECRET='your-api-secret'")
        
        if not cred_results.get('alpaca'):
            print("\n3. OPTIONAL - CONFIGURE ALPACA (for stock trading):")
            print("   Set these environment variables:")
            print("   export ALPACA_API_KEY='your-api-key'")
            print("   export ALPACA_API_SECRET='your-api-secret'")
            print("   export ALPACA_PAPER='true'  # or 'false' for live trading")


def main():
    """Run the diagnostic tool."""
    print("\n" + "="*70)
    print("NIJA BROKER CONNECTION DIAGNOSTIC TOOL")
    print("="*70)
    print("\nThis tool will help you diagnose broker connection issues.")
    print()
    
    # Step 1: Check credentials
    cred_results = diagnose_credentials()
    
    # Step 2: Test connections (only if at least one broker is configured)
    if any(cred_results.values()):
        input("\nPress Enter to test broker connections (this may take a moment)...")
        connection_results = test_connections(cred_results)
    else:
        print("\n⚠️  No broker credentials configured. Skipping connection tests.")
        connection_results = {}
    
    # Step 3: Provide guidance
    provide_guidance(cred_results, connection_results)
    
    print("\n" + "="*70)
    print("Diagnostic complete!")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
