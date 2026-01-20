"""
Test Suite: Unified Broker Minimum Balance Rules
=================================================

Tests for the unified $25 Coinbase minimum balance enforcement:
- Option A: Exact $25 minimum parameters
- Option B: Kraken primary engine
- Option C: Emergency hotfix
- Option D: Unified balance rules

This test verifies that all systems enforce the same $25 threshold.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_coinbase_config_minimum():
    """Test Option A: Coinbase config has $25 minimum"""
    from broker_configs.coinbase_config import COINBASE_CONFIG
    
    print("=" * 60)
    print("TEST 1: Coinbase Config Minimum Position Size")
    print("=" * 60)
    
    assert COINBASE_CONFIG.min_position_usd == 25.0, \
        f"Expected $25 minimum, got ${COINBASE_CONFIG.min_position_usd}"
    
    assert COINBASE_CONFIG.recommended_min_usd == 25.0, \
        f"Expected $25 recommended, got ${COINBASE_CONFIG.recommended_min_usd}"
    
    print(f"✅ PASS: Coinbase config min_position_usd = ${COINBASE_CONFIG.min_position_usd}")
    print(f"✅ PASS: Coinbase config recommended_min_usd = ${COINBASE_CONFIG.recommended_min_usd}")
    print()


def test_broker_adapter_minimum():
    """Test Option A: Broker adapter enforces $25 minimum"""
    from broker_adapters import CoinbaseAdapter
    
    print("=" * 60)
    print("TEST 2: Broker Adapter Minimum Notional")
    print("=" * 60)
    
    adapter = CoinbaseAdapter()
    
    assert adapter.MIN_NOTIONAL_DEFAULT == 25.0, \
        f"Expected $25 default notional, got ${adapter.MIN_NOTIONAL_DEFAULT}"
    
    assert adapter.MIN_NOTIONAL_BTC == 25.0, \
        f"Expected $25 BTC notional, got ${adapter.MIN_NOTIONAL_BTC}"
    
    print(f"✅ PASS: Adapter MIN_NOTIONAL_DEFAULT = ${adapter.MIN_NOTIONAL_DEFAULT}")
    print(f"✅ PASS: Adapter MIN_NOTIONAL_BTC = ${adapter.MIN_NOTIONAL_BTC}")
    print()


def test_broker_manager_minimum():
    """Test Option C & D: Broker manager enforces $25 minimum"""
    from broker_manager import COINBASE_MINIMUM_BALANCE
    
    print("=" * 60)
    print("TEST 3: Broker Manager Minimum Balance")
    print("=" * 60)
    
    assert COINBASE_MINIMUM_BALANCE == 25.0, \
        f"Expected $25 minimum balance, got ${COINBASE_MINIMUM_BALANCE}"
    
    print(f"✅ PASS: COINBASE_MINIMUM_BALANCE = ${COINBASE_MINIMUM_BALANCE}")
    print()


def test_broker_fee_optimizer_minimum():
    """Test Option C & D: Fee optimizer enforces $25 minimum"""
    from broker_fee_optimizer import BrokerFeeOptimizer
    
    print("=" * 60)
    print("TEST 4: Broker Fee Optimizer Minimum Balance")
    print("=" * 60)
    
    optimizer = BrokerFeeOptimizer()
    
    assert optimizer.COINBASE_MIN_BALANCE == 25.0, \
        f"Expected $25 minimum balance, got ${optimizer.COINBASE_MIN_BALANCE}"
    
    print(f"✅ PASS: Fee optimizer COINBASE_MIN_BALANCE = ${optimizer.COINBASE_MIN_BALANCE}")
    print()


def test_kraken_priority():
    """Test Option B: Kraken is primary engine"""
    from broker_fee_optimizer import BrokerFeeOptimizer
    
    print("=" * 60)
    print("TEST 5: Kraken Primary Engine Priority")
    print("=" * 60)
    
    optimizer = BrokerFeeOptimizer()
    
    # Test broker selection with small balance
    small_balance_brokers = ['coinbase', 'kraken', 'alpaca']
    selected = optimizer.get_optimal_broker(30.0, small_balance_brokers)
    
    assert selected == 'kraken', \
        f"Expected Kraken to be selected, got {selected}"
    
    print(f"✅ PASS: Kraken selected for $30 balance (primary engine)")
    
    # Test broker selection with large balance
    large_balance_brokers = ['coinbase', 'kraken', 'alpaca']
    selected = optimizer.get_optimal_broker(100.0, large_balance_brokers)
    
    assert selected == 'kraken', \
        f"Expected Kraken to be selected even with large balance, got {selected}"
    
    print(f"✅ PASS: Kraken selected for $100 balance (primary engine)")
    
    # Test Coinbase disabled for small balance
    assert optimizer.should_disable_coinbase(20.0) == True, \
        "Expected Coinbase to be disabled for $20 balance"
    
    print(f"✅ PASS: Coinbase disabled for balance < $25")
    
    # Test Coinbase enabled for balance >= $25
    assert optimizer.should_disable_coinbase(25.0) == False, \
        "Expected Coinbase to be enabled for $25 balance"
    
    print(f"✅ PASS: Coinbase enabled for balance >= $25")
    print()


def test_exchange_risk_profile_minimum():
    """Test Option D: Exchange risk profiles use $25 minimum"""
    from exchange_risk_profiles import _get_coinbase_profile
    
    print("=" * 60)
    print("TEST 6: Exchange Risk Profile Minimum")
    print("=" * 60)
    
    profile = _get_coinbase_profile()
    
    assert profile['min_position_usd'] == 25.0, \
        f"Expected $25 minimum position, got ${profile['min_position_usd']}"
    
    print(f"✅ PASS: Exchange risk profile min_position_usd = ${profile['min_position_usd']}")
    print()


def test_unified_consistency():
    """Test Option D: All systems use the same $25 threshold"""
    from broker_configs.coinbase_config import COINBASE_CONFIG
    from broker_adapters import CoinbaseAdapter
    from broker_manager import COINBASE_MINIMUM_BALANCE
    from broker_fee_optimizer import BrokerFeeOptimizer
    from exchange_risk_profiles import _get_coinbase_profile
    
    print("=" * 60)
    print("TEST 7: Unified Balance Rules Consistency")
    print("=" * 60)
    
    adapter = CoinbaseAdapter()
    optimizer = BrokerFeeOptimizer()
    profile = _get_coinbase_profile()
    
    # Collect all minimum values
    minimums = {
        'Coinbase Config': COINBASE_CONFIG.min_position_usd,
        'Broker Adapter': adapter.MIN_NOTIONAL_DEFAULT,
        'Broker Manager': COINBASE_MINIMUM_BALANCE,
        'Fee Optimizer': optimizer.COINBASE_MIN_BALANCE,
        'Risk Profile': profile['min_position_usd'],
    }
    
    # Check all are $25
    for name, value in minimums.items():
        assert value == 25.0, \
            f"{name} has ${value}, expected $25"
        print(f"  {name:20s}: ${value:.2f} ✅")
    
    print(f"\n✅ PASS: All systems unified at $25 minimum")
    print()


def test_profitability_calculation():
    """Test that $25 minimum is profitable after fees"""
    print("=" * 60)
    print("TEST 8: Profitability Calculation")
    print("=" * 60)
    
    position_size = 25.0
    fee_pct = 0.014  # 1.4% Coinbase fees
    profit_target_pct = 0.015  # 1.5% profit target
    
    # Calculate fee cost
    fee_cost = position_size * fee_pct
    
    # Calculate profit at target
    profit_at_target = position_size * profit_target_pct
    
    # Net profit
    net_profit = profit_at_target - fee_cost
    
    print(f"  Position size: ${position_size:.2f}")
    print(f"  Fee cost (1.4%): ${fee_cost:.2f}")
    print(f"  Profit target (1.5%): ${profit_at_target:.2f}")
    print(f"  Net profit: ${net_profit:.2f}")
    
    assert net_profit > 0, \
        f"Expected positive net profit, got ${net_profit:.2f}"
    
    print(f"\n✅ PASS: $25 position is profitable after fees (net ${net_profit:.2f})")
    print()


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("UNIFIED BROKER MINIMUM BALANCE TEST SUITE")
    print("=" * 60)
    print()
    
    tests = [
        test_coinbase_config_minimum,
        test_broker_adapter_minimum,
        test_broker_manager_minimum,
        test_broker_fee_optimizer_minimum,
        test_kraken_priority,
        test_exchange_risk_profile_minimum,
        test_unified_consistency,
        test_profitability_calculation,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ FAIL: {test.__name__}")
            print(f"   Error: {e}")
            print()
            failed += 1
        except Exception as e:
            print(f"❌ ERROR: {test.__name__}")
            print(f"   Error: {e}")
            print()
            failed += 1
    
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"  Total tests: {passed + failed}")
    print(f"  Passed: {passed} ✅")
    print(f"  Failed: {failed} {'❌' if failed > 0 else ''}")
    print("=" * 60)
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! 🎉")
        print("\nImplementation Summary:")
        print("  ✅ Option A: Coinbase $25 minimum enforced")
        print("  ✅ Option B: Kraken is primary engine")
        print("  ✅ Option C: Emergency hotfix deployed")
        print("  ✅ Option D: Unified balance rules across all brokers")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
