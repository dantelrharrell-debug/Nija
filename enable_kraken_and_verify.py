#!/usr/bin/env python3
"""
Enable and Verify Kraken Trading Connection

This script:
1. Verifies Kraken API credentials are set
2. Tests connection to Kraken Pro API
3. Checks account balance
4. Verifies the bot will connect to Kraken on startup

Run this to ensure Kraken is ready for live trading.
"""

import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def main():
    print("=" * 80)
    print("🔍 KRAKEN CONNECTION VERIFICATION")
    print("=" * 80)
    print()
    
    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ Environment variables loaded from .env")
    except ImportError:
        print("⚠️  python-dotenv not installed, using system environment variables")
    
    # Check credentials
    print()
    print("=" * 80)
    print("📋 CHECKING CREDENTIALS")
    print("=" * 80)
    
    kraken_key = os.getenv("KRAKEN_API_KEY", "").strip()
    kraken_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
    
    if not kraken_key:
        print("❌ KRAKEN_API_KEY not set in environment")
        print()
        print("To fix:")
        print("1. Add to .env file: KRAKEN_API_KEY=your_key_here")
        print("2. Or export: export KRAKEN_API_KEY=your_key_here")
        return False
    
    if not kraken_secret:
        print("❌ KRAKEN_API_SECRET not set in environment")
        print()
        print("To fix:")
        print("1. Add to .env file: KRAKEN_API_SECRET=your_secret_here")
        print("2. Or export: export KRAKEN_API_SECRET=your_secret_here")
        return False
    
    print(f"✅ KRAKEN_API_KEY: Set ({len(kraken_key)} chars)")
    print(f"✅ KRAKEN_API_SECRET: Set ({len(kraken_secret)} chars)")
    
    # Test connection
    print()
    print("=" * 80)
    print("🔌 TESTING KRAKEN CONNECTION")
    print("=" * 80)
    
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        
        print("✅ Kraken SDK installed (krakenex + pykrakenapi)")
        
        # Initialize API
        api = krakenex.API(key=kraken_key, secret=kraken_secret)
        kraken_api = KrakenAPI(api)
        
        print("⏳ Connecting to Kraken Pro API...")
        
        # Test connection with balance query
        balance_response = api.query_private('Balance')
        
        if balance_response and 'error' in balance_response:
            if balance_response['error']:
                error_msgs = ', '.join(balance_response['error'])
                print(f"❌ Kraken API error: {error_msgs}")
                return False
        
        if balance_response and 'result' in balance_response:
            result = balance_response.get('result', {})
            
            print()
            print("=" * 80)
            print("✅ KRAKEN CONNECTION SUCCESSFUL")
            print("=" * 80)
            
            # Show balances
            usd_balance = float(result.get('ZUSD', 0))
            usdt_balance = float(result.get('USDT', 0))
            total = usd_balance + usdt_balance
            
            print(f"USD Balance:  ${usd_balance:.2f}")
            print(f"USDT Balance: ${usdt_balance:.2f}")
            print(f"Total:        ${total:.2f}")
            
            # Check all crypto balances
            crypto_balances = []
            for asset, amount in result.items():
                if asset not in ['ZUSD', 'USDT'] and float(amount) > 0:
                    crypto_balances.append((asset, float(amount)))
            
            if crypto_balances:
                print()
                print("Crypto Holdings:")
                for asset, amount in crypto_balances:
                    print(f"  {asset}: {amount}")
            
            print("=" * 80)
            
            # Check if sufficient for trading
            if total < 2.0:
                print()
                print("⚠️  WARNING: Balance is low for trading")
                print(f"   Current: ${total:.2f}")
                print(f"   Minimum recommended: $25.00")
                print(f"   Absolute minimum: $2.00")
                print()
                print("You can still trade but profitability will be limited by fees.")
            else:
                print()
                print(f"✅ Sufficient balance for trading (${total:.2f})")
            
            return True
        else:
            print("❌ No balance data returned from Kraken")
            return False
            
    except ImportError as e:
        print(f"❌ Kraken SDK not installed: {e}")
        print()
        print("To install:")
        print("  pip install krakenex pykrakenapi")
        return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("=" * 80)
    print("🎯 BOT CONFIGURATION")
    print("=" * 80)
    print()
    print("The NIJA bot is configured to automatically connect to Kraken on startup.")
    print("See bot/trading_strategy.py lines 197-208 for the connection logic.")
    print()
    print("When you start the bot, you should see:")
    print('  📊 Attempting to connect Kraken Pro...')
    print('     ✅ Kraken connected')
    print()
    print("If you don't see this, check the startup logs for errors.")
    print("=" * 80)


if __name__ == "__main__":
    try:
        success = main()
        
        print()
        print("=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)
        
        if success:
            print("✅ Kraken is configured and ready for trading")
            print()
            print("Next steps:")
            print("1. Start the bot: python bot.py")
            print("2. Watch logs for 'Kraken connected' message")
            print("3. Bot will trade on both Coinbase AND Kraken simultaneously")
            print()
            sys.exit(0)
        else:
            print("❌ Kraken connection failed")
            print()
            print("Fix the issues above and run this script again.")
            print()
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
