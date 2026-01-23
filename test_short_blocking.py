#!/usr/bin/env python3
"""
Test SHORT blocking for Kraken spot markets

This script verifies that:
1. SHORT entries are blocked on Kraken spot markets (BTC-USD, ETH-USD)
2. SHORT entries are allowed on Kraken futures (BTC-PERP, ETH-PERP)
3. SHORT entries are blocked on Coinbase (all symbols)
4. SHORT entries are allowed on Alpaca (stocks)

Note: Run from repository root:
    python test_short_blocking.py
"""

import sys
import os

# Import from bot package
try:
    from bot.exchange_capabilities import can_short, EXCHANGE_CAPABILITIES
except ImportError:
    # If not installed as package, try relative import
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    from exchange_capabilities import can_short, EXCHANGE_CAPABILITIES


def test_kraken_spot():
    """Test that Kraken spot markets block SHORT"""
    print("\n" + "="*70)
    print("TEST 1: Kraken Spot Markets (Should Block SHORT)")
    print("="*70)
    
    test_cases = [
        ('kraken', 'BTC-USD', False),
        ('kraken', 'ETH-USD', False),
        ('kraken', 'SOL-USD', False),
        ('kraken', 'DOGE-USD', False),
    ]
    
    passed = 0
    failed = 0
    
    for broker, symbol, expected in test_cases:
        result = can_short(broker, symbol)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} | {broker:10} | {symbol:15} | Expected: {str(expected):5} | Got: {str(result):5}")
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_kraken_futures():
    """Test that Kraken futures/perpetuals allow SHORT"""
    print("\n" + "="*70)
    print("TEST 2: Kraken Futures/Perpetuals (Should Allow SHORT)")
    print("="*70)
    
    test_cases = [
        ('kraken', 'BTC-PERP', True),
        ('kraken', 'ETH-PERP', True),
        ('kraken', 'BTCUSD-PERP', True),
        ('kraken', 'BTC-FUTURE', True),
    ]
    
    passed = 0
    failed = 0
    
    for broker, symbol, expected in test_cases:
        result = can_short(broker, symbol)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} | {broker:10} | {symbol:15} | Expected: {str(expected):5} | Got: {str(result):5}")
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_coinbase():
    """Test that Coinbase blocks SHORT on all markets"""
    print("\n" + "="*70)
    print("TEST 3: Coinbase Markets (Should Block SHORT)")
    print("="*70)
    
    test_cases = [
        ('coinbase', 'BTC-USD', False),
        ('coinbase', 'ETH-USD', False),
        ('coinbase', 'SOL-USD', False),
    ]
    
    passed = 0
    failed = 0
    
    for broker, symbol, expected in test_cases:
        result = can_short(broker, symbol)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} | {broker:10} | {symbol:15} | Expected: {str(expected):5} | Got: {str(result):5}")
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_binance():
    """Test that Binance spot blocks SHORT but futures allow it"""
    print("\n" + "="*70)
    print("TEST 4: Binance Markets (Spot NO, Futures YES)")
    print("="*70)
    
    test_cases = [
        ('binance', 'BTC-USDT', False),  # Spot
        ('binance', 'ETH-USDT', False),  # Spot
        ('binance', 'BTCUSDT-PERP', True),  # Perpetual
        ('binance', 'ETHUSDT-PERP', True),  # Perpetual
    ]
    
    passed = 0
    failed = 0
    
    for broker, symbol, expected in test_cases:
        result = can_short(broker, symbol)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} | {broker:10} | {symbol:15} | Expected: {str(expected):5} | Got: {str(result):5}")
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_alpaca():
    """Test that Alpaca allows SHORT (stocks)"""
    print("\n" + "="*70)
    print("TEST 5: Alpaca Stocks (Should Allow SHORT)")
    print("="*70)
    
    test_cases = [
        ('alpaca', 'AAPL', True),
        ('alpaca', 'TSLA', True),
        ('alpaca', 'SPY', True),
    ]
    
    passed = 0
    failed = 0
    
    for broker, symbol, expected in test_cases:
        result = can_short(broker, symbol)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} | {broker:10} | {symbol:15} | Expected: {str(expected):5} | Got: {str(result):5}")
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_capability_summaries():
    """Print capability summaries for all brokers"""
    print("\n" + "="*70)
    print("EXCHANGE CAPABILITY SUMMARIES")
    print("="*70)
    
    for broker in ['kraken', 'coinbase', 'binance']:
        print(EXCHANGE_CAPABILITIES.get_summary(broker))


if __name__ == "__main__":
    print("\n" + "="*70)
    print("TESTING SHORT ENTRY BLOCKING")
    print("="*70)
    
    all_passed = True
    
    all_passed &= test_kraken_spot()
    all_passed &= test_kraken_futures()
    all_passed &= test_coinbase()
    all_passed &= test_binance()
    all_passed &= test_alpaca()
    
    test_capability_summaries()
    
    print("\n" + "="*70)
    print("FINAL RESULT")
    print("="*70)
    
    if all_passed:
        print("✅ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
