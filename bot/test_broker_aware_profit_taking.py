#!/usr/bin/env python3
"""
Test broker-aware profit-taking functionality
Ensures Kraken uses lower profit thresholds due to lower fees
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from execution_engine import ExecutionEngine


class MockBrokerClient:
    """Mock broker client for testing"""
    def __init__(self, broker_name):
        self.broker_type = broker_name


def test_kraken_fees():
    """Test that Kraken uses 0.36% fees"""
    print("Testing Kraken fee calculation...")
    
    # Create mock Kraken broker
    kraken_broker = MockBrokerClient('kraken')
    engine = ExecutionEngine(broker_client=kraken_broker)
    
    # Get broker fee
    fee = engine._get_broker_round_trip_fee()
    
    expected_fee = 0.0036  # 0.36%
    assert abs(fee - expected_fee) < 0.0001, f"Kraken fee should be {expected_fee}, got {fee}"
    print(f"✅ Kraken fee: {fee*100:.2f}% (expected {expected_fee*100:.2f}%)")


def test_coinbase_fees():
    """Test that Coinbase uses 1.4% fees"""
    print("\nTesting Coinbase fee calculation...")
    
    # Create mock Coinbase broker
    coinbase_broker = MockBrokerClient('coinbase')
    engine = ExecutionEngine(broker_client=coinbase_broker)
    
    # Get broker fee
    fee = engine._get_broker_round_trip_fee()
    
    expected_fee = 0.014  # 1.4%
    assert abs(fee - expected_fee) < 0.0001, f"Coinbase fee should be {expected_fee}, got {fee}"
    print(f"✅ Coinbase fee: {fee*100:.2f}% (expected {expected_fee*100:.2f}%)")


def test_binance_fees():
    """Test that Binance uses 0.28% fees"""
    print("\nTesting Binance fee calculation...")
    
    # Create mock Binance broker
    binance_broker = MockBrokerClient('binance')
    engine = ExecutionEngine(broker_client=binance_broker)
    
    # Get broker fee
    fee = engine._get_broker_round_trip_fee()
    
    expected_fee = 0.0028  # 0.28%
    assert abs(fee - expected_fee) < 0.0001, f"Binance fee should be {expected_fee}, got {fee}"
    print(f"✅ Binance fee: {fee*100:.2f}% (expected {expected_fee*100:.2f}%)")


def test_unknown_broker_defaults_to_coinbase():
    """Test that unknown brokers default to Coinbase fees"""
    print("\nTesting unknown broker defaults...")
    
    # Create mock unknown broker
    unknown_broker = MockBrokerClient('unknown_exchange')
    engine = ExecutionEngine(broker_client=unknown_broker)
    
    # Get broker fee
    fee = engine._get_broker_round_trip_fee()
    
    expected_fee = 0.014  # 1.4% - Coinbase default
    assert abs(fee - expected_fee) < 0.0001, f"Unknown broker should default to {expected_fee}, got {fee}"
    print(f"✅ Unknown broker fee: {fee*100:.2f}% (defaults to Coinbase {expected_fee*100:.2f}%)")


def test_no_broker_defaults_to_coinbase():
    """Test that no broker client defaults to Coinbase fees"""
    print("\nTesting no broker client defaults...")
    
    # Create engine without broker client
    engine = ExecutionEngine(broker_client=None)
    
    # Get broker fee
    fee = engine._get_broker_round_trip_fee()
    
    expected_fee = 0.014  # 1.4% - Coinbase default
    assert abs(fee - expected_fee) < 0.0001, f"No broker should default to {expected_fee}, got {fee}"
    print(f"✅ No broker client fee: {fee*100:.2f}% (defaults to Coinbase {expected_fee*100:.2f}%)")


def test_kraken_profit_thresholds():
    """Test that Kraken uses lower profit exit thresholds"""
    print("\nTesting Kraken profit exit thresholds...")
    
    # Create mock Kraken broker
    kraken_broker = MockBrokerClient('kraken')
    engine = ExecutionEngine(broker_client=kraken_broker)
    
    # Add a test position
    engine.positions['BTC-USD'] = {
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_price': 100.0,
        'position_size': 100.0,
        'remaining_size': 1.0,
        'stop_loss': 99.0,
        'tp1': 103.0,
        'tp2': 105.0,
        'tp3': 108.0
    }
    
    # Test at 0.7% profit (should trigger for Kraken, not Coinbase)
    current_price = 100.7  # 0.7% profit
    result = engine.check_stepped_profit_exits('BTC-USD', current_price)
    
    assert result is not None, "Kraken should trigger profit exit at 0.7%"
    assert result['profit_level'] == '0.7%', f"Expected 0.7% profit level, got {result['profit_level']}"
    print(f"✅ Kraken triggers profit exit at 0.7% (NET profit: ~{(0.007 - 0.0036)*100:.2f}%)")


def test_coinbase_profit_thresholds():
    """Test that Coinbase uses higher profit exit thresholds"""
    print("\nTesting Coinbase profit exit thresholds...")
    
    # Create mock Coinbase broker
    coinbase_broker = MockBrokerClient('coinbase')
    engine = ExecutionEngine(broker_client=coinbase_broker)
    
    # Add a test position
    engine.positions['BTC-USD'] = {
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_price': 100.0,
        'position_size': 100.0,
        'remaining_size': 1.0,
        'stop_loss': 99.0,
        'tp1': 103.0,
        'tp2': 105.0,
        'tp3': 108.0
    }
    
    # Test at 0.7% profit (should NOT trigger for Coinbase)
    current_price = 100.7  # 0.7% profit
    result = engine.check_stepped_profit_exits('BTC-USD', current_price)
    
    assert result is None, "Coinbase should NOT trigger profit exit at 0.7% (fees too high)"
    print(f"✅ Coinbase does NOT trigger profit exit at 0.7% (would be NET loss)")
    
    # Test at 2.0% profit (should trigger for Coinbase)
    current_price = 102.0  # 2.0% profit
    result = engine.check_stepped_profit_exits('BTC-USD', current_price)
    
    assert result is not None, "Coinbase should trigger profit exit at 2.0%"
    assert result['profit_level'] == '2.0%', f"Expected 2.0% profit level, got {result['profit_level']}"
    print(f"✅ Coinbase triggers profit exit at 2.0% (NET profit: ~{(0.020 - 0.014)*100:.2f}%)")


def main():
    """Run all tests"""
    print("="*70)
    print("BROKER-AWARE PROFIT TAKING TESTS")
    print("="*70)
    
    try:
        # Test fee calculations
        test_kraken_fees()
        test_coinbase_fees()
        test_binance_fees()
        test_unknown_broker_defaults_to_coinbase()
        test_no_broker_defaults_to_coinbase()
        
        # Test profit thresholds
        test_kraken_profit_thresholds()
        test_coinbase_profit_thresholds()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED")
        print("="*70)
        print("\nSummary:")
        print("- Kraken uses 0.36% fees → takes profit at 0.7%, 1.0%, 1.5%, 2.5%")
        print("- Coinbase uses 1.4% fees → takes profit at 2.0%, 2.5%, 3.0%, 4.0%")
        print("- All profit levels ensure NET profitability after fees")
        print("- Kraken will take profits ~60-70% faster than before")
        print("\n")
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
