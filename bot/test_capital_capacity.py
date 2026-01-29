#!/usr/bin/env python3
"""
Test Capital Capacity Calculations
===================================

Test suite for deployable capital and max position size calculations.
"""

import sys
sys.path.insert(0, './bot')

from portfolio_state import PortfolioState, UserPortfolioState


def test_empty_portfolio():
    """Test portfolio with no positions."""
    print("\n🧪 Test 1: Empty Portfolio")
    portfolio = PortfolioState(available_cash=1000.0, min_reserve_pct=0.10)

    assert portfolio.total_equity == 1000.0, "Total equity should equal cash"
    assert portfolio.total_position_value == 0.0, "No positions"

    deployable = portfolio.calculate_deployable_capital()
    # Deployable = total_equity * (1 - reserve_pct) - positions
    # = 1000 * (1 - 0.10) - 0 = 900
    expected_deployable = 1000.0 * (1 - 0.10)
    assert abs(deployable - expected_deployable) < 0.01, f"Expected {expected_deployable}, got {deployable}"

    max_position = portfolio.calculate_max_position_size()
    # Max = min(total_equity * max_pct, deployable, available_cash)
    # = min(1000 * 0.15, 900, 1000) = min(150, 900, 1000) = 150
    expected_max = min(1000.0 * 0.15, deployable)
    assert abs(max_position - expected_max) < 0.01, f"Expected {expected_max}, got {max_position}"

    print(f"   ✅ Total Equity: ${portfolio.total_equity:.2f}")
    print(f"   ✅ Deployable: ${deployable:.2f} (calculated: {1000.0} * (1 - 0.10) = {expected_deployable:.2f})")
    print(f"   ✅ Max Position: ${max_position:.2f} (min of 15% equity or deployable)")


def test_portfolio_with_positions():
    """Test portfolio with open positions."""
    print("\n🧪 Test 2: Portfolio with Positions")
    portfolio = PortfolioState(available_cash=8000.0, min_reserve_pct=0.10)
    portfolio.add_position("BTC-USD", 0.1, 45000, 46000)  # $4600 position

    # Total equity = cash + positions = 8000 + 4600 = 12600
    assert portfolio.total_equity == 12600.0, "Total equity = cash + positions"
    assert abs(portfolio.total_position_value - 4600.0) < 0.01, "Position value"

    # Calculate deployable
    # Max deployable = total_equity * (1 - reserve_pct) - deployed
    # = 12600 * (1 - 0.10) - 4600
    # = 12600 * 0.9 - 4600
    # = 11340 - 4600 = 6740
    deployable = portfolio.calculate_deployable_capital()
    expected_deployable = (12600.0 * (1 - 0.10)) - 4600.0
    assert abs(deployable - expected_deployable) < 0.01, f"Expected {expected_deployable}, got {deployable}"

    # Max position = min(total_equity * max_pct, deployable, available_cash)
    # = min(12600 * 0.15, 6740, 8000)
    # = min(1890, 6740, 8000) = 1890
    max_position = portfolio.calculate_max_position_size()
    expected_max = min(12600.0 * 0.15, deployable, 8000.0)
    assert abs(max_position - expected_max) < 0.01, f"Expected {expected_max}, got {max_position}"

    print(f"   ✅ Total Equity: ${portfolio.total_equity:.2f}")
    print(f"   ✅ Deployable: ${deployable:.2f} (12600 * 0.9 - 4600 = {expected_deployable:.2f})")
    print(f"   ✅ Max Position: ${max_position:.2f} (min(1890, 6740, 8000) = {expected_max:.2f})")


def test_fully_deployed_portfolio():
    """Test portfolio that's near max deployment."""
    print("\n🧪 Test 3: Fully Deployed Portfolio")
    portfolio = PortfolioState(available_cash=1000.0, min_reserve_pct=0.10)
    portfolio.add_position("BTC-USD", 0.2, 45000, 46000)  # $9200 position

    # Total equity = 1000 + 9200 = 10200
    # Max deployable = 10200 * 0.9 = 9180
    # Already deployed = 9200 (over the limit!)
    # Remaining = 0 (can't go negative in real scenario, but calculation shows -20)

    deployable = portfolio.calculate_deployable_capital()
    # Should be 0 or very small since we're already over-deployed
    assert deployable >= 0, "Deployable should never be negative"
    assert deployable < 100, f"Should have minimal deployable, got {deployable}"

    print(f"   ✅ Total Equity: ${portfolio.total_equity:.2f}")
    print(f"   ✅ Deployable: ${deployable:.2f} (minimal - near max deployment)")
    print(f"   ✅ Cash Utilization: {portfolio.cash_utilization_pct:.1f}%")


def test_custom_reserve_percentage():
    """Test with custom reserve percentage."""
    print("\n🧪 Test 4: Custom Reserve Percentage (20%)")
    portfolio = PortfolioState(available_cash=10000.0, min_reserve_pct=0.20)

    # With 20% reserve:
    # Max deployable = 10000 * 0.8 = 8000
    deployable = portfolio.calculate_deployable_capital()
    expected_deployable = 8000.0
    assert abs(deployable - expected_deployable) < 0.01, f"Expected {expected_deployable}, got {deployable}"

    print(f"   ✅ Reserve: 20%")
    print(f"   ✅ Deployable: ${deployable:.2f}")


def test_custom_max_position_percentage():
    """Test with custom max position percentage."""
    print("\n🧪 Test 5: Custom Max Position Percentage (20%)")
    portfolio = PortfolioState(available_cash=10000.0, min_reserve_pct=0.10)

    # With 20% max position:
    # Max = 10000 * 0.20 = 2000
    max_position = portfolio.calculate_max_position_size(max_position_pct=0.20)
    expected_max = 2000.0
    assert abs(max_position - expected_max) < 0.01, f"Expected {expected_max}, got {max_position}"

    print(f"   ✅ Max Position %: 20%")
    print(f"   ✅ Max Position: ${max_position:.2f}")


def test_user_portfolio_state():
    """Test UserPortfolioState."""
    print("\n🧪 Test 6: User Portfolio State")
    user_portfolio = UserPortfolioState(
        available_cash=5000.0,
        user_id="test_user",
        broker_type="coinbase",
        min_reserve_pct=0.10
    )

    assert user_portfolio.user_id == "test_user"
    assert user_portfolio.broker_type == "coinbase"
    assert user_portfolio.total_equity == 5000.0

    deployable = user_portfolio.calculate_deployable_capital()
    assert deployable == 4500.0, f"Expected 4500, got {deployable}"

    print(f"   ✅ User ID: {user_portfolio.user_id}")
    print(f"   ✅ Broker: {user_portfolio.broker_type}")
    print(f"   ✅ Deployable: ${deployable:.2f}")


def test_capital_breakdown():
    """Test get_capital_breakdown method."""
    print("\n🧪 Test 7: Capital Breakdown")
    portfolio = PortfolioState(available_cash=10000.0, min_reserve_pct=0.10)
    portfolio.add_position("ETH-USD", 2.0, 3000, 3100)  # $6200 position

    breakdown = portfolio.get_capital_breakdown()

    # Verify all fields are present
    required_fields = [
        'total_equity', 'available_cash', 'total_position_value',
        'deployable_capital', 'max_position_size', 'cash_utilization_pct',
        'min_reserve_amount', 'max_deployable_total'
    ]

    for field in required_fields:
        assert field in breakdown, f"Missing field: {field}"

    assert breakdown['total_equity'] == 16200.0
    assert breakdown['total_position_value'] == 6200.0
    assert breakdown['available_cash'] == 10000.0

    print(f"   ✅ All required fields present")
    print(f"   ✅ Total Equity: ${breakdown['total_equity']:.2f}")
    print(f"   ✅ Deployable: ${breakdown['deployable_capital']:.2f}")


def test_summary_includes_capital_metrics():
    """Test that get_summary includes capital metrics."""
    print("\n🧪 Test 8: Summary Includes Capital Metrics")
    portfolio = PortfolioState(available_cash=5000.0, min_reserve_pct=0.10)

    summary = portfolio.get_summary()

    assert 'deployable_capital' in summary, "Summary should include deployable_capital"
    assert 'max_position_size' in summary, "Summary should include max_position_size"

    print(f"   ✅ Summary includes deployable_capital")
    print(f"   ✅ Summary includes max_position_size")


def test_edge_case_zero_balance():
    """Test edge case with zero balance."""
    print("\n🧪 Test 9: Edge Case - Zero Balance")
    portfolio = PortfolioState(available_cash=0.0, min_reserve_pct=0.10)

    assert portfolio.total_equity == 0.0
    assert portfolio.calculate_deployable_capital() == 0.0
    assert portfolio.calculate_max_position_size() == 0.0

    print(f"   ✅ Zero balance handled correctly")


def test_edge_case_very_small_balance():
    """Test edge case with very small balance."""
    print("\n🧪 Test 10: Edge Case - Very Small Balance")
    portfolio = PortfolioState(available_cash=10.0, min_reserve_pct=0.10)

    deployable = portfolio.calculate_deployable_capital()
    max_position = portfolio.calculate_max_position_size()

    assert deployable == 9.0, f"Expected 9.0, got {deployable}"
    assert max_position == 1.5, f"Expected 1.5, got {max_position}"

    print(f"   ✅ Small balance: ${portfolio.total_equity:.2f}")
    print(f"   ✅ Deployable: ${deployable:.2f}")
    print(f"   ✅ Max Position: ${max_position:.2f}")


def run_all_tests():
    """Run all test cases."""
    print("="*80)
    print("CAPITAL CAPACITY CALCULATION TESTS")
    print("="*80)

    test_empty_portfolio()
    test_portfolio_with_positions()
    test_fully_deployed_portfolio()
    test_custom_reserve_percentage()
    test_custom_max_position_percentage()
    test_user_portfolio_state()
    test_capital_breakdown()
    test_summary_includes_capital_metrics()
    test_edge_case_zero_balance()
    test_edge_case_very_small_balance()

    print("\n" + "="*80)
    print("✅ ALL TESTS PASSED!")
    print("="*80)
    print()


if __name__ == '__main__':
    run_all_tests()
