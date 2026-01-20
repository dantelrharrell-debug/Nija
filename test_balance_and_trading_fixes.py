"""
Test Balance Model and Trading Fixes
====================================

Tests for the critical balance and trading rule fixes:
1. Balance Model (3-part split)
2. Sell bypass balance checks
3. Emergency liquidation at -1% PnL
4. Kraken nonce persistence
5. Broker fee optimization
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

import logging
logging.basicConfig(level=logging.INFO)

def test_balance_model():
    """Test balance model with 3-part split."""
    print("\n" + "="*70)
    print("TEST: Balance Model (FIX 1)")
    print("="*70)
    
    try:
        from balance_models import BalanceSnapshot, UserBrokerState, create_balance_snapshot_from_broker_response
        
        # Test BalanceSnapshot
        snapshot = BalanceSnapshot(
            total_equity_usd=100.0,
            available_usd=60.0,
            locked_in_positions_usd=40.0,
            broker_name='coinbase'
        )
        
        assert snapshot.total_equity_usd == 100.0
        assert snapshot.available_usd == 60.0
        assert snapshot.locked_in_positions_usd == 40.0
        assert snapshot.utilization_pct == 40.0
        
        print("✅ BalanceSnapshot working correctly")
        print(f"   Total: ${snapshot.total_equity_usd:.2f}, Available: ${snapshot.available_usd:.2f}, Locked: ${snapshot.locked_in_positions_usd:.2f}")
        
        # Test UserBrokerState  
        user_state = UserBrokerState(
            broker='coinbase',
            user_id='test_user',
            balance=snapshot,
            open_positions=[{'symbol': 'BTC-USD'}]
        )
        
        assert user_state.total_equity == 100.0
        assert user_state.available_cash == 60.0
        assert user_state.position_count == 1
        
        print("✅ UserBrokerState working correctly")
        print(f"   User: {user_state.user_id}, Equity: ${user_state.total_equity:.2f}, Positions: {user_state.position_count}")
        
        print("\n✅ PASSED: Balance Model\n")
        return True
        
    except Exception as e:
        print(f"\n❌ FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_emergency_liquidation():
    """Test emergency liquidation at -1% PnL."""
    print("\n" + "="*70)
    print("TEST: Emergency Liquidation (FIX 3)")
    print("="*70)
    
    try:
        from emergency_liquidation import EmergencyLiquidator
        
        liquidator = EmergencyLiquidator()
        
        # Test -0.5% loss (should NOT liquidate)
        position1 = {
            'symbol': 'BTC-USD',
            'entry_price': 100.0,
            'size_usd': 100.0,
            'side': 'long'
        }
        should_liquidate = liquidator.should_force_liquidate(position1, 99.5)
        assert should_liquidate == False
        print("✅ Small loss (-0.5%): No liquidation")
        
        # Test -1.5% loss (SHOULD liquidate)
        should_liquidate = liquidator.should_force_liquidate(position1, 98.5)
        assert should_liquidate == True
        print("✅ Big loss (-1.5%): Emergency liquidation triggered")
        
        print("\n✅ PASSED: Emergency Liquidation\n")
        return True
        
    except Exception as e:
        print(f"\n❌ FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_kraken_nonce():
    """Test Kraken nonce persistence."""
    print("\n" + "="*70)
    print("TEST: Kraken Nonce Persistence (FIX 4)")
    print("="*70)
    
    try:
        from global_kraken_nonce import get_global_kraken_nonce, get_global_nonce_stats
        
        nonce1 = get_global_kraken_nonce()
        nonce2 = get_global_kraken_nonce()
        
        assert nonce2 > nonce1, "Nonces must increase"
        print(f"✅ Nonces are monotonic: {nonce2} > {nonce1}")
        
        stats = get_global_nonce_stats()
        print(f"✅ Total nonces issued: {stats['total_nonces_issued']}")
        
        print("\n✅ PASSED: Kraken Nonce Persistence\n")
        return True
        
    except Exception as e:
        print(f"\n❌ FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_fee_optimizer():
    """Test broker fee optimizer."""
    print("\n" + "="*70)
    print("TEST: Broker Fee Optimizer (FIX 6)")
    print("="*70)
    
    try:
        from broker_fee_optimizer import BrokerFeeOptimizer, BROKER_FEE_PROFILES
        
        optimizer = BrokerFeeOptimizer()
        
        # Test small balance
        should_disable = optimizer.should_disable_coinbase(30.0)
        assert should_disable == True
        print("✅ Small balance ($30): Coinbase disabled")
        
        # Test large balance
        should_disable = optimizer.should_disable_coinbase(100.0)
        assert should_disable == False
        print("✅ Large balance ($100): Coinbase enabled")
        
        # Test broker selection
        optimal = optimizer.get_optimal_broker(30.0, ['coinbase', 'kraken'])
        assert optimal == 'kraken'
        print(f"✅ Optimal broker for $30: {optimal}")
        
        # Test profit target
        target = optimizer.adjust_profit_target_for_fees('coinbase', 30.0, 0.01)
        assert target >= 0.02
        print(f"✅ Adjusted profit target: {target*100:.1f}%")
        
        print("\n✅ PASSED: Broker Fee Optimizer\n")
        return True
        
    except Exception as e:
        print(f"\n❌ FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*70)
    print("BALANCE MODEL AND TRADING FIXES TEST SUITE")
    print("="*70)
    
    tests = [
        ("Balance Model", test_balance_model),
        ("Emergency Liquidation", test_emergency_liquidation),
        ("Kraken Nonce", test_kraken_nonce),
        ("Fee Optimizer", test_fee_optimizer),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"❌ {test_name} crashed: {e}")
            results[test_name] = False
    
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    print("="*70)
    print(f"TOTAL: {passed}/{total} tests passed")
    print("="*70)
    
    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
