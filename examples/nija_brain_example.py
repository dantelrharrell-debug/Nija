"""
Example: Using NIJA Brain - Integrated Intelligence System

This example demonstrates how to use the complete NIJA Brain system
with multi-strategy orchestration, execution intelligence, self-learning,
and investor-grade metrics.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.nija_brain import create_nija_brain
from datetime import datetime
import pandas as pd
import numpy as np


def create_sample_market_data(symbol: str = "BTC-USD"):
    """Create sample market data for testing"""
    # Generate 100 candles of sample OHLCV data
    dates = pd.date_range(end=datetime.now(), periods=100, freq='5min')
    
    # Simulate price movement
    base_price = 50000
    prices = base_price + np.cumsum(np.random.randn(100) * 100)
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': prices + np.random.randn(100) * 50,
        'high': prices + np.random.randn(100) * 100,
        'low': prices - np.random.randn(100) * 100,
        'close': prices,
        'volume': np.random.randint(1000, 10000, 100)
    })
    
    return df


def create_sample_indicators(df: pd.DataFrame):
    """Create sample technical indicators"""
    close_prices = df['close']
    
    indicators = {
        'rsi': pd.Series([50 + np.random.randn() * 10 for _ in range(len(df))]),
        'macd': {
            'macd_line': pd.Series(np.random.randn(len(df)) * 100),
            'signal': pd.Series(np.random.randn(len(df)) * 100),
            'histogram': pd.Series(np.random.randn(len(df)) * 50)
        },
        'ema_9': pd.Series(close_prices * 0.99),
        'ema_21': pd.Series(close_prices * 0.98),
        'ema_50': pd.Series(close_prices * 0.97),
        'vwap': pd.Series(close_prices * 1.001),
        'atr': pd.Series([close_prices.iloc[-1] * 0.02] * len(df)),
        'adx': pd.Series([25 + np.random.randn() * 5 for _ in range(len(df))])
    }
    
    return indicators


def main():
    """Main example function"""
    print("=" * 60)
    print("NIJA Brain - Integrated Intelligence System Demo")
    print("=" * 60)
    print()
    
    # Initialize NIJA Brain with $10,000 capital
    print("🧠 Initializing NIJA Brain...")
    brain = create_nija_brain(
        total_capital=10000.0,
        config={
            'execution': {
                'enable_dynamic_targets': True,
                'enable_partial_exits': True
            },
            'learning': {
                'min_trades_for_learning': 10
            },
            'metrics': {
                'risk_free_rate': 0.02
            }
        }
    )
    print()
    
    # Example 1: Analyze trading opportunity
    print("-" * 60)
    print("Example 1: Opportunity Analysis")
    print("-" * 60)
    
    symbol = "BTC-USD"
    df = create_sample_market_data(symbol)
    indicators = create_sample_indicators(df)
    
    analysis = brain.analyze_opportunity(symbol, df, indicators)
    
    print(f"Symbol: {analysis['symbol']}")
    print(f"Decision: {analysis['decision']}")
    print(f"Confidence: {analysis['confidence']:.1%}")
    
    if 'orchestrator' in analysis['components']:
        orch_data = analysis['components']['orchestrator']
        print(f"Signals received: {orch_data.get('signals_count', 0)}")
        if orch_data.get('consensus'):
            print(f"Agreeing strategies: {orch_data['consensus'].get('agreeing_strategies', [])}")
    print()
    
    # Example 2: Evaluate exit for existing position
    print("-" * 60)
    print("Example 2: Exit Evaluation")
    print("-" * 60)
    
    # Simulate existing position
    position = {
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_price': 50000,
        'size': 100,
        'unrealized_pnl': 500,
        'unrealized_pnl_pct': 0.01  # 1% profit
    }
    
    exit_eval = brain.evaluate_exit(symbol, df, indicators, position)
    
    print(f"Should exit: {exit_eval['should_exit']}")
    print(f"Exit percentage: {exit_eval['exit_pct']*100:.0f}%")
    print(f"Reason: {exit_eval['reason']}")
    if 'signal' in exit_eval:
        signal = exit_eval['signal']
        print(f"Signal type: {signal['type']}")
        print(f"Confidence: {signal['confidence']:.1%}")
        print(f"Exit score: {signal['score']:.0f}/100")
    print()
    
    # Example 3: Record a completed trade
    print("-" * 60)
    print("Example 3: Recording Trade")
    print("-" * 60)
    
    trade_data = {
        'trade_id': 'trade_001',
        'strategy_id': 'apex_v72',
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_time': datetime.now(),
        'entry_price': 50000,
        'entry_size': 100,
        'entry_indicators': {},
        'entry_regime': 'trending',
        'entry_confidence': 0.75,
        'exit_time': datetime.now(),
        'exit_price': 50500,
        'exit_size': 100,
        'exit_reason': 'profit_target',
        'pnl': 500,
        'pnl_pct': 0.01,
        'fees': 5,
        'mfe': 600,  # Max favorable excursion
        'mae': -100  # Max adverse excursion
    }
    
    brain.record_trade_completion(trade_data)
    print("✅ Trade recorded successfully")
    print()
    
    # Example 4: Generate performance report
    print("-" * 60)
    print("Example 4: Performance Report")
    print("-" * 60)
    
    report = brain.get_performance_report()
    
    print("System Status:")
    for system, status in report['systems_status'].items():
        print(f"  {system}: {'✅ Online' if status else '❌ Offline'}")
    print()
    
    if 'investor_metrics' in report:
        metrics = report['investor_metrics']
        account = metrics['account_summary']
        overall = metrics['overall_performance']
        
        print("Account Summary:")
        print(f"  Initial Capital: ${account['initial_capital']:,.2f}")
        print(f"  Current Capital: ${account['current_capital']:,.2f}")
        print(f"  Total P&L: ${account['total_pnl']:,.2f}")
        print(f"  Total Return: {account['total_return_pct']:.2f}%")
        print()
        
        print("Performance Metrics:")
        print(f"  Sharpe Ratio: {overall.get('sharpe_ratio', 0):.2f}")
        print(f"  Sortino Ratio: {overall.get('sortino_ratio', 0):.2f}")
        print(f"  Calmar Ratio: {overall.get('calmar_ratio', 0):.2f}")
        print()
    
    if 'execution_quality' in report:
        exec_quality = report['execution_quality']
        if exec_quality.get('status') != 'no_data':
            print("Execution Quality:")
            print(f"  Total Executions: {exec_quality.get('total_executions', 0)}")
            print(f"  Avg Slippage: {exec_quality.get('avg_slippage_bps', 0):.1f} bps")
            print(f"  Total Cost: ${exec_quality.get('execution_cost_total', 0):.2f}")
            print()
    
    # Example 5: Daily review
    print("-" * 60)
    print("Example 5: Daily Review")
    print("-" * 60)
    
    brain.perform_daily_review()
    print()
    
    print("=" * 60)
    print("Demo Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
