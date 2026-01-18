#!/usr/bin/env python3
"""
Test for Immediate Loss Prevention Filter

This test validates that NIJA rejects trades that show immediate loss
beyond acceptable thresholds due to spread/slippage.

Problem: XRP trades being accepted at -$0.23 immediate loss
Solution: Validate fill price and reject if immediate loss > 0.5%
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from execution_engine import ExecutionEngine
from typing import Dict


class MockBrokerClient:
    """Mock broker for testing entry validation"""
    
    def __init__(self, fill_price: float = None, should_fail: bool = False):
        self.fill_price = fill_price
        self.should_fail = should_fail
        self.orders = []
        self.current_price = 2.0  # Default current price
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Mock market order placement"""
        self.orders.append({
            'symbol': symbol,
            'side': side,
            'quantity': quantity
        })
        
        if self.should_fail:
            return {'status': 'error', 'error': 'Mock error'}
        
        # Return successful order with fill price
        return {
            'status': 'filled',
            'success_response': {
                'average_filled_price': self.fill_price if self.fill_price else 2.0
            },
            'order': {
                'order_id': 'mock-123',
                'symbol': symbol
            }
        }
    
    def get_current_price(self, symbol: str) -> float:
        """Mock current price"""
        return self.current_price


def test_scenario_1_acceptable_entry():
    """Test: Normal entry with acceptable fill price"""
    print("\n" + "=" * 70)
    print("TEST 1: Acceptable Entry (minimal slippage)")
    print("=" * 70)
    
    # Setup: Expected $2.00, actual $2.005 (0.25% slippage - acceptable)
    broker = MockBrokerClient(fill_price=2.005)
    engine = ExecutionEngine(broker_client=broker)
    
    result = engine.execute_entry(
        symbol='XRP-USD',
        side='long',
        position_size=100.0,
        entry_price=2.00,
        stop_loss=1.98,
        take_profit_levels={'tp1': 2.03, 'tp2': 2.05, 'tp3': 2.08}
    )
    
    if result is not None:
        print("✅ PASS: Entry accepted (slippage 0.25% < 0.5% threshold)")
        assert result['symbol'] == 'XRP-USD'
        assert result['entry_price'] == 2.005
        assert len(broker.orders) == 1  # Only BUY order
        return True
    else:
        print("❌ FAIL: Entry should have been accepted")
        return False


def test_scenario_2_favorable_entry():
    """Test: Entry with favorable fill (better than expected)"""
    print("\n" + "=" * 70)
    print("TEST 2: Favorable Entry (better fill price)")
    print("=" * 70)
    
    # Setup: Expected $2.00, actual $1.995 (favorable fill)
    broker = MockBrokerClient(fill_price=1.995)
    engine = ExecutionEngine(broker_client=broker)
    
    result = engine.execute_entry(
        symbol='XRP-USD',
        side='long',
        position_size=100.0,
        entry_price=2.00,
        stop_loss=1.98,
        take_profit_levels={'tp1': 2.03, 'tp2': 2.05, 'tp3': 2.08}
    )
    
    if result is not None:
        print("✅ PASS: Entry accepted (favorable fill)")
        assert result['entry_price'] == 1.995
        assert len(broker.orders) == 1
        return True
    else:
        print("❌ FAIL: Favorable entry should have been accepted")
        return False


def test_scenario_3_excessive_loss_rejected():
    """Test: Entry with excessive immediate loss (REJECTED)"""
    print("\n" + "=" * 70)
    print("TEST 3: Excessive Loss - SHOULD BE REJECTED")
    print("=" * 70)
    print("Scenario: XRP expected $2.00, filled at $2.015 (0.75% loss)")
    
    # Setup: Expected $2.00, actual $2.015 (0.75% loss - exceeds 0.5% threshold)
    broker = MockBrokerClient(fill_price=2.015)
    engine = ExecutionEngine(broker_client=broker)
    
    result = engine.execute_entry(
        symbol='XRP-USD',
        side='long',
        position_size=100.0,
        entry_price=2.00,
        stop_loss=1.98,
        take_profit_levels={'tp1': 2.03, 'tp2': 2.05, 'tp3': 2.08}
    )
    
    if result is None:
        print("✅ PASS: Entry correctly rejected (0.75% loss > 0.5% threshold)")
        assert engine.rejected_trades_count == 1
        assert engine.immediate_exit_count == 1
        assert len(broker.orders) == 2  # BUY + immediate SELL
        print(f"   Orders: {len(broker.orders)} (BUY + immediate EXIT)")
        return True
    else:
        print("❌ FAIL: Entry should have been rejected")
        print(f"   Immediate loss 0.75% exceeds 0.5% threshold!")
        return False


def test_scenario_4_xrp_real_case():
    """Test: XRP case - rejecting trades with excessive slippage"""
    print("\n" + "=" * 70)
    print("TEST 4: XRP Case - Immediate Loss Prevention")
    print("=" * 70)
    print("Problem: Master losing money on XRP trades with immediate losses")
    print("Scenario: XRP at $2.00, filled at $2.012")
    print("          Slippage: 0.6%, Position: $10")
    print("          This represents the type of bad fill we want to prevent")
    
    # Example scenario: XRP expected $2.00, filled at $2.012
    # Slippage = (2.00 - 2.012) / 2.00 = -0.6% (unfavorable)
    # Dollar loss on $10 position = $10 * 0.006 = $0.06
    # This type of bad execution should be rejected
    
    broker = MockBrokerClient(fill_price=2.012)
    engine = ExecutionEngine(broker_client=broker)
    
    result = engine.execute_entry(
        symbol='XRP-USD',
        side='long',
        position_size=10.0,  # Small position
        entry_price=2.00,
        stop_loss=1.98,
        take_profit_levels={'tp1': 2.03, 'tp2': 2.05, 'tp3': 2.08}
    )
    
    # Calculate expected loss
    expected_slippage_pct = 0.006  # 0.6%
    expected_loss_usd = 10.0 * expected_slippage_pct
    
    if result is None:
        print(f"✅ PASS: XRP trade rejected ({expected_slippage_pct*100:.1f}% slippage >= 0.5% threshold)")
        print("   This prevents accepting trades with bad execution!")
        print(f"   Prevented immediate loss: ${expected_loss_usd:.2f} on ${10.0:.2f} position")
        assert engine.rejected_trades_count == 1
        return True
    else:
        print("❌ FAIL: XRP trade should have been rejected")
        return False


def test_scenario_5_threshold_boundary():
    """Test: Entry exactly at threshold (should reject at boundary)"""
    print("\n" + "=" * 70)
    print("TEST 5: Boundary Test - Exactly at 0.5% threshold")
    print("=" * 70)
    print("Expected: $2.00, Actual: $2.010 (exactly 0.5% unfavorable)")
    
    # Setup: Expected $2.00, actual $2.010
    # Slippage = (2.00 - 2.010) / 2.00 = -0.005 = -0.5% (exactly at threshold)
    # With >= comparison, this should be REJECTED
    broker = MockBrokerClient(fill_price=2.010)
    engine = ExecutionEngine(broker_client=broker)
    
    result = engine.execute_entry(
        symbol='XRP-USD',
        side='long',
        position_size=100.0,
        entry_price=2.00,
        stop_loss=1.98,
        take_profit_levels={'tp1': 2.03, 'tp2': 2.05, 'tp3': 2.08}
    )
    
    # At exactly threshold (0.5%), should REJECT (using >= not >)
    if result is None:
        print("✅ PASS: Entry at exact threshold (0.5%) rejected")
        print("   Using >= comparison to be conservative")
        assert engine.rejected_trades_count == 1
        return True
    else:
        print("❌ FAIL: Entry at exact threshold should be rejected")
        return False


def test_scenario_6_short_position():
    """Test: Short position with excessive loss"""
    print("\n" + "=" * 70)
    print("TEST 6: Short Position with Excessive Loss")
    print("=" * 70)
    
    # Setup: Short at expected $2.00, filled at $1.985 (sold for less = loss)
    # Loss = (2.00 - 1.985) / 2.00 = 0.75% - should reject
    broker = MockBrokerClient(fill_price=1.985)
    engine = ExecutionEngine(broker_client=broker)
    
    result = engine.execute_entry(
        symbol='XRP-USD',
        side='short',
        position_size=100.0,
        entry_price=2.00,
        stop_loss=2.02,
        take_profit_levels={'tp1': 1.97, 'tp2': 1.95, 'tp3': 1.92}
    )
    
    if result is None:
        print("✅ PASS: Short entry rejected (0.75% loss > 0.5% threshold)")
        assert engine.rejected_trades_count == 1
        return True
    else:
        print("❌ FAIL: Short entry should have been rejected")
        return False


def run_all_tests():
    """Run all test scenarios"""
    print("\n" + "=" * 70)
    print("IMMEDIATE LOSS PREVENTION FILTER - TEST SUITE")
    print("=" * 70)
    print("\nPurpose: Prevent NIJA from accepting trades with excessive spread/slippage")
    print("Threshold: 0.5% maximum immediate loss")
    print("\nRunning tests...")
    
    tests = [
        ("Acceptable Entry", test_scenario_1_acceptable_entry),
        ("Favorable Entry", test_scenario_2_favorable_entry),
        ("Excessive Loss Rejected", test_scenario_3_excessive_loss_rejected),
        ("Real XRP Case", test_scenario_4_xrp_real_case),
        ("Threshold Boundary", test_scenario_5_threshold_boundary),
        ("Short Position Loss", test_scenario_6_short_position),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n❌ ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    print("=" * 70)
    print(f"Results: {passed_count}/{total_count} tests passed")
    print("=" * 70)
    
    if passed_count == total_count:
        print("\n🎉 ALL TESTS PASSED!")
        print("\nImmediate loss filter is working correctly:")
        print("  ✅ Accepts normal trades with acceptable slippage (< 0.5%)")
        print("  ✅ Rejects trades with excessive spread/loss (> 0.5%)")
        print("  ✅ Automatically closes bad entries to prevent losses")
        print("  ✅ Works for both long and short positions")
        return 0
    else:
        print(f"\n⚠️ {total_count - passed_count} TEST(S) FAILED")
        return 1


if __name__ == '__main__':
    exit(run_all_tests())
