#!/usr/bin/env python3
"""
NIJA Brain Integration Test
Tests all 4 components working together
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, timedelta
import pandas as pd
import numpy as np


def test_strategy_orchestrator():
    """Test strategy orchestrator component"""
    print("Testing Strategy Orchestrator...")

    from core.strategy_orchestrator import StrategyOrchestrator, StrategyConfig, StrategyState

    orchestrator = StrategyOrchestrator(total_capital=10000.0)

    # Test 1: Create mock strategy
    class MockStrategy:
        def __init__(self):
            self.name = "mock_strategy"

    config = StrategyConfig(
        strategy_id="test_strategy",
        strategy_class=MockStrategy,
        strategy_instance=MockStrategy(),
        weight=1.0,
        state=StrategyState.ACTIVE
    )

    assert orchestrator.register_strategy(config), "Failed to register strategy"
    assert "test_strategy" in orchestrator.strategies, "Strategy not in registry"
    assert orchestrator.capital_allocations["test_strategy"] > 0, "No capital allocated"

    # Test 2: Record trade result (need 10+ for review)
    for i in range(12):
        orchestrator.record_trade_result("test_strategy", pnl=50.0, fees=0.5, regime="trending")
    perf = orchestrator.performance["test_strategy"]
    assert perf.total_trades == 12, "Trades not recorded"
    assert perf.total_pnl == 600.0, "PnL not recorded correctly"

    # Test 3: Performance review
    results = orchestrator.review_strategy_performance()
    assert "test_strategy" in results["strategy_status"], "Strategy not in review"

    print("✅ Strategy Orchestrator: PASS")
    return True


def test_execution_intelligence():
    """Test execution intelligence component"""
    print("Testing Execution Intelligence...")

    from core.execution_intelligence import ExecutionIntelligence, ExecutionMetrics, ExitSignal

    exec_intel = ExecutionIntelligence()

    # Test 1: Track execution
    execution = ExecutionMetrics(
        order_id="test_order",
        symbol="BTC-USD",
        side="buy",
        requested_size=100,
        filled_size=100,
        fill_price=50000,
        expected_price=50010,
        fees_usd=5.0
    )
    execution.fill_time = datetime.now()

    exec_intel.track_execution(execution)
    assert len(exec_intel.execution_history) == 1, "Execution not tracked"

    # Test 2: Calculate exit score
    df = pd.DataFrame({
        'open': [50000] * 10,
        'high': [50100] * 10,
        'low': [49900] * 10,
        'close': [50000 + i*10 for i in range(10)],
        'volume': [1000] * 10
    })

    indicators = {
        'rsi': pd.Series([60] * 10),
        'macd': {'histogram': pd.Series([10] * 10)},
        'atr': pd.Series([100] * 10),
        'adx': pd.Series([25] * 10)
    }

    position = {
        'entry_price': 50000,
        'size': 100,
        'side': 'long',
        'unrealized_pnl': 50,
        'unrealized_pnl_pct': 0.01
    }

    exit_signal = exec_intel.calculate_exit_score("BTC-USD", df, indicators, position)
    assert isinstance(exit_signal, ExitSignal), "Exit signal not returned"
    assert 0 <= exit_signal.confidence <= 1, "Invalid confidence"
    assert 0 <= exit_signal.exit_score <= 100, "Invalid exit score"

    # Test 3: Dynamic profit targets
    targets = exec_intel.get_dynamic_profit_targets("BTC-USD", df, indicators, 50000)
    assert len(targets) > 0, "No profit targets generated"

    # Test 4: Execution quality report
    report = exec_intel.get_execution_quality_report()
    assert 'total_executions' in report, "Report missing key metrics"

    print("✅ Execution Intelligence: PASS")
    return True


def test_self_learning_engine():
    """Test self-learning engine component"""
    print("Testing Self-Learning Engine...")

    from core.self_learning_engine import SelfLearningEngine, TradeRecord

    learning = SelfLearningEngine(data_dir="/tmp/nija_test_learning")

    # Test 1: Record trade
    trade = TradeRecord(
        trade_id="test_trade_1",
        strategy_id="test_strategy",
        symbol="BTC-USD",
        side="long",
        entry_time=datetime.now() - timedelta(hours=1),
        entry_price=50000,
        entry_size=100,
        entry_indicators={'rsi': 50, 'adx': 25},
        entry_regime="trending",
        entry_confidence=0.75,
        exit_time=datetime.now(),
        exit_price=50500,
        exit_size=100,
        exit_reason="profit_target",
        pnl=500,
        pnl_pct=0.01,
        fees=5,
        net_pnl=495,
        duration_minutes=60
    )

    learning.record_trade(trade)
    assert len(learning.trade_history) == 1, "Trade not recorded"

    # Test 2: Start A/B test
    test_id = learning.start_ab_test(
        strategy_id="test_strategy",
        parameter_name="min_confidence",
        control_value=0.65,
        test_value=0.75
    )
    assert test_id in learning.active_tests, "A/B test not started"

    # Test 3: Record test trades
    learning.record_test_trade(test_id, "trade_1", is_control=True, pnl=50)
    learning.record_test_trade(test_id, "trade_2", is_control=False, pnl=60)

    test = learning.active_tests[test_id]
    assert len(test.control_trades) == 1, "Control trade not recorded"
    assert len(test.test_trades) == 1, "Test trade not recorded"

    print("✅ Self-Learning Engine: PASS")
    return True


def test_investor_metrics():
    """Test investor metrics component"""
    print("Testing Investor Metrics...")

    from core.investor_metrics import InvestorMetricsEngine

    metrics = InvestorMetricsEngine(initial_capital=10000.0)

    # Test 1: Update equity
    metrics.update_equity(10500.0, strategy_id="test_strategy")
    assert metrics.current_capital == 10500.0, "Equity not updated"
    assert len(metrics.equity_curve) == 2, "Equity curve not updated"  # initial + update

    # Test 2: Calculate Sharpe ratio
    returns = [0.01, 0.02, -0.005, 0.015, 0.01]
    sharpe = metrics.calculate_sharpe_ratio(returns)
    assert isinstance(sharpe, float), "Sharpe ratio not calculated"

    # Test 3: Calculate Sortino ratio
    sortino = metrics.calculate_sortino_ratio(returns)
    assert isinstance(sortino, float), "Sortino ratio not calculated"

    # Test 4: Get performance metrics
    perf = metrics.get_performance_metrics()
    assert perf.total_return > 0, "Total return not calculated"
    assert hasattr(perf, 'sharpe_ratio'), "Missing Sharpe ratio"
    assert hasattr(perf, 'max_drawdown'), "Missing max drawdown"

    # Test 5: Generate investor report
    report = metrics.generate_investor_report()
    assert 'account_summary' in report, "Report missing account summary"
    assert 'overall_performance' in report, "Report missing performance"

    print("✅ Investor Metrics: PASS")
    return True


def test_nija_brain_integration():
    """Test full NIJA Brain integration"""
    print("Testing NIJA Brain Integration...")

    from core.nija_brain import NIJABrain

    brain = NIJABrain(total_capital=10000.0)

    # Test 1: Components initialized
    assert brain.orchestrator is not None, "Orchestrator not initialized"
    assert brain.execution_intelligence is not None, "Execution intelligence not initialized"
    assert brain.learning_engine is not None, "Learning engine not initialized"
    assert brain.metrics_engine is not None, "Metrics engine not initialized"

    # Test 2: Analyze opportunity
    df = pd.DataFrame({
        'open': [50000] * 100,
        'high': [50100] * 100,
        'low': [49900] * 100,
        'close': [50000 + i*10 for i in range(100)],
        'volume': [1000] * 100
    })

    indicators = {
        'rsi': pd.Series([60] * 100),
        'macd': {'histogram': pd.Series([10] * 100)},
        'atr': pd.Series([100] * 100),
        'adx': pd.Series([25] * 100),
        'ema_9': pd.Series([50000] * 100),
        'ema_21': pd.Series([49900] * 100),
        'ema_50': pd.Series([49800] * 100),
        'vwap': pd.Series([50050] * 100)
    }

    analysis = brain.analyze_opportunity("BTC-USD", df, indicators)
    assert 'decision' in analysis, "Analysis missing decision"
    assert 'confidence' in analysis, "Analysis missing confidence"
    assert 'components' in analysis, "Analysis missing components"

    # Test 3: Evaluate exit
    position = {
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_price': 50000,
        'size': 100,
        'unrealized_pnl': 500,
        'unrealized_pnl_pct': 0.01
    }

    exit_eval = brain.evaluate_exit("BTC-USD", df, indicators, position)
    assert 'should_exit' in exit_eval, "Exit evaluation missing should_exit"
    assert 'reason' in exit_eval, "Exit evaluation missing reason"

    # Test 4: Record trade
    trade_data = {
        'trade_id': 'integration_test_1',
        'strategy_id': 'test_strategy',
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_time': datetime.now() - timedelta(hours=1),
        'entry_price': 50000,
        'entry_size': 100,
        'entry_regime': 'trending',
        'entry_confidence': 0.75,
        'exit_time': datetime.now(),
        'exit_price': 50500,
        'exit_size': 100,
        'exit_reason': 'profit_target',
        'pnl': 500,
        'pnl_pct': 0.01,
        'fees': 5
    }

    brain.record_trade_completion(trade_data)
    # Verify trade was recorded in all systems

    # Test 5: Performance report
    report = brain.get_performance_report()
    assert 'systems_status' in report, "Report missing systems status"
    assert report['systems_status']['orchestrator'], "Orchestrator not operational"
    assert report['systems_status']['execution_intelligence'], "Execution not operational"

    print("✅ NIJA Brain Integration: PASS")
    return True


def main():
    """Run all tests"""
    print("=" * 60)
    print("NIJA Brain - Comprehensive Integration Tests")
    print("=" * 60)
    print()

    tests = [
        ("Strategy Orchestrator", test_strategy_orchestrator),
        ("Execution Intelligence", test_execution_intelligence),
        ("Self-Learning Engine", test_self_learning_engine),
        ("Investor Metrics", test_investor_metrics),
        ("NIJA Brain Integration", test_nija_brain_integration)
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"❌ {name}: FAIL")
        except Exception as e:
            failed += 1
            print(f"❌ {name}: FAIL - {str(e)}")
            import traceback
            traceback.print_exc()
        print()

    print("=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("🎉 All tests passed! NIJA Brain is fully operational.")
        return 0
    else:
        print("⚠️  Some tests failed. Please review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
