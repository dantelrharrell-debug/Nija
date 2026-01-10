#!/usr/bin/env python3
"""
Quick Status Check: Is User #1 Trading on Kraken?

This script provides a fast answer to whether User #1 (Daivon Frazier)
is currently configured and trading on Kraken.

Usage:
    python3 check_user1_kraken_status_now.py
"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def check_sdk_installed():
    """Check if Kraken SDK is installed."""
    try:
        import krakenex
        import pykrakenapi
        return True
    except ImportError:
        return False


def check_credentials_configured():
    """Check if User #1 Kraken credentials are set."""
    api_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "").strip()
    api_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "").strip()
    return bool(api_key and api_secret)


def check_can_connect():
    """Test if we can connect to Kraken with User #1 credentials."""
    if not check_sdk_installed():
        return False, "SDK not installed"
    
    if not check_credentials_configured():
        return False, "Credentials not configured"
    
    try:
        import krakenex
        
        api_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "").strip()
        api_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "").strip()
        
        api = krakenex.API(key=api_key, secret=api_secret)
        balance = api.query_private('Balance')
        
        if balance and 'error' in balance and balance['error']:
            error_msgs = ', '.join(balance['error'])
            return False, f"API error: {error_msgs}"
        
        if balance and 'result' in balance:
            result = balance.get('result', {})
            usd = float(result.get('ZUSD', 0))
            usdt = float(result.get('USDT', 0))
            total = usd + usdt
            return True, f"Connected (Balance: ${total:.2f})"
        
        return False, "Unexpected API response"
        
    except Exception as e:
        return False, f"Connection error: {str(e)[:100]}"


def main():
    """Run quick status check."""
    print("=" * 80)
    print("QUICK STATUS CHECK: User #1 Kraken Trading")
    print("=" * 80)
    print()
    print("User: Daivon Frazier (daivon_frazier)")
    print("Broker: Kraken Pro")
    print()
    print("-" * 80)
    
    # Check 1: SDK
    sdk_ok = check_sdk_installed()
    print(f"Kraken SDK: {'✅ Installed' if sdk_ok else '❌ Not installed'}")
    
    # Check 2: Credentials
    creds_ok = check_credentials_configured()
    if creds_ok:
        print(f"Credentials: ✅ Configured")
        api_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "")
        print(f"  API Key: {len(api_key)} characters")
    else:
        print(f"Credentials: ❌ Not configured")
    
    # Check 3: Connection
    if sdk_ok and creds_ok:
        can_connect, msg = check_can_connect()
        print(f"Connection: {'✅' if can_connect else '❌'} {msg}")
    else:
        print(f"Connection: ⏭️  Skipped (prerequisites not met)")
        can_connect = False
    
    print("-" * 80)
    print()
    
    # Final answer
    if sdk_ok and creds_ok and can_connect:
        print("=" * 80)
        print("✅ ANSWER: User #1 CAN trade on Kraken")
        print("=" * 80)
        print()
        print("Prerequisites are met. If the bot is running with")
        print("MULTI_BROKER_INDEPENDENT=true, User #1 should be trading.")
        print()
        print("Check bot logs for:")
        print("  ✅ User #1 Kraken connected")
        print("  ✅ USER #1 (Daivon Frazier): TRADING (Broker: Kraken)")
        print("  🚀 Started independent trading thread for daivon_frazier_kraken")
        print()
        return 0
    else:
        print("=" * 80)
        print("❌ ANSWER: User #1 CANNOT trade on Kraken")
        print("=" * 80)
        print()
        print("Missing prerequisites:")
        if not sdk_ok:
            print("  ❌ Kraken SDK not installed")
            print("     Install: pip install krakenex==2.2.2 pykrakenapi==0.3.2")
        if not creds_ok:
            print("  ❌ Credentials not configured")
            print("     Set: KRAKEN_USER_DAIVON_API_KEY")
            print("     Set: KRAKEN_USER_DAIVON_API_SECRET")
        if sdk_ok and creds_ok and not can_connect:
            print("  ❌ Cannot connect to Kraken")
            print("     Check API key validity and permissions")
        print()
        print("Fix the issues above, then restart the bot.")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
