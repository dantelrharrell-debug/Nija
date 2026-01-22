#!/usr/bin/env python3
"""
Test script for Kraken adapter module.

Tests:
1. Symbol normalization for various formats
2. Dust position detection
3. Position reconciliation (without actual API calls)
"""

import sys
import os

# Add bot directory to path
bot_dir = os.path.join(os.path.dirname(__file__), 'bot')
sys.path.insert(0, bot_dir)

# Import directly from kraken_adapter module file
import importlib.util
spec = importlib.util.spec_from_file_location("kraken_adapter", os.path.join(bot_dir, "kraken_adapter.py"))
kraken_adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kraken_adapter)

# Get functions from module
normalize_symbol = kraken_adapter.normalize_symbol
normalize_kraken_symbol = kraken_adapter.normalize_kraken_symbol
normalize_coinbase_symbol = kraken_adapter.normalize_coinbase_symbol
is_dust_position = kraken_adapter.is_dust_position
should_track_position = kraken_adapter.should_track_position
KRAKEN_SYMBOL_MAP = kraken_adapter.KRAKEN_SYMBOL_MAP
DUST_THRESHOLD_USD = kraken_adapter.DUST_THRESHOLD_USD
KrakenPositionReconciler = kraken_adapter.KrakenPositionReconciler

def test_symbol_normalization():
    """Test symbol normalization for Kraken and Coinbase."""
    print("=" * 70)
    print("TEST: Symbol Normalization")
    print("=" * 70)
    
    test_cases = [
        # (input_symbol, broker, expected_output)
        ("ETH-USD", "kraken", "ETHUSD"),
        ("BTC-USD", "kraken", "BTCUSD"),
        ("SOL-USD", "kraken", "SOLUSD"),
        ("ETH/USD", "kraken", "ETHUSD"),
        ("BTC/USD", "kraken", "BTCUSD"),
        ("XRP-USD", "kraken", "XRPUSD"),
        ("ADA-USD", "kraken", "ADAUSD"),
        
        ("ETHUSD", "coinbase", "ETH-USD"),
        ("BTCUSD", "coinbase", "BTC-USD"),
        ("SOL/USD", "coinbase", "SOL-USD"),
    ]
    
    passed = 0
    failed = 0
    
    for input_symbol, broker, expected in test_cases:
        result = normalize_symbol(input_symbol, broker)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} | {broker:10} | {input_symbol:12} → {result:12} (expected: {expected})")
    
    print("-" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print()
    
    return failed == 0


def test_dust_detection():
    """Test dust position detection."""
    print("=" * 70)
    print("TEST: Dust Position Detection")
    print("=" * 70)
    print(f"Dust threshold: ${DUST_THRESHOLD_USD}")
    print()
    
    test_cases = [
        # (usd_value, expected_is_dust)
        (0.01, True),
        (0.50, True),
        (0.99, True),
        (1.00, False),
        (1.01, False),
        (10.00, False),
        (100.00, False),
    ]
    
    passed = 0
    failed = 0
    
    for usd_value, expected_is_dust in test_cases:
        result = is_dust_position(usd_value)
        should_track = should_track_position(usd_value)
        status = "✅ PASS" if result == expected_is_dust else "❌ FAIL"
        
        if result == expected_is_dust:
            passed += 1
        else:
            failed += 1
        
        dust_str = "DUST" if result else "TRACK"
        track_str = "NO" if result else "YES"
        print(f"{status} | ${usd_value:6.2f} → {dust_str:5} | Track: {track_str}")
    
    print("-" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print()
    
    return failed == 0


def test_position_reconciler():
    """Test position reconciler (without actual API calls)."""
    print("=" * 70)
    print("TEST: Position Reconciler")
    print("=" * 70)
    
    # Test filter_dust_positions
    reconciler = KrakenPositionReconciler()
    
    test_positions = [
        {'symbol': 'ETH-USD', 'size': 0.001, 'usd_value': 0.50},  # Dust
        {'symbol': 'BTC-USD', 'size': 0.0001, 'usd_value': 0.80},  # Dust
        {'symbol': 'SOL-USD', 'size': 10.0, 'usd_value': 100.00},  # Not dust
        {'symbol': 'XRP-USD', 'size': 100.0, 'usd_value': 50.00},  # Not dust
        {'symbol': 'ADA-USD', 'size': 5.0, 'usd_value': 1.50},  # Not dust
    ]
    
    print(f"Input positions: {len(test_positions)}")
    for pos in test_positions:
        print(f"  • {pos['symbol']}: ${pos['usd_value']:.2f}")
    
    filtered = reconciler.filter_dust_positions(test_positions)
    
    print()
    print(f"After filtering: {len(filtered)} positions")
    for pos in filtered:
        print(f"  • {pos['symbol']}: ${pos['usd_value']:.2f}")
    
    print()
    expected_count = 3  # Should filter out 2 dust positions
    status = "✅ PASS" if len(filtered) == expected_count else "❌ FAIL"
    print(f"{status} | Expected {expected_count} positions, got {len(filtered)}")
    print()
    
    return len(filtered) == expected_count


def test_kraken_symbol_map():
    """Test that KRAKEN_SYMBOL_MAP contains expected pairs."""
    print("=" * 70)
    print("TEST: Kraken Symbol Map")
    print("=" * 70)
    
    required_pairs = [
        "ETH-USD",
        "BTC-USD",
        "SOL-USD",
        "ETH/USD",
        "BTC/USD",
        "SOL/USD",
    ]
    
    passed = 0
    failed = 0
    
    for pair in required_pairs:
        if pair in KRAKEN_SYMBOL_MAP:
            passed += 1
            print(f"✅ PASS | {pair:12} → {KRAKEN_SYMBOL_MAP[pair]}")
        else:
            failed += 1
            print(f"❌ FAIL | {pair:12} NOT FOUND")
    
    print("-" * 70)
    print(f"Total pairs in map: {len(KRAKEN_SYMBOL_MAP)}")
    print(f"Results: {passed} passed, {failed} failed")
    print()
    
    return failed == 0


def main():
    """Run all tests."""
    print()
    print("=" * 70)
    print("KRAKEN ADAPTER MODULE TESTS")
    print("=" * 70)
    print()
    
    all_passed = True
    
    # Run tests
    all_passed &= test_kraken_symbol_map()
    all_passed &= test_symbol_normalization()
    all_passed &= test_dust_detection()
    all_passed &= test_position_reconciler()
    
    # Summary
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    if all_passed:
        print("✅ ALL TESTS PASSED")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
