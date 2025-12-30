#!/usr/bin/env python3
"""
Test script for Kraken Pro and Binance broker integrations.

This script tests the connection to Binance and Kraken exchanges
without executing any trades.

Usage:
    python test_broker_integrations.py
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import BinanceBroker, KrakenBroker, OKXBroker
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("nija.test")


def test_binance():
    """Test Binance broker connection"""
    print("\n" + "="*70)
    print("TESTING BINANCE BROKER")
    print("="*70 + "\n")
    
    binance = BinanceBroker()
    
    # Test connection
    if binance.connect():
        print("✅ Binance connection successful\n")
        
        # Test balance fetch
        try:
            balance = binance.get_account_balance()
            print(f"✅ Balance fetch successful: ${balance:.2f}\n")
        except Exception as e:
            print(f"❌ Balance fetch failed: {e}\n")
        
        # Test get positions
        try:
            positions = binance.get_positions()
            print(f"✅ Positions fetch successful: {len(positions)} position(s)\n")
            for pos in positions[:5]:  # Show first 5
                print(f"   {pos['symbol']}: {pos['quantity']}")
        except Exception as e:
            print(f"❌ Positions fetch failed: {e}\n")
        
        # Test get candles (BTC-USD)
        try:
            candles = binance.get_candles('BTC-USD', '5m', 5)
            print(f"\n✅ Candles fetch successful: {len(candles)} candle(s)")
            if candles:
                last_candle = candles[-1]
                print(f"   Latest BTC price: ${last_candle['close']:.2f}\n")
        except Exception as e:
            print(f"❌ Candles fetch failed: {e}\n")
    else:
        print("❌ Binance connection failed\n")
        print("Make sure you have set BINANCE_API_KEY and BINANCE_API_SECRET\n")


def test_kraken():
    """Test Kraken broker connection"""
    print("\n" + "="*70)
    print("TESTING KRAKEN BROKER")
    print("="*70 + "\n")
    
    kraken = KrakenBroker()
    
    # Test connection
    if kraken.connect():
        print("✅ Kraken connection successful\n")
        
        # Test balance fetch
        try:
            balance = kraken.get_account_balance()
            print(f"✅ Balance fetch successful: ${balance:.2f}\n")
        except Exception as e:
            print(f"❌ Balance fetch failed: {e}\n")
        
        # Test get positions
        try:
            positions = kraken.get_positions()
            print(f"✅ Positions fetch successful: {len(positions)} position(s)\n")
            for pos in positions[:5]:  # Show first 5
                print(f"   {pos['symbol']}: {pos['quantity']}")
        except Exception as e:
            print(f"❌ Positions fetch failed: {e}\n")
        
        # Test get candles (BTC-USD)
        try:
            candles = kraken.get_candles('BTC-USD', '5m', 5)
            print(f"\n✅ Candles fetch successful: {len(candles)} candle(s)")
            if candles:
                last_candle = candles[-1]
                print(f"   Latest BTC price: ${last_candle['close']:.2f}\n")
        except Exception as e:
            print(f"❌ Candles fetch failed: {e}\n")
    else:
        print("❌ Kraken connection failed\n")
        print("Make sure you have set KRAKEN_API_KEY and KRAKEN_API_SECRET\n")


def test_okx():
    """Test OKX broker connection (already implemented)"""
    print("\n" + "="*70)
    print("TESTING OKX BROKER (EXISTING)")
    print("="*70 + "\n")
    
    okx = OKXBroker()
    
    # Test connection
    if okx.connect():
        print("✅ OKX connection successful\n")
        
        # Test balance fetch
        try:
            balance = okx.get_account_balance()
            print(f"✅ Balance fetch successful: ${balance:.2f}\n")
        except Exception as e:
            print(f"❌ Balance fetch failed: {e}\n")
    else:
        print("❌ OKX connection failed\n")
        print("Make sure you have set OKX_API_KEY, OKX_API_SECRET, and OKX_PASSPHRASE\n")


def main():
    """Main test runner"""
    print("\n" + "="*70)
    print("NIJA MULTI-EXCHANGE BROKER INTEGRATION TEST")
    print("="*70)
    print("\nThis script tests connections to Binance, Kraken Pro, and OKX.")
    print("No trades will be executed.\n")
    print("Set the following environment variables to test each exchange:")
    print("  - Binance: BINANCE_API_KEY, BINANCE_API_SECRET")
    print("  - Kraken: KRAKEN_API_KEY, KRAKEN_API_SECRET")
    print("  - OKX: OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE")
    print("\n" + "="*70 + "\n")
    
    # Test each broker
    results = {
        'binance': False,
        'kraken': False,
        'okx': False
    }
    
    # Test Binance
    try:
        if os.getenv('BINANCE_API_KEY') and os.getenv('BINANCE_API_SECRET'):
            test_binance()
            results['binance'] = True
        else:
            print("\n⏭️  Skipping Binance test (credentials not set)\n")
    except Exception as e:
        print(f"\n❌ Binance test error: {e}\n")
    
    # Test Kraken
    try:
        if os.getenv('KRAKEN_API_KEY') and os.getenv('KRAKEN_API_SECRET'):
            test_kraken()
            results['kraken'] = True
        else:
            print("\n⏭️  Skipping Kraken test (credentials not set)\n")
    except Exception as e:
        print(f"\n❌ Kraken test error: {e}\n")
    
    # Test OKX
    try:
        if os.getenv('OKX_API_KEY') and os.getenv('OKX_API_SECRET') and os.getenv('OKX_PASSPHRASE'):
            test_okx()
            results['okx'] = True
        else:
            print("\n⏭️  Skipping OKX test (credentials not set)\n")
    except Exception as e:
        print(f"\n❌ OKX test error: {e}\n")
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70 + "\n")
    
    tested = sum(1 for v in results.values() if v)
    if tested == 0:
        print("❌ No brokers tested (missing credentials)")
    else:
        print(f"✅ Tested {tested} broker(s)")
        for broker, tested in results.items():
            if tested:
                print(f"   - {broker.capitalize()}: ✅ Tested")
    
    print("\n" + "="*70 + "\n")
    print("Next steps:")
    print("  1. Install dependencies: pip install -r requirements.txt")
    print("  2. Set up API credentials in .env file (copy from .env.example)")
    print("  3. Run this test script to verify connections")
    print("  4. Uncomment broker initialization in bot/apex_live_trading.py")
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    main()
