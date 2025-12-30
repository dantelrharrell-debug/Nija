#!/usr/bin/env python3
"""
Test OKX Exchange Connection

This script tests the OKX exchange integration by:
1. Connecting to OKX API (testnet or live)
2. Fetching account balance
3. Getting market data
4. Displaying connection status

Usage:
    python test_okx_connection.py
    
Environment Variables Required:
    OKX_API_KEY - Your OKX API key
    OKX_API_SECRET - Your OKX API secret
    OKX_PASSPHRASE - Your OKX API passphrase
    OKX_USE_TESTNET - 'true' for testnet, 'false' for live (optional)
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_broker_manager():
    """Test using broker_manager.py (recommended)"""
    print("=" * 70)
    print("TEST 1: OKX Integration via broker_manager.py")
    print("=" * 70)
    
    try:
        from broker_manager import OKXBroker
        
        # Initialize OKX broker
        broker = OKXBroker()
        
        # Test connection
        print("\n🔌 Connecting to OKX...")
        if broker.connect():
            print("✅ Successfully connected to OKX!")
            
            # Get balance
            print("\n💰 Fetching account balance...")
            balance = broker.get_account_balance()
            print(f"   USDT Balance: ${balance:.2f}")
            
            # Get positions
            print("\n📊 Fetching open positions...")
            positions = broker.get_positions()
            if positions:
                print(f"   Found {len(positions)} open positions:")
                for pos in positions:
                    print(f"   - {pos['symbol']}: {pos['quantity']:.4f} {pos['currency']}")
            else:
                print("   No open positions")
            
            # Test market data
            print("\n📈 Fetching market data for BTC-USDT...")
            candles = broker.get_candles('BTC-USDT', '5m', 10)
            if candles:
                print(f"   Fetched {len(candles)} candles")
                latest = candles[0]
                print(f"   Latest candle: O={latest['open']:.2f}, H={latest['high']:.2f}, "
                      f"L={latest['low']:.2f}, C={latest['close']:.2f}")
            else:
                print("   Failed to fetch candles")
            
            return True
        else:
            print("❌ Failed to connect to OKX")
            return False
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure OKX SDK is installed: pip install okx")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_broker_integration():
    """Test using broker_integration.py (adapter pattern)"""
    print("\n" + "=" * 70)
    print("TEST 2: OKX Integration via broker_integration.py")
    print("=" * 70)
    
    try:
        from broker_integration import BrokerFactory
        
        # Create OKX broker using factory
        print("\n🏭 Creating OKX broker adapter...")
        broker = BrokerFactory.create_broker('okx')
        
        # Test connection
        print("\n🔌 Connecting to OKX...")
        if broker.connect():
            print("✅ Successfully connected to OKX!")
            
            # Get balance
            print("\n💰 Fetching account balance...")
            balance_info = broker.get_account_balance()
            print(f"   Total Balance: ${balance_info['total_balance']:.2f}")
            print(f"   Available USDT: ${balance_info['available_balance']:.2f}")
            print(f"   Currency: {balance_info['currency']}")
            
            # Get market data
            print("\n📈 Fetching market data for BTC-USD...")
            market_data = broker.get_market_data('BTC-USD', '5m', 10)
            if market_data:
                candles = market_data['candles']
                print(f"   Fetched {len(candles)} candles for {market_data['symbol']}")
                if candles:
                    latest = candles[0]
                    print(f"   Latest: ${latest['close']:.2f} (Vol: {latest['volume']:.2f})")
            else:
                print("   Failed to fetch market data")
            
            # Get positions
            print("\n📊 Fetching open positions...")
            positions = broker.get_open_positions()
            if positions:
                print(f"   Found {len(positions)} positions:")
                for pos in positions:
                    print(f"   - {pos['symbol']}: {pos['size']:.4f}")
            else:
                print("   No open positions")
            
            return True
        else:
            print("❌ Failed to connect to OKX")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_credentials():
    """Check if OKX credentials are configured"""
    print("=" * 70)
    print("OKX CREDENTIAL CHECK")
    print("=" * 70)
    
    api_key = os.getenv("OKX_API_KEY")
    api_secret = os.getenv("OKX_API_SECRET")
    passphrase = os.getenv("OKX_PASSPHRASE")
    use_testnet = os.getenv("OKX_USE_TESTNET", "false")
    
    print(f"\n📋 Configuration Status:")
    print(f"   OKX_API_KEY: {'✅ Set' if api_key else '❌ Not set'}")
    print(f"   OKX_API_SECRET: {'✅ Set' if api_secret else '❌ Not set'}")
    print(f"   OKX_PASSPHRASE: {'✅ Set' if passphrase else '❌ Not set'}")
    print(f"   OKX_USE_TESTNET: {use_testnet}")
    
    if not api_key or not api_secret or not passphrase:
        print("\n⚠️  Missing credentials! Set these environment variables:")
        print("   export OKX_API_KEY='your_api_key'")
        print("   export OKX_API_SECRET='your_api_secret'")
        print("   export OKX_PASSPHRASE='your_passphrase'")
        print("\nOr add them to your .env file")
        print("\nGet credentials from: https://www.okx.com/account/my-api")
        return False
    
    return True


def main():
    """Run all tests"""
    print("\n" + "🔥" * 35)
    print("   OKX EXCHANGE INTEGRATION TEST")
    print("🔥" * 35 + "\n")
    
    # Check credentials first
    if not check_credentials():
        print("\n❌ Cannot proceed without valid credentials")
        sys.exit(1)
    
    # Run tests
    test1_passed = test_broker_manager()
    test2_passed = test_broker_integration()
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"   broker_manager.py: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"   broker_integration.py: {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    
    if test1_passed and test2_passed:
        print("\n✅ All tests passed! OKX integration is working correctly.")
        print("\nNext steps:")
        print("   1. Review the code in bot/broker_manager.py (OKXBroker class)")
        print("   2. Review the code in bot/broker_integration.py (OKXBrokerAdapter class)")
        print("   3. Update BROKER_INTEGRATION_GUIDE.md with OKX setup instructions")
        print("   4. Test placing small orders on testnet before going live")
    else:
        print("\n❌ Some tests failed. Check the error messages above.")
    
    print("=" * 70)


if __name__ == "__main__":
    main()
