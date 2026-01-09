#!/usr/bin/env python3
"""
NIJA Comprehensive Broker Diagnostic Tool
==========================================

This script checks the status of all configured brokers and provides
actionable guidance on how to fix any connection issues.

Usage:
    python3 diagnose_broker_connections.py
"""

import os
import sys

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

def check_env_credentials():
    """Check environment variables for broker credentials"""
    print_header("BROKER CREDENTIALS CHECK")
    
    all_ok = True
    issues = []
    
    # Coinbase
    print_section("1. Coinbase Advanced Trade (Primary Broker)")
    coinbase_jwt_pem = os.getenv("COINBASE_JWT_PEM", "").strip()
    coinbase_api_key = os.getenv("COINBASE_API_KEY", "").strip()
    coinbase_api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    
    if coinbase_jwt_pem or (coinbase_api_key and coinbase_api_secret):
        print("  ✅ Credentials: SET")
        if coinbase_jwt_pem:
            print(f"     Using JWT PEM ({len(coinbase_jwt_pem)} characters)")
        else:
            print(f"     Using API Key + Secret")
    else:
        print("  ❌ Credentials: MISSING")
        all_ok = False
        issues.append("Coinbase credentials not configured")
    
    # Kraken
    print_section("2. Kraken Pro (Crypto Trading)")
    kraken_master_key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
    kraken_master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()
    kraken_user_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "").strip()
    kraken_user_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "").strip()
    
    if kraken_master_key and kraken_master_secret:
        print("  ✅ MASTER Account: SET")
    else:
        print("  ⚠️  MASTER Account: NOT SET (optional)")
    
    if kraken_user_key and kraken_user_secret:
        print("  ✅ USER Account (Daivon): SET")
    else:
        print("  ⚠️  USER Account: NOT SET (optional)")
    
    # OKX
    print_section("3. OKX Exchange (Crypto + Futures)")
    okx_key = os.getenv("OKX_API_KEY", "").strip()
    okx_secret = os.getenv("OKX_API_SECRET", "").strip()
    okx_passphrase = os.getenv("OKX_PASSPHRASE", "").strip()
    
    okx_ready = False
    if okx_key and okx_secret and okx_passphrase:
        # Check if passphrase is a placeholder
        placeholder_values = ['REQUIRED_SET_YOUR_PASSPHRASE_HERE', 'your_passphrase', 'YOUR_PASSPHRASE']
        if okx_passphrase in placeholder_values:
            print("  ⚠️  Credentials: INCOMPLETE")
            print(f"     API Key: SET ({len(okx_key)} chars)")
            print(f"     API Secret: SET ({len(okx_secret)} chars)")
            print(f"     Passphrase: ❌ PLACEHOLDER VALUE - MUST BE UPDATED")
            issues.append("OKX passphrase is a placeholder - update with actual passphrase")
        else:
            print("  ✅ Credentials: SET")
            print(f"     API Key: SET ({len(okx_key)} chars)")
            print(f"     API Secret: SET ({len(okx_secret)} chars)")
            print(f"     Passphrase: SET ({len(okx_passphrase)} chars)")
            okx_ready = True
    elif okx_key or okx_secret or okx_passphrase:
        print("  ⚠️  Credentials: INCOMPLETE")
        print(f"     API Key: {'SET' if okx_key else '❌ MISSING'}")
        print(f"     API Secret: {'SET' if okx_secret else '❌ MISSING'}")
        print(f"     Passphrase: {'SET' if okx_passphrase else '❌ MISSING'}")
        issues.append("OKX credentials incomplete - all three required (key, secret, passphrase)")
    else:
        print("  ⚠️  Credentials: NOT CONFIGURED (optional)")
    
    # Binance
    print_section("4. Binance Exchange (Crypto)")
    binance_key = os.getenv("BINANCE_API_KEY", "").strip()
    binance_secret = os.getenv("BINANCE_API_SECRET", "").strip()
    
    if binance_key and binance_secret:
        print("  ✅ Credentials: SET")
        print(f"     API Key: SET ({len(binance_key)} chars)")
        print(f"     API Secret: SET ({len(binance_secret)} chars)")
    else:
        print("  ⚠️  Credentials: NOT CONFIGURED (optional)")
    
    # Alpaca
    print_section("5. Alpaca (Stock Trading)")
    alpaca_key = os.getenv("ALPACA_API_KEY", "").strip()
    alpaca_secret = os.getenv("ALPACA_API_SECRET", "").strip()
    alpaca_paper = os.getenv("ALPACA_PAPER", "true").lower()
    
    if alpaca_key and alpaca_secret:
        mode = "📄 PAPER TRADING" if alpaca_paper in ["true", "1", "yes"] else "🔴 LIVE TRADING"
        print(f"  ✅ Credentials: SET ({mode})")
        print(f"     API Key: SET ({len(alpaca_key)} chars)")
        print(f"     API Secret: SET ({len(alpaca_secret)} chars)")
    else:
        print("  ⚠️  Credentials: NOT CONFIGURED (optional)")
    
    return all_ok, issues

def test_broker_connections():
    """Test actual connections to configured brokers"""
    print_header("BROKER CONNECTION TEST")
    
    connected_brokers = []
    failed_brokers = []
    
    # Try loading broker modules
    try:
        from broker_manager import (
            BrokerManager, BrokerType, 
            CoinbaseBroker, KrakenBroker, OKXBroker, 
            BinanceBroker, AlpacaBroker
        )
        
        broker_manager = BrokerManager()
        
        # Test Coinbase
        print_section("Testing Coinbase Connection")
        try:
            coinbase = CoinbaseBroker()
            if coinbase.connect():
                broker_manager.add_broker(coinbase)
                balance = coinbase.get_account_balance()
                connected_brokers.append(("Coinbase", balance))
                print(f"  ✅ Connected - Balance: ${balance:,.2f}")
            else:
                failed_brokers.append(("Coinbase", "Connection failed"))
                print("  ❌ Connection failed")
        except Exception as e:
            failed_brokers.append(("Coinbase", str(e)))
            print(f"  ❌ Error: {e}")
        
        # Test Kraken
        print_section("Testing Kraken Connection")
        try:
            kraken = KrakenBroker()
            if kraken.connect():
                broker_manager.add_broker(kraken)
                balance = kraken.get_account_balance()
                connected_brokers.append(("Kraken", balance))
                print(f"  ✅ Connected - Balance: ${balance:,.2f}")
            else:
                failed_brokers.append(("Kraken", "Connection failed"))
                print("  ⚠️  Connection failed (credentials may not be configured)")
        except Exception as e:
            failed_brokers.append(("Kraken", str(e)))
            print(f"  ⚠️  Error: {e}")
        
        # Test OKX
        print_section("Testing OKX Connection")
        try:
            okx = OKXBroker()
            if okx.connect():
                broker_manager.add_broker(okx)
                balance = okx.get_account_balance()
                connected_brokers.append(("OKX", balance))
                print(f"  ✅ Connected - Balance: ${balance:,.2f}")
            else:
                failed_brokers.append(("OKX", "Connection failed - check passphrase"))
                print("  ⚠️  Connection failed (check passphrase configuration)")
        except Exception as e:
            failed_brokers.append(("OKX", str(e)))
            print(f"  ⚠️  Error: {e}")
        
        # Test Binance
        print_section("Testing Binance Connection")
        try:
            binance = BinanceBroker()
            if binance.connect():
                broker_manager.add_broker(binance)
                balance = binance.get_account_balance()
                connected_brokers.append(("Binance", balance))
                print(f"  ✅ Connected - Balance: ${balance:,.2f}")
            else:
                failed_brokers.append(("Binance", "Connection failed"))
                print("  ⚠️  Connection failed (credentials may not be configured)")
        except Exception as e:
            failed_brokers.append(("Binance", str(e)))
            print(f"  ⚠️  Error: {e}")
        
        # Test Alpaca
        print_section("Testing Alpaca Connection")
        try:
            alpaca = AlpacaBroker()
            if alpaca.connect():
                broker_manager.add_broker(alpaca)
                balance = alpaca.get_account_balance()
                connected_brokers.append(("Alpaca", balance))
                print(f"  ✅ Connected - Balance: ${balance:,.2f}")
            else:
                failed_brokers.append(("Alpaca", "Connection failed"))
                print("  ⚠️  Connection failed (credentials may not be configured)")
        except Exception as e:
            failed_brokers.append(("Alpaca", str(e)))
            print(f"  ⚠️  Error: {e}")
        
        # Summary
        print_header("CONNECTION SUMMARY")
        
        if connected_brokers:
            print(f"\n✅ CONNECTED BROKERS: {len(connected_brokers)}")
            total_balance = sum(balance for _, balance in connected_brokers)
            for broker_name, balance in connected_brokers:
                print(f"   • {broker_name}: ${balance:,.2f}")
            print(f"\n💰 TOTAL BALANCE: ${total_balance:,.2f}")
            
            # Show primary broker
            primary = broker_manager.get_primary_broker()
            if primary:
                print(f"\n📌 PRIMARY BROKER: {primary.broker_type.value}")
        else:
            print("\n❌ NO BROKERS CONNECTED")
            print("   At least one broker must be configured to start trading")
        
        if failed_brokers:
            print(f"\n⚠️  FAILED CONNECTIONS: {len(failed_brokers)}")
            for broker_name, error in failed_brokers:
                print(f"   • {broker_name}: {error}")
        
        return connected_brokers, failed_brokers
        
    except ImportError as e:
        print(f"\n❌ Failed to import broker modules: {e}")
        print("   Make sure you're running from the repository root")
        return [], []

def print_recommendations(credential_issues, connected_brokers, failed_brokers):
    """Print actionable recommendations"""
    print_header("RECOMMENDATIONS")
    
    if not connected_brokers:
        print("\n🚨 CRITICAL: No brokers are connected!")
        print("\nTo start trading, you MUST configure at least ONE broker:")
        print("\n1. Coinbase (Recommended - Easiest Setup)")
        print("   ✓ Most reliable for crypto trading")
        print("   ✓ Good liquidity and market selection")
        print("   → See BROKER_SETUP_GUIDE.md for setup instructions")
        
    if credential_issues:
        print("\n⚠️  CREDENTIAL ISSUES FOUND:")
        for i, issue in enumerate(credential_issues, 1):
            print(f"\n{i}. {issue}")
            
            if "OKX passphrase" in issue:
                print("   → Action: Edit .env file, line 32")
                print("   → Set: OKX_PASSPHRASE=your_actual_passphrase")
                print("   → Where to find: OKX API Management page (when you created the API key)")
    
    if len(connected_brokers) == 1:
        print("\n✅ Good! You have 1 broker connected.")
        print("   You can start trading immediately.")
        print("\n💡 Optional: Configure additional brokers for:")
        print("   • Diversification across exchanges")
        print("   • Access to different markets/coins")
        print("   • Redundancy if one exchange has issues")
    
    elif len(connected_brokers) > 1:
        print(f"\n🎉 Excellent! You have {len(connected_brokers)} brokers connected.")
        print("   NIJA will trade across all connected brokers simultaneously.")
        print("   Each broker operates independently for maximum resilience.")
    
    print("\n" + "=" * 80)
    print("📚 For detailed setup instructions, see: BROKER_SETUP_GUIDE.md")
    print("=" * 80)

def main():
    """Main diagnostic routine"""
    print("=" * 80)
    print("  NIJA MULTI-BROKER DIAGNOSTIC TOOL")
    print("  Checking broker credentials and connections...")
    print("=" * 80)
    
    # Step 1: Check credentials
    credentials_ok, credential_issues = check_env_credentials()
    
    # Step 2: Test connections
    connected_brokers, failed_brokers = test_broker_connections()
    
    # Step 3: Provide recommendations
    print_recommendations(credential_issues, connected_brokers, failed_brokers)
    
    # Exit code
    if connected_brokers:
        print("\n✅ READY TO TRADE")
        return 0
    else:
        print("\n❌ NOT READY - Fix broker configuration first")
        return 1

if __name__ == "__main__":
    try:
        # Load environment from .env
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            print("⚠️  python-dotenv not installed, using system environment variables")
        
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nDiagnostic cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
