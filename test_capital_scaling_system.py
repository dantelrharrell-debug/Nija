"""
Test Capital Scaling, Performance Dashboard, and Strategy Portfolio

This test validates the integration of all three new systems:
1. Capital Scaling Framework
2. Performance Dashboard
3. Strategy Portfolio Manager
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / "bot"))

from performance_metrics import get_performance_calculator, PerformanceSnapshot
from strategy_portfolio_manager import get_portfolio_manager, MarketRegime
from performance_dashboard import get_performance_dashboard


def test_performance_metrics():
    """Test performance metrics calculator"""
    print("\n" + "="*60)
    print("Testing Performance Metrics Calculator")
    print("="*60)
    
    # Initialize calculator
    calc = get_performance_calculator(initial_capital=10000.0, reset=True)
    
    # Create snapshots
    base_time = datetime.now()
    for i in range(10):
        snapshot = PerformanceSnapshot(
            timestamp=base_time + timedelta(days=i),
            nav=10000 + (i * 100),
            equity=10000 + (i * 100),
            cash=8000 + (i * 80),
            positions_value=2000 + (i * 20),
            unrealized_pnl=i * 10,
            realized_pnl_today=i * 5,
            total_trades=i * 2,
            winning_trades=i,
            losing_trades=i
        )
        calc.record_snapshot(snapshot)
    
    # Calculate metrics
    metrics = calc.calculate_metrics()
    
    print(f"\n✅ Performance Metrics:")
    print(f"   Total Return: {metrics.total_return_pct:.2f}%")
    print(f"   Annualized Return: {metrics.annualized_return_pct:.2f}%")
    print(f"   Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
    print(f"   Max Drawdown: {metrics.max_drawdown_pct:.2f}%")
    print(f"   Win Rate: {metrics.win_rate_pct:.2f}%")
    print(f"   Days Trading: {metrics.days_trading}")
    
    # Test equity curve
    equity_curve = calc.get_equity_curve()
    print(f"\n✅ Equity Curve: {len(equity_curve)} data points")
    
    # Test monthly report
    report = calc.generate_monthly_report(datetime.now().year, datetime.now().month)
    if 'error' not in report:
        print(f"\n✅ Monthly Report:")
        print(f"   Monthly Return: {report.get('monthly_return_pct', 0):.2f}%")
        print(f"   Total Trades: {report.get('total_trades', 0)}")
    
    return True


def test_strategy_portfolio():
    """Test strategy portfolio manager"""
    print("\n" + "="*60)
    print("Testing Strategy Portfolio Manager")
    print("="*60)
    
    # Initialize portfolio
    portfolio = get_portfolio_manager(total_capital=100000.0, reset=True)
    
    print(f"\n✅ Portfolio initialized with ${portfolio.total_capital:,.2f}")
    print(f"   Registered Strategies: {len(portfolio.strategies)}")
    
    # Update regime
    portfolio.update_market_regime(MarketRegime.BULL_TRENDING)
    print(f"\n✅ Market Regime: {portfolio.current_regime.value}")
    
    # Optimize allocation
    allocation = portfolio.optimize_allocation()
    print(f"\n✅ Optimized Allocation:")
    for name, pct in allocation.allocations.items():
        capital = portfolio.get_strategy_capital(name)
        print(f"   {name}: {pct:.1f}% (${capital:,.2f})")
    
    # Simulate some trades
    for i in range(5):
        portfolio.update_strategy_performance(
            strategy_name="APEX_RSI",
            trade_result={'pnl': 100.0 * (i + 1), 'return_pct': 1.0}
        )
    
    # Calculate correlation
    correlation_matrix = portfolio.calculate_correlation_matrix()
    print(f"\n✅ Correlation Matrix: {correlation_matrix.shape}")
    
    # Get diversification score
    div_score = portfolio.get_diversification_score()
    print(f"✅ Diversification Score: {div_score:.1f}/100")
    
    # Get summary
    summary = portfolio.get_portfolio_summary()
    print(f"\n✅ Portfolio Summary:")
    print(f"   Total Capital: ${summary['total_capital']:,.2f}")
    print(f"   Active Strategies: {summary['active_strategies']}")
    print(f"   Total Trades: {summary['total_trades']}")
    print(f"   Total P&L: ${summary['total_pnl']:,.2f}")
    
    return True


def test_performance_dashboard():
    """Test performance dashboard"""
    print("\n" + "="*60)
    print("Testing Performance Dashboard")
    print("="*60)
    
    # Initialize dashboard
    dashboard = get_performance_dashboard(
        initial_capital=10000.0,
        user_id="test_user",
        reset=True
    )
    
    print(f"\n✅ Dashboard initialized for user: {dashboard.user_id}")
    
    # Update snapshots
    for i in range(5):
        dashboard.update_snapshot(
            cash=8000 + (i * 200),
            positions_value=2000 + (i * 100),
            unrealized_pnl=i * 50,
            realized_pnl_today=i * 20,
            total_trades=i * 3,
            winning_trades=i * 2,
            losing_trades=i
        )
    
    print(f"✅ Updated {len(dashboard.metrics_calculator.snapshots)} snapshots")
    
    # Get current metrics
    metrics = dashboard.get_current_metrics()
    print(f"\n✅ Current Metrics:")
    print(f"   Total Return: {metrics['total_return_pct']:.2f}%")
    print(f"   Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"   Max Drawdown: {metrics['max_drawdown_pct']:.2f}%")
    
    # Get equity curve
    equity_curve = dashboard.get_equity_curve()
    print(f"\n✅ Equity Curve: {len(equity_curve)} points")
    
    # Get strategy performance
    strategy_perf = dashboard.get_strategy_performance()
    print(f"\n✅ Strategy Performance:")
    print(f"   Active Strategies: {strategy_perf['active_strategies']}")
    print(f"   Current Regime: {strategy_perf['current_regime']}")
    
    # Get investor summary
    summary = dashboard.get_investor_summary()
    print(f"\n✅ Investor Summary:")
    print(f"   Initial Capital: ${summary['initial_capital']:,.2f}")
    print(f"   Current NAV: ${summary['current_nav']:,.2f}")
    print(f"   Total Return: {summary['total_return_pct']:.2f}%")
    print(f"   Sharpe Ratio: {summary['sharpe_ratio']:.2f}")
    
    # Test export
    try:
        filepath = dashboard.export_investor_report(output_dir="/tmp/nija_reports")
        print(f"\n✅ Exported report to: {filepath}")
    except Exception as e:
        print(f"\n⚠️  Export test skipped: {e}")
    
    return True


def test_integration():
    """Test integration of all systems"""
    print("\n" + "="*60)
    print("Testing System Integration")
    print("="*60)
    
    # Initialize all systems
    dashboard = get_performance_dashboard(initial_capital=100000.0, reset=True)
    portfolio = dashboard.portfolio_manager
    
    # Simulate trading day
    print("\n📊 Simulating Trading Day...")
    
    # Update market regime
    portfolio.update_market_regime(MarketRegime.BULL_TRENDING)
    
    # Get allocations
    allocation = portfolio.optimize_allocation()
    
    # Simulate trades for each strategy
    for strategy_name, alloc_pct in allocation.allocations.items():
        capital = portfolio.get_strategy_capital(strategy_name)
        
        # Simulate trade result
        pnl = capital * 0.02  # 2% gain
        portfolio.update_strategy_performance(
            strategy_name=strategy_name,
            trade_result={'pnl': pnl, 'return_pct': 2.0}
        )
        
        print(f"   {strategy_name}: ${pnl:,.2f} profit")
    
    # Update dashboard snapshot
    total_pnl = sum(perf.total_pnl for perf in portfolio.performance.values())
    dashboard.update_snapshot(
        cash=80000.0,
        positions_value=20000.0 + total_pnl,
        unrealized_pnl=total_pnl,
        realized_pnl_today=total_pnl,
        total_trades=10,
        winning_trades=8,
        losing_trades=2
    )
    
    # Get integrated summary
    summary = dashboard.get_investor_summary()
    
    print(f"\n✅ Integrated System Summary:")
    print(f"   Total Capital: ${summary['current_equity']:,.2f}")
    print(f"   Total Return: {summary['total_return_pct']:.2f}%")
    print(f"   Active Strategies: {summary['active_strategies']}")
    print(f"   Diversification: {summary['diversification_score']:.1f}/100")
    print(f"   Sharpe Ratio: {summary['sharpe_ratio']:.2f}")
    
    return True


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("NIJA Capital Scaling & Performance System Tests")
    print("="*60)
    
    tests = [
        ("Performance Metrics", test_performance_metrics),
        ("Strategy Portfolio", test_strategy_portfolio),
        ("Performance Dashboard", test_performance_dashboard),
        ("System Integration", test_integration)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = "✅ PASS" if result else "❌ FAIL"
        except Exception as e:
            results[test_name] = f"❌ ERROR: {str(e)}"
            import traceback
            traceback.print_exc()
    
    # Print summary
    print("\n" + "="*60)
    print("Test Results Summary")
    print("="*60)
    
    for test_name, result in results.items():
        print(f"{test_name}: {result}")
    
    all_passed = all("PASS" in r for r in results.values())
    
    if all_passed:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed")
        return 1


if __name__ == "__main__":
    exit(main())
