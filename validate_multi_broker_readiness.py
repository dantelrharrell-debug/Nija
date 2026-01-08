#!/usr/bin/env python3
"""
Multi-Broker Trading Readiness Validator
=========================================

This script validates that OKX and Kraken are properly configured and ready
for independent multi-broker trading.

Checks performed:
1. Environment credentials configuration
2. Python SDK dependencies installed
3. Broker class implementations
4. API connectivity (if credentials provided)
5. Account balances and funding status
6. Multi-broker independent trading configuration

Usage:
    python3 validate_multi_broker_readiness.py
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Minimum balance required for trading
MINIMUM_TRADING_BALANCE = 2.0


def print_header(title):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_section(title):
    """Print formatted section title"""
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80)


def print_status(item, status, details=""):
    """Print status line"""
    status_icon = "✅" if status else "❌"
    status_text = "READY" if status else "NOT READY"
    print(f"{status_icon} {item}: {status_text}")
    if details:
        print(f"   → {details}")


def check_kraken_credentials():
    """Check if Kraken API credentials are configured"""
    api_key = os.getenv("KRAKEN_API_KEY", "").strip()
    api_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
    
    configured = bool(api_key and api_secret)
    
    if configured:
        details = f"API Key: {len(api_key)} chars, Secret: {len(api_secret)} chars"
    else:
        details = "Set KRAKEN_API_KEY and KRAKEN_API_SECRET in .env"
    
    return configured, details


def check_okx_credentials():
    """Check if OKX API credentials are configured"""
    api_key = os.getenv("OKX_API_KEY", "").strip()
    api_secret = os.getenv("OKX_API_SECRET", "").strip()
    passphrase = os.getenv("OKX_PASSPHRASE", "").strip()
    use_testnet = os.getenv("OKX_USE_TESTNET", "false").lower()
    
    configured = bool(api_key and api_secret and passphrase)
    
    if configured:
        details = f"API Key: {len(api_key)} chars, Secret: {len(api_secret)} chars, "
        details += f"Passphrase: {len(passphrase)} chars, Testnet: {use_testnet}"
    else:
        details = "Set OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE in .env"
    
    return configured, details


def check_kraken_sdk():
    """Check if Kraken SDK is installed"""
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        return True, f"krakenex and pykrakenapi installed"
    except ImportError as e:
        return False, f"Install with: pip install krakenex pykrakenapi"


def check_okx_sdk():
    """Check if OKX SDK is installed"""
    try:
        import okx
        return True, "okx SDK installed"
    except ImportError:
        return False, "Install with: pip install okx"


def test_kraken_connection():
    """Test actual connection to Kraken API"""
    try:
        import krakenex
        
        api_key = os.getenv("KRAKEN_API_KEY", "").strip()
        api_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
        
        if not api_key or not api_secret:
            return False, "Credentials not configured", None
        
        # Initialize API
        api = krakenex.API(key=api_key, secret=api_secret)
        
        # Test connection
        balance = api.query_private('Balance')
        
        if balance and 'error' in balance and balance['error']:
            error_msgs = ', '.join(balance['error'])
            return False, f"API Error: {error_msgs}", None
        
        if balance and 'result' in balance:
            result = balance.get('result', {})
            usd_balance = float(result.get('ZUSD', 0))
            usdt_balance = float(result.get('USDT', 0))
            total = usd_balance + usdt_balance
            
            details = f"USD: ${usd_balance:.2f}, USDT: ${usdt_balance:.2f}, Total: ${total:.2f}"
            return True, details, total
        
        return False, "No balance data returned", None
        
    except ImportError:
        return False, "Kraken SDK not installed", None
    except Exception as e:
        return False, f"Connection error: {e}", None


def test_okx_connection():
    """Test actual connection to OKX API"""
    try:
        from okx.api import Account
        
        api_key = os.getenv("OKX_API_KEY", "").strip()
        api_secret = os.getenv("OKX_API_SECRET", "").strip()
        passphrase = os.getenv("OKX_PASSPHRASE", "").strip()
        use_testnet = os.getenv("OKX_USE_TESTNET", "false").lower() in ["true", "1", "yes"]
        
        if not api_key or not api_secret or not passphrase:
            return False, "Credentials not configured", None
        
        # Initialize API
        flag = "1" if use_testnet else "0"
        account_api = Account(api_key, api_secret, passphrase, flag)
        
        # Test connection
        result = account_api.get_balance()
        
        if result and result.get('code') == '0':
            data = result.get('data', [])
            if data and len(data) > 0:
                # Get USDT balance
                usdt_balance = 0.0
                for detail in data[0].get('details', []):
                    if detail.get('ccy') == 'USDT':
                        usdt_balance = float(detail.get('availBal', 0))
                        break
                
                env_type = "Testnet" if use_testnet else "Live"
                details = f"USDT: ${usdt_balance:.2f} ({env_type})"
                return True, details, usdt_balance
            else:
                return True, "Connected but no balance data", 0.0
        else:
            code = result.get('code', 'unknown')
            msg = result.get('msg', 'Unknown error')
            return False, f"API Error {code}: {msg}", None
        
    except ImportError:
        return False, "OKX SDK not installed", None
    except Exception as e:
        return False, f"Connection error: {e}", None


def check_broker_classes():
    """Check if broker classes are implemented"""
    try:
        from broker_manager import KrakenBroker, OKXBroker
        
        kraken_ok = hasattr(KrakenBroker, 'connect') and hasattr(KrakenBroker, 'get_account_balance')
        okx_ok = hasattr(OKXBroker, 'connect') and hasattr(OKXBroker, 'get_account_balance')
        
        return kraken_ok, okx_ok
    except ImportError as e:
        return False, False


def check_multi_broker_config():
    """Check if multi-broker independent trading is configured"""
    multi_broker = os.getenv("MULTI_BROKER_INDEPENDENT", "false").lower() in ["true", "1", "yes"]
    details = "Enabled" if multi_broker else "Not enabled (set MULTI_BROKER_INDEPENDENT=true)"
    return multi_broker, details


def main():
    """Run all validation checks"""
    print("\n" + "🔥" * 40)
    print("   MULTI-BROKER TRADING READINESS VALIDATOR")
    print("   OKX + KRAKEN INDEPENDENT TRADING SETUP")
    print("🔥" * 40)
    
    all_checks = []
    
    # ===== KRAKEN CHECKS =====
    print_header("KRAKEN PRO VALIDATION")
    
    print_section("1. Kraken Credentials")
    kraken_creds_ok, kraken_creds_details = check_kraken_credentials()
    print_status("Kraken API Credentials", kraken_creds_ok, kraken_creds_details)
    all_checks.append(("Kraken Credentials", kraken_creds_ok))
    
    print_section("2. Kraken SDK")
    kraken_sdk_ok, kraken_sdk_details = check_kraken_sdk()
    print_status("Kraken SDK Installation", kraken_sdk_ok, kraken_sdk_details)
    all_checks.append(("Kraken SDK", kraken_sdk_ok))
    
    print_section("3. Kraken Connection Test")
    kraken_conn_ok, kraken_conn_details, kraken_balance = test_kraken_connection()
    print_status("Kraken API Connection", kraken_conn_ok, kraken_conn_details)
    all_checks.append(("Kraken Connection", kraken_conn_ok))
    
    # ===== OKX CHECKS =====
    print_header("OKX EXCHANGE VALIDATION")
    
    print_section("1. OKX Credentials")
    okx_creds_ok, okx_creds_details = check_okx_credentials()
    print_status("OKX API Credentials", okx_creds_ok, okx_creds_details)
    all_checks.append(("OKX Credentials", okx_creds_ok))
    
    print_section("2. OKX SDK")
    okx_sdk_ok, okx_sdk_details = check_okx_sdk()
    print_status("OKX SDK Installation", okx_sdk_ok, okx_sdk_details)
    all_checks.append(("OKX SDK", okx_sdk_ok))
    
    print_section("3. OKX Connection Test")
    okx_conn_ok, okx_conn_details, okx_balance = test_okx_connection()
    print_status("OKX API Connection", okx_conn_ok, okx_conn_details)
    all_checks.append(("OKX Connection", okx_conn_ok))
    
    # ===== CODE IMPLEMENTATION CHECKS =====
    print_header("CODE IMPLEMENTATION VALIDATION")
    
    print_section("1. Broker Classes")
    kraken_class_ok, okx_class_ok = check_broker_classes()
    print_status("KrakenBroker Class", kraken_class_ok, "Implemented in bot/broker_manager.py")
    print_status("OKXBroker Class", okx_class_ok, "Implemented in bot/broker_manager.py")
    all_checks.append(("Kraken Class", kraken_class_ok))
    all_checks.append(("OKX Class", okx_class_ok))
    
    print_section("2. Multi-Broker Configuration")
    multi_broker_ok, multi_broker_details = check_multi_broker_config()
    print_status("Independent Multi-Broker Trading", multi_broker_ok, multi_broker_details)
    all_checks.append(("Multi-Broker Config", multi_broker_ok))
    
    # ===== FUNDING STATUS =====
    print_header("FUNDING STATUS")
    
    # Check funding status and store in variables for later use
    kraken_funded = False
    okx_funded = False
    
    if kraken_balance is not None:
        kraken_funded = kraken_balance >= MINIMUM_TRADING_BALANCE
        print_status(
            "Kraken Funded",
            kraken_funded,
            f"${kraken_balance:.2f} (minimum: ${MINIMUM_TRADING_BALANCE:.2f})"
        )
    else:
        print_status("Kraken Funded", False, "Cannot verify - connection failed")
    
    if okx_balance is not None:
        okx_funded = okx_balance >= MINIMUM_TRADING_BALANCE
        print_status(
            "OKX Funded",
            okx_funded,
            f"${okx_balance:.2f} (minimum: ${MINIMUM_TRADING_BALANCE:.2f})"
        )
    else:
        print_status("OKX Funded", False, "Cannot verify - connection failed")
    
    # ===== SUMMARY =====
    print_header("VALIDATION SUMMARY")
    
    passed = sum(1 for _, status in all_checks if status)
    total = len(all_checks)
    
    print(f"\n📊 Checks Passed: {passed}/{total}")
    print("\nDetailed Results:")
    for check_name, status in all_checks:
        icon = "✅" if status else "❌"
        print(f"  {icon} {check_name}")
    
    # ===== FINAL VERDICT =====
    print_header("FINAL VERDICT")
    
    kraken_ready = kraken_creds_ok and kraken_sdk_ok and kraken_conn_ok
    okx_ready = okx_creds_ok and okx_sdk_ok and okx_conn_ok
    
    print("\n" + "=" * 80)
    
    if kraken_ready and okx_ready:
        print("🎉 BOTH BROKERS ARE READY FOR TRADING! 🎉")
        print("\n✅ Kraken Status: READY")
        if kraken_balance is not None:
            print(f"   💰 Balance: ${kraken_balance:.2f}")
            if kraken_funded:
                print(f"   ✅ Funded (minimum: ${MINIMUM_TRADING_BALANCE:.2f})")
            else:
                print(f"   ⚠️  Underfunded (minimum: ${MINIMUM_TRADING_BALANCE:.2f})")
        
        print("\n✅ OKX Status: READY")
        if okx_balance is not None:
            print(f"   💰 Balance: ${okx_balance:.2f}")
            if okx_funded:
                print(f"   ✅ Funded (minimum: ${MINIMUM_TRADING_BALANCE:.2f})")
            else:
                print(f"   ⚠️  Unfunded - Transfer funds to start trading")
        
        if multi_broker_ok:
            print("\n✅ Multi-Broker Independent Trading: ENABLED")
            print("   Each broker will trade in isolated thread")
            print("   Failures in one broker won't affect others")
        else:
            print("\n⚠️  Multi-Broker Independent Trading: NOT ENABLED")
            print("   Set MULTI_BROKER_INDEPENDENT=true in .env to enable")
        
        print("\n📝 Next Steps:")
        print("   1. Verify fund balances are correct")
        if not okx_funded and okx_balance is not None:
            print(f"   2. Transfer funds to OKX (current: ${okx_balance:.2f})")
        if not multi_broker_ok:
            print("   3. Enable multi-broker trading in .env")
        print(f"   4. Start NIJA bot with: ./start.sh")
        print("   5. Monitor logs to verify both brokers connect")
        
    elif kraken_ready:
        print("✅ KRAKEN IS READY FOR TRADING")
        if kraken_balance is not None:
            print(f"   💰 Balance: ${kraken_balance:.2f}")
        
        print("\n❌ OKX IS NOT READY")
        if not okx_creds_ok:
            print("   ⚠️  Configure OKX credentials in .env")
        if not okx_sdk_ok:
            print("   ⚠️  Install OKX SDK: pip install okx")
        if okx_creds_ok and okx_sdk_ok and not okx_conn_ok:
            print("   ⚠️  OKX connection failed - check credentials")
        
        print("\n📝 To Enable OKX:")
        print("   1. Get API credentials from https://www.okx.com/account/my-api")
        print("   2. Add to .env file:")
        print("      OKX_API_KEY=your_key")
        print("      OKX_API_SECRET=your_secret")
        print("      OKX_PASSPHRASE=your_passphrase")
        print("   3. Run this script again to validate")
        
    elif okx_ready:
        print("✅ OKX IS READY FOR TRADING")
        if okx_balance is not None:
            print(f"   💰 Balance: ${okx_balance:.2f}")
        
        print("\n❌ KRAKEN IS NOT READY")
        if not kraken_creds_ok:
            print("   ⚠️  Configure Kraken credentials in .env")
        if not kraken_sdk_ok:
            print("   ⚠️  Install Kraken SDK: pip install krakenex pykrakenapi")
        if kraken_creds_ok and kraken_sdk_ok and not kraken_conn_ok:
            print("   ⚠️  Kraken connection failed - check credentials")
        
        print("\n📝 To Enable Kraken:")
        print("   1. Get API credentials from https://www.kraken.com/u/security/api")
        print("   2. Add to .env file:")
        print("      KRAKEN_API_KEY=your_key")
        print("      KRAKEN_API_SECRET=your_secret")
        print("   3. Run this script again to validate")
        
    else:
        print("❌ NEITHER BROKER IS READY")
        print("\n📝 Setup Required:")
        
        if not kraken_ready:
            print("\n🟪 Kraken Setup:")
            if not kraken_creds_ok:
                print("   1. Get API credentials: https://www.kraken.com/u/security/api")
                print("   2. Add KRAKEN_API_KEY and KRAKEN_API_SECRET to .env")
            if not kraken_sdk_ok:
                print("   3. Install SDK: pip install krakenex pykrakenapi")
        
        if not okx_ready:
            print("\n⬛ OKX Setup:")
            if not okx_creds_ok:
                print("   1. Get API credentials: https://www.okx.com/account/my-api")
                print("   2. Add OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE to .env")
            if not okx_sdk_ok:
                print("   3. Install SDK: pip install okx")
        
        print("\n   4. Run this script again to validate")
    
    print("\n" + "=" * 80 + "\n")
    
    # Return exit code
    if kraken_ready and okx_ready:
        return 0
    elif kraken_ready or okx_ready:
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
