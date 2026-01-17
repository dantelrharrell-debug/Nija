#!/usr/bin/env python3
"""
Test script for NIJA copy-trading functionality.

Tests:
1. Trade signal emission
2. Position sizing calculations
3. Copy trade engine basic functionality
"""

import sys
import os
import time

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_trade_signal_emitter():
    """Test trade signal emission and queue."""
    print("=" * 70)
    print("TEST 1: Trade Signal Emitter")
    print("=" * 70)
    
    from trade_signal_emitter import emit_trade_signal, get_signal_emitter
    
    # Emit a test signal
    result = emit_trade_signal(
        broker="coinbase",
        symbol="BTC-USD",
        side="buy",
        price=45000.0,
        size=500.0,
        size_type="quote",
        order_id="test-123",
        master_balance=10000.0
    )
    
    if result:
        print("✅ Signal emission: PASSED")
    else:
        print("❌ Signal emission: FAILED")
        return False
    
    # Retrieve the signal
    emitter = get_signal_emitter()
    signal = emitter.get_signal(timeout=1.0)
    
    if signal:
        print("✅ Signal retrieval: PASSED")
        print(f"   Symbol: {signal.symbol}")
        print(f"   Side: {signal.side}")
        print(f"   Size: {signal.size}")
        print(f"   Master Balance: ${signal.master_balance:.2f}")
    else:
        print("❌ Signal retrieval: FAILED")
        return False
    
    # Check stats
    stats = emitter.get_stats()
    print(f"✅ Signal stats: {stats['total_emitted']} emitted, {stats['signals_dropped']} dropped")
    
    return True


def test_position_sizer():
    """Test position sizing calculations."""
    print("\n" + "=" * 70)
    print("TEST 2: Position Sizer")
    print("=" * 70)
    
    from position_sizer import calculate_user_position_size
    
    # Test 1: Normal scaling
    result = calculate_user_position_size(
        master_size=500.0,
        master_balance=10000.0,
        user_balance=1000.0,
        size_type="quote",
        symbol="BTC-USD"
    )
    
    expected_size = 50.0  # 10% of master
    if result['valid'] and abs(result['size'] - expected_size) < 0.01:
        print(f"✅ Normal scaling: PASSED (size={result['size']:.2f}, expected={expected_size:.2f})")
    else:
        print(f"❌ Normal scaling: FAILED (size={result['size']:.2f}, expected={expected_size:.2f})")
        return False
    
    # Test 2: Large user account (5x master)
    result = calculate_user_position_size(
        master_size=500.0,
        master_balance=10000.0,
        user_balance=50000.0,
        size_type="quote",
        symbol="BTC-USD"
    )
    
    expected_size = 2500.0  # 500% of master
    if result['valid'] and abs(result['size'] - expected_size) < 0.01:
        print(f"✅ Large account scaling: PASSED (size={result['size']:.2f}, expected={expected_size:.2f})")
    else:
        print(f"❌ Large account scaling: FAILED (size={result['size']:.2f}, expected={expected_size:.2f})")
        return False
    
    # Test 3: Position too small (should fail validation)
    result = calculate_user_position_size(
        master_size=500.0,
        master_balance=10000.0,
        user_balance=10.0,  # Very small balance
        size_type="quote",
        symbol="BTC-USD"
    )
    
    if not result['valid'] and result['size'] < 1.0:
        print(f"✅ Minimum size validation: PASSED (size={result['size']:.2f}, invalid={not result['valid']})")
    else:
        print(f"❌ Minimum size validation: FAILED (size={result['size']:.2f}, should be invalid)")
        return False
    
    # Test 4: Zero user balance (should fail)
    result = calculate_user_position_size(
        master_size=500.0,
        master_balance=10000.0,
        user_balance=0.0,
        size_type="quote",
        symbol="BTC-USD"
    )
    
    if not result['valid']:
        print(f"✅ Zero balance validation: PASSED (correctly rejected)")
    else:
        print(f"❌ Zero balance validation: FAILED (should be invalid)")
        return False
    
    return True


def test_copy_engine_initialization():
    """Test copy trade engine initialization."""
    print("\n" + "=" * 70)
    print("TEST 3: Copy Trade Engine Initialization")
    print("=" * 70)
    
    try:
        from copy_trade_engine import get_copy_engine
        
        # Get engine instance
        engine = get_copy_engine()
        print("✅ Engine initialization: PASSED")
        
        # Check stats
        stats = engine.get_stats()
        print(f"✅ Engine stats: running={stats['running']}, trades={stats['total_trades_copied']}")
        
        return True
    except Exception as e:
        print(f"❌ Engine initialization: FAILED - {e}")
        import traceback
        traceback.print_exc()
        return False


def test_account_type_support():
    """Test that brokers support account_type parameter."""
    print("\n" + "=" * 70)
    print("TEST 4: Broker Account Type Support")
    print("=" * 70)
    
    try:
        from broker_manager import CoinbaseBroker, KrakenBroker, AccountType
        
        # Test CoinbaseBroker with MASTER account type
        broker = CoinbaseBroker(account_type=AccountType.MASTER)
        if broker.account_type == AccountType.MASTER and broker.user_id is None:
            print("✅ CoinbaseBroker MASTER: PASSED")
        else:
            print("❌ CoinbaseBroker MASTER: FAILED")
            return False
        
        # Test KrakenBroker with USER account type
        broker = KrakenBroker(account_type=AccountType.USER, user_id="test_user")
        if broker.account_type == AccountType.USER and broker.user_id == "test_user":
            print("✅ KrakenBroker USER: PASSED")
        else:
            print("❌ KrakenBroker USER: FAILED")
            return False
        
        # Test that USER account type requires user_id
        try:
            broker = KrakenBroker(account_type=AccountType.USER, user_id=None)
            print("❌ USER validation: FAILED (should require user_id)")
            return False
        except ValueError:
            print("✅ USER validation: PASSED (correctly requires user_id)")
        
        return True
    except Exception as e:
        print(f"❌ Account type support: FAILED - {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("🧪 NIJA COPY-TRADING COMPONENT TESTS")
    print("=" * 70)
    print("")
    
    tests = [
        ("Trade Signal Emitter", test_trade_signal_emitter),
        ("Position Sizer", test_position_sizer),
        ("Copy Engine Initialization", test_copy_engine_initialization),
        ("Account Type Support", test_account_type_support),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ {name}: EXCEPTION - {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Print summary
    print("\n" + "=" * 70)
    print("📊 TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {name}")
    
    print("=" * 70)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 70)
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
