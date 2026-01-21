"""
Test script for broker-specific order validation

Tests the new execute_order method with:
1. Symbol support validation
2. EXIT-ONLY mode validation
3. Minimum trade size validation
"""

import sys
sys.path.insert(0, '.')

from bot.broker_manager import BaseBroker, BrokerType


class MockBroker(BaseBroker):
    """Mock broker for testing"""
    
    def connect(self):
        return True
    
    def get_account_balance(self):
        return 100.0
    
    def get_positions(self):
        return []
    
    def place_market_order(self, symbol, side, quantity, size_type='quote', 
                          ignore_balance=False, ignore_min_trade=False, force_liquidate=False):
        return {
            'status': 'filled',
            'order_id': 'test-order-123',
            'symbol': symbol,
            'side': side,
            'quantity': quantity
        }


def test_symbol_validation():
    """Test symbol support validation"""
    print("=" * 70)
    print("TEST 1: Symbol Support Validation")
    print("=" * 70)
    
    # Test 1a: Coinbase does not support BUSD
    cb = MockBroker(BrokerType.COINBASE)
    result = cb.execute_order('ETH-BUSD', 'buy', 10.0, 'quote')
    
    assert result['status'] == 'skipped', "Should skip unsupported symbol"
    assert result['error'] == 'UNSUPPORTED_SYMBOL', "Should have UNSUPPORTED_SYMBOL error"
    print(f"✅ Test 1a PASSED: Coinbase correctly rejected BUSD pair")
    print(f"   Result: {result}")
    
    # Test 1b: Coinbase supports USD
    result = cb.execute_order('ETH-USD', 'buy', 10.0, 'quote')
    assert result['status'] == 'filled', "Should execute supported symbol"
    print(f"✅ Test 1b PASSED: Coinbase correctly accepted USD pair")
    print(f"   Result: {result}")
    
    # Test 1c: Kraken does not support BUSD
    kr = MockBroker(BrokerType.KRAKEN)
    result = kr.execute_order('BTC-BUSD', 'buy', 10.0, 'quote')
    
    assert result['status'] == 'skipped', "Should skip unsupported symbol"
    assert result['error'] == 'UNSUPPORTED_SYMBOL', "Should have UNSUPPORTED_SYMBOL error"
    print(f"✅ Test 1c PASSED: Kraken correctly rejected BUSD pair")
    print(f"   Result: {result}")
    
    print()


def test_exit_only_mode():
    """Test EXIT-ONLY mode validation"""
    print("=" * 70)
    print("TEST 2: EXIT-ONLY Mode Validation")
    print("=" * 70)
    
    cb = MockBroker(BrokerType.COINBASE)
    cb.exit_only_mode = True
    
    # Test 2a: BUY should be blocked in exit-only mode
    result = cb.execute_order('BTC-USD', 'buy', 10.0, 'quote')
    
    assert result['status'] == 'skipped', "Should skip BUY in exit-only mode"
    assert result['error'] == 'EXIT_ONLY_MODE', "Should have EXIT_ONLY_MODE error"
    print(f"✅ Test 2a PASSED: BUY correctly blocked in exit-only mode")
    print(f"   Result: {result}")
    
    # Test 2b: SELL should be allowed in exit-only mode
    result = cb.execute_order('BTC-USD', 'sell', 10.0, 'quote')
    
    assert result['status'] == 'filled', "Should execute SELL in exit-only mode"
    print(f"✅ Test 2b PASSED: SELL correctly allowed in exit-only mode")
    print(f"   Result: {result}")
    
    # Test 2c: force_liquidate should override exit-only mode
    result = cb.execute_order('BTC-USD', 'buy', 10.0, 'quote', force_liquidate=True)
    
    assert result['status'] == 'filled', "Should execute with force_liquidate"
    print(f"✅ Test 2c PASSED: force_liquidate correctly overrides exit-only mode")
    print(f"   Result: {result}")
    
    print()


def test_minimum_trade_size():
    """Test minimum trade size validation"""
    print("=" * 70)
    print("TEST 3: Minimum Trade Size Validation")
    print("=" * 70)
    
    cb = MockBroker(BrokerType.COINBASE)
    
    # Test 3a: Trade below minimum should be blocked
    result = cb.execute_order('BTC-USD', 'buy', 3.0, 'quote')
    
    assert result['status'] == 'skipped', "Should skip trade below minimum"
    assert result['error'] == 'TRADE_SIZE_TOO_SMALL', "Should have TRADE_SIZE_TOO_SMALL error"
    print(f"✅ Test 3a PASSED: Trade below $5 minimum correctly blocked")
    print(f"   Result: {result}")
    
    # Test 3b: Trade at minimum should execute (with warning)
    print(f"\n   Testing trade at minimum ($5)...")
    result = cb.execute_order('BTC-USD', 'buy', 5.0, 'quote')
    
    assert result['status'] == 'filled', "Should execute trade at minimum"
    print(f"✅ Test 3b PASSED: Trade at $5 minimum correctly executed")
    print(f"   Result: {result}")
    
    # Test 3c: Trade above warning threshold should execute without warning
    result = cb.execute_order('BTC-USD', 'buy', 15.0, 'quote')
    
    assert result['status'] == 'filled', "Should execute trade above warning threshold"
    print(f"✅ Test 3c PASSED: Trade above $10 warning threshold correctly executed")
    print(f"   Result: {result}")
    
    # Test 3d: ignore_min_trade should override minimum
    result = cb.execute_order('BTC-USD', 'buy', 2.0, 'quote', ignore_min_trade=True)
    
    assert result['status'] == 'filled', "Should execute with ignore_min_trade"
    print(f"✅ Test 3d PASSED: ignore_min_trade correctly overrides minimum")
    print(f"   Result: {result}")
    
    print()


def test_broker_specific_minimums():
    """Test broker-specific minimum trade sizes"""
    print("=" * 70)
    print("TEST 4: Broker-Specific Minimum Trade Sizes")
    print("=" * 70)
    
    # Test 4a: Coinbase minimum
    cb = MockBroker(BrokerType.COINBASE)
    print(f"   Coinbase min_trade_size: ${cb.min_trade_size:.2f}")
    print(f"   Coinbase warn_trade_size: ${cb.warn_trade_size:.2f}")
    assert cb.min_trade_size == 5.00, "Coinbase minimum should be $5"
    assert cb.warn_trade_size == 10.00, "Coinbase warning should be $10"
    print(f"✅ Test 4a PASSED: Coinbase has correct minimums")
    
    # Test 4b: Kraken minimum
    kr = MockBroker(BrokerType.KRAKEN)
    print(f"   Kraken min_trade_size: ${kr.min_trade_size:.2f}")
    print(f"   Kraken warn_trade_size: ${kr.warn_trade_size:.2f}")
    assert kr.min_trade_size == 5.00, "Kraken minimum should be $5"
    assert kr.warn_trade_size == 10.00, "Kraken warning should be $10"
    print(f"✅ Test 4b PASSED: Kraken has correct minimums")
    
    print()


def test_combined_validation():
    """Test combined validation scenarios"""
    print("=" * 70)
    print("TEST 5: Combined Validation Scenarios")
    print("=" * 70)
    
    cb = MockBroker(BrokerType.COINBASE)
    cb.exit_only_mode = True
    
    # Test 5a: Unsupported symbol + exit-only mode (symbol check first)
    result = cb.execute_order('ETH-BUSD', 'buy', 10.0, 'quote')
    
    assert result['error'] == 'UNSUPPORTED_SYMBOL', "Symbol validation should run first"
    print(f"✅ Test 5a PASSED: Symbol validation runs before exit-only check")
    print(f"   Result: {result}")
    
    # Test 5b: Exit-only mode + small trade size (exit-only check first)
    result = cb.execute_order('BTC-USD', 'buy', 3.0, 'quote')
    
    assert result['error'] == 'EXIT_ONLY_MODE', "Exit-only validation should run before size check"
    print(f"✅ Test 5b PASSED: Exit-only validation runs before size check")
    print(f"   Result: {result}")
    
    print()


def run_all_tests():
    """Run all validation tests"""
    print("\n")
    print("=" * 70)
    print("BROKER VALIDATION TEST SUITE")
    print("=" * 70)
    print()
    
    try:
        test_symbol_validation()
        test_exit_only_mode()
        test_minimum_trade_size()
        test_broker_specific_minimums()
        test_combined_validation()
        
        print("=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print()
        print("Summary:")
        print("  - Symbol support validation: ✅")
        print("  - EXIT-ONLY mode validation: ✅")
        print("  - Minimum trade size validation: ✅")
        print("  - Broker-specific minimums: ✅")
        print("  - Combined validation: ✅")
        print()
        
        return 0
        
    except AssertionError as e:
        print("=" * 70)
        print("❌ TEST FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print("=" * 70)
        print("❌ UNEXPECTED ERROR")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(run_all_tests())
