#!/usr/bin/env python3
"""
Enable Kraken Trading - Setup Script

This script helps enable Kraken trading on NIJA by:
1. Checking if Kraken SDK is installed
2. Checking if Kraken API credentials are set
3. Testing the Kraken connection
4. Providing next steps

Usage:
    python3 enable_kraken_trading.py
"""

import os
import sys

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, env vars should be set externally

def check_sdk_installed():
    """Check if Kraken SDK dependencies are installed."""
    print("=" * 70)
    print("STEP 1: Checking Kraken SDK Installation")
    print("=" * 70)
    
    try:
        import krakenex
        print("✅ krakenex installed (version: {})".format(krakenex.__version__ if hasattr(krakenex, '__version__') else 'unknown'))
    except ImportError:
        print("❌ krakenex not installed")
        print("   Run: pip install krakenex==2.2.2")
        return False
    
    try:
        import pykrakenapi
        print("✅ pykrakenapi installed")
    except ImportError:
        print("❌ pykrakenapi not installed")
        print("   Run: pip install pykrakenapi==0.3.2")
        return False
    
    print("\n✅ All SDK dependencies installed\n")
    return True


def check_credentials():
    """Check if Kraken API credentials are set."""
    print("=" * 70)
    print("STEP 2: Checking Kraken API Credentials")
    print("=" * 70)
    
    api_key = os.getenv("KRAKEN_API_KEY", "").strip()
    api_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
    
    if not api_key:
        print("❌ KRAKEN_API_KEY not set")
        print("\n📝 To set Kraken API credentials:")
        print("\n   Option A: Using .env file (recommended)")
        print("   1. Open or create .env file in the repository root")
        print("   2. Add the following lines:")
        print("      KRAKEN_API_KEY=your_api_key_here")
        print("      KRAKEN_API_SECRET=your_api_secret_here")
        print("\n   Option B: Using environment variables (Railway/production)")
        print("   1. Go to your Railway dashboard")
        print("   2. Navigate to Variables")
        print("   3. Add:")
        print("      - KRAKEN_API_KEY")
        print("      - KRAKEN_API_SECRET")
        print("\n   Option C: Using export command (temporary)")
        print("   export KRAKEN_API_KEY=\"your_api_key_here\"")
        print("   export KRAKEN_API_SECRET=\"your_api_secret_here\"")
        print("\n🔑 Get Kraken API credentials from:")
        print("   https://www.kraken.com/u/security/api")
        print("\n⚠️  Required permissions:")
        print("   - Query Funds")
        print("   - Query Open Orders & Trades")
        print("   - Query Closed Orders & Trades")
        print("   - Create & Modify Orders")
        print()
        return False
    
    if not api_secret:
        print("❌ KRAKEN_API_SECRET not set")
        return False
    
    print("✅ KRAKEN_API_KEY set ({} characters)".format(len(api_key)))
    print("✅ KRAKEN_API_SECRET set ({} characters)".format(len(api_secret)))
    print("\n✅ Credentials configured\n")
    return True


def test_connection():
    """Test Kraken API connection."""
    print("=" * 70)
    print("STEP 3: Testing Kraken Connection")
    print("=" * 70)
    
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        import time
        
        api_key = os.getenv("KRAKEN_API_KEY", "").strip()
        api_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
        
        if not api_key or not api_secret:
            print("⚠️  Skipping connection test (credentials not set)")
            return False
        
        print("🔄 Connecting to Kraken API...")
        
        # Initialize Kraken API
        api = krakenex.API(key=api_key, secret=api_secret)
        kraken_api = KrakenAPI(api)
        
        # Test connection with retry logic
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    delay = 5
                    print(f"   Retry attempt {attempt}/{max_attempts} in {delay}s...")
                    time.sleep(delay)
                
                # Query balance to test connection
                balance = api.query_private('Balance')
                
                if balance and 'error' in balance and balance['error']:
                    error_msgs = ', '.join(balance['error'])
                    print(f"❌ Connection failed: {error_msgs}")
                    if attempt < max_attempts:
                        continue
                    return False
                
                if balance and 'result' in balance:
                    print("✅ Successfully connected to Kraken!")
                    print("\n" + "=" * 70)
                    print("KRAKEN ACCOUNT BALANCE")
                    print("=" * 70)
                    
                    result = balance.get('result', {})
                    usd_balance = float(result.get('ZUSD', 0))  # Kraken uses ZUSD for USD
                    usdt_balance = float(result.get('USDT', 0))
                    
                    print(f"USD Balance:  ${usd_balance:.2f}")
                    print(f"USDT Balance: ${usdt_balance:.2f}")
                    print(f"Total:        ${usd_balance + usdt_balance:.2f}")
                    print("=" * 70)
                    
                    if usd_balance + usdt_balance < 10:
                        print("\n⚠️  WARNING: Low balance detected")
                        print("   Minimum recommended: $100 USD")
                        print("   For effective trading: $500+ USD")
                    
                    print()
                    return True
                else:
                    print(f"❌ No balance data returned (attempt {attempt}/{max_attempts})")
                    if attempt < max_attempts:
                        continue
                    return False
            
            except Exception as e:
                error_msg = str(e)
                print(f"❌ Connection error (attempt {attempt}/{max_attempts}): {error_msg}")
                
                if attempt < max_attempts:
                    continue
                
                # Check for specific error types
                error_lower = error_msg.lower()
                if 'api' in error_lower and ('key' in error_lower or 'signature' in error_lower):
                    print("\n💡 Troubleshooting:")
                    print("   - Verify API key and secret are correct")
                    print("   - Check that API key has required permissions")
                    print("   - Ensure API key is not expired")
                elif 'connection' in error_lower or 'network' in error_lower:
                    print("\n💡 Troubleshooting:")
                    print("   - Check your internet connection")
                    print("   - Verify Kraken API is accessible")
                    print("   - Try again in a few minutes")
                
                return False
        
        return False
        
    except ImportError as e:
        print(f"❌ SDK import error: {e}")
        print("   Run: pip install krakenex pykrakenapi")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


def main():
    """Main setup script."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  NIJA - Enable Kraken Trading Setup".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    # Step 1: Check SDK
    sdk_installed = check_sdk_installed()
    if not sdk_installed:
        print("\n❌ SETUP INCOMPLETE: Install Kraken SDK first")
        print("   Run: pip install -r requirements.txt")
        sys.exit(1)
    
    # Step 2: Check credentials
    credentials_set = check_credentials()
    if not credentials_set:
        print("\n❌ SETUP INCOMPLETE: Set Kraken API credentials")
        print("   See instructions above")
        sys.exit(1)
    
    # Step 3: Test connection
    connection_ok = test_connection()
    if not connection_ok:
        print("\n⚠️  SETUP INCOMPLETE: Connection test failed")
        print("   Review error messages above and try again")
        sys.exit(1)
    
    # Success!
    print("\n" + "=" * 70)
    print("✅ KRAKEN TRADING ENABLED!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("1. Restart the trading bot:")
    print("   ./start.sh")
    print()
    print("2. Verify Kraken is connected:")
    print("   python3 check_broker_status.py")
    print()
    print("3. Check trading activity:")
    print("   python3 check_trading_status.py")
    print()
    print("4. Monitor logs for Kraken activity:")
    print("   Look for: 'kraken: Running trading cycle...'")
    print()
    print("The bot will now trade on BOTH Coinbase and Kraken simultaneously!")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
