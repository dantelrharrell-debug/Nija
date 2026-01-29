#!/usr/bin/env python3
"""
NIJA Execution Demo
===================

Demonstrates the complete workflow of:
1. Running a backtest
2. Simulating live trades
3. Comparing backtest vs live performance

This is a complete end-to-end example showing how to use the
Live Execution + Backtesting Engine.

Author: NIJA Trading Systems
Date: January 28, 2026
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent))

from bot.unified_backtest_engine import UnifiedBacktestEngine
from bot.live_execution_tracker import LiveExecutionTracker


def generate_sample_data(days=90):
    """Generate sample OHLCV data for testing"""
    print("📊 Generating sample market data...")

    # Generate realistic BTC price data
    np.random.seed(42)

    dates = pd.date_range(end=datetime.now(), periods=days*24, freq='1h')

    # Start at $50,000 and add random walk
    base_price = 50000.0
    returns = np.random.normal(0.0001, 0.02, len(dates))  # Slight upward bias
    prices = base_price * np.exp(np.cumsum(returns))

    # Generate OHLC from close prices
    df = pd.DataFrame({
        'close': prices,
        'open': prices * (1 + np.random.uniform(-0.005, 0.005, len(prices))),
        'high': prices * (1 + np.random.uniform(0, 0.01, len(prices))),
        'low': prices * (1 - np.random.uniform(0, 0.01, len(prices))),
        'volume': np.random.uniform(100, 1000, len(prices))
    }, index=dates)

    # Ensure OHLC logic is correct
    df['high'] = df[['open', 'close', 'high']].max(axis=1)
    df['low'] = df[['open', 'close', 'low']].min(axis=1)

    print(f"✅ Generated {len(df)} hourly candles")
    print(f"   Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

    return df


def run_backtest_demo():
    """Run backtest demonstration"""
    print("\n" + "="*80)
    print("PART 1: BACKTESTING")
    print("="*80)

    # Generate sample data
    df = generate_sample_data(days=90)

    # Create backtest engine
    engine = UnifiedBacktestEngine(
        initial_balance=10000.0,
        commission_pct=0.001,  # 0.1%
        slippage_pct=0.0005    # 0.05%
    )

    print("\n🚀 Running backtest with simple MA crossover strategy...")

    # Simple moving average strategy
    df['sma_fast'] = df['close'].rolling(window=10).mean()
    df['sma_slow'] = df['close'].rolling(window=30).mean()

    position_id = None
    trades_count = 0

    for i in range(30, len(df)):
        timestamp = df.index[i]
        row = df.iloc[i]
        prev_row = df.iloc[i-1]

        # Update equity curve
        engine.update_equity_curve(timestamp, {"BTC-USD": row['close']})

        # Entry: Fast crosses above slow
        if position_id is None and prev_row['sma_fast'] < prev_row['sma_slow'] and row['sma_fast'] > row['sma_slow']:
            size = (engine.current_balance * 0.02) / row['close']  # 2% position
            stop_loss = row['close'] * 0.995  # 0.5% stop
            take_profit = row['close'] * 1.015  # 1.5% target

            position_id = engine.open_position(
                symbol="BTC-USD",
                side='long',
                entry_price=row['close'],
                size=size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                entry_time=timestamp,
                regime="trending"
            )

            if position_id:
                trades_count += 1

        # Exit: Stop loss or take profit
        elif position_id:
            pos = engine.positions.get(position_id)
            if pos:
                # Stop loss
                if row['low'] <= pos['stop_loss']:
                    engine.close_position(position_id, pos['stop_loss'], timestamp, "stop_loss")
                    position_id = None
                # Take profit
                elif pos['take_profit'] and row['high'] >= pos['take_profit']:
                    engine.close_position(position_id, pos['take_profit'], timestamp, "take_profit")
                    position_id = None
                # Exit signal
                elif row['sma_fast'] < row['sma_slow']:
                    engine.close_position(position_id, row['close'], timestamp, "signal")
                    position_id = None

    # Close any remaining positions
    if position_id:
        last_row = df.iloc[-1]
        engine.close_position(position_id, last_row['close'], df.index[-1], "end_of_data")

    # Calculate results
    results = engine.calculate_metrics()

    print(f"\n✅ Backtest complete: {trades_count} entries executed")

    # Print detailed results
    results.print_summary()

    # Export results
    results_dir = Path("./results")
    results_dir.mkdir(exist_ok=True)
    engine.export_results(results, results_dir / "demo_backtest.json")

    print(f"\n📁 Results saved to: results/demo_backtest.json")

    return results


def run_live_demo():
    """Run live tracking demonstration"""
    print("\n" + "="*80)
    print("PART 2: LIVE EXECUTION TRACKING")
    print("="*80)

    # Initialize tracker
    tracker = LiveExecutionTracker(
        initial_balance=10000.0,
        data_dir="./data/demo_live_tracking",
        max_daily_loss_pct=5.0,
        max_drawdown_pct=12.0
    )

    print("\n🔴 Simulating live trades...")

    # Simulate some live trades
    current_balance = 10000.0

    # Trade 1: Winner
    print("\nTrade 1: LONG BTC-USD")
    tracker.record_entry(
        trade_id="LIVE-001",
        symbol="BTC-USD",
        side="long",
        entry_price=50000.0,
        size=0.04,  # $2000 position (2% of account)
        stop_loss=49750.0,
        take_profit=50750.0,
        commission=2.0,
        broker="coinbase"
    )

    tracker.record_exit(
        trade_id="LIVE-001",
        exit_price=50750.0,
        exit_reason="take_profit",
        commission=2.03
    )
    current_balance += 26.0  # Net profit after fees

    # Trade 2: Loser
    print("Trade 2: LONG ETH-USD")
    tracker.record_entry(
        trade_id="LIVE-002",
        symbol="ETH-USD",
        side="long",
        entry_price=3000.0,
        size=0.67,  # ~$2000 position
        stop_loss=2985.0,
        take_profit=3045.0,
        commission=2.0,
        broker="coinbase"
    )

    tracker.record_exit(
        trade_id="LIVE-002",
        exit_price=2985.0,
        exit_reason="stop_loss",
        commission=2.0
    )
    current_balance -= 14.05  # Net loss after fees

    # Trade 3: Winner
    print("Trade 3: LONG BTC-USD")
    tracker.record_entry(
        trade_id="LIVE-003",
        symbol="BTC-USD",
        side="long",
        entry_price=51000.0,
        size=0.04,
        stop_loss=50745.0,
        take_profit=51765.0,
        commission=2.04,
        broker="coinbase"
    )

    tracker.record_exit(
        trade_id="LIVE-003",
        exit_price=51765.0,
        exit_reason="take_profit",
        commission=2.07
    )
    current_balance += 26.49

    # Get performance snapshot
    print("\n📊 Getting performance snapshot...")
    snapshot = tracker.get_performance_snapshot(current_balance=current_balance)

    print("\n" + "="*80)
    print("LIVE PERFORMANCE SNAPSHOT")
    print("="*80)
    print(f"Current Balance:     ${snapshot.balance:,.2f}")
    print(f"Total Equity:        ${snapshot.equity:,.2f}")
    print(f"Total P&L:           ${snapshot.realized_pnl_total:+.2f}")
    print(f"Total Trades:        {snapshot.trades_total}")
    print(f"Win Rate:            {snapshot.win_rate*100:.1f}%")
    print(f"Profit Factor:       {snapshot.profit_factor:.2f}")
    print("="*80)

    # Print daily summary
    tracker.print_daily_summary()

    # Export to CSV
    tracker.export_to_csv("./data/demo_live_tracking/demo_trades.csv")
    print(f"\n📁 Live trades saved to: data/demo_live_tracking/demo_trades.csv")

    return tracker


def compare_results(backtest_results, live_tracker):
    """Compare backtest vs live results"""
    print("\n" + "="*80)
    print("PART 3: BACKTEST VS LIVE COMPARISON")
    print("="*80)

    # Get live stats
    snapshot = live_tracker.get_performance_snapshot(current_balance=10038.44)

    print(f"\n{'Metric':<25} {'Backtest':<20} {'Live':<20} {'Delta':<15}")
    print("-"*80)

    # Win Rate
    bt_wr = backtest_results.win_rate * 100
    live_wr = snapshot.win_rate * 100
    delta_wr = live_wr - bt_wr
    print(f"{'Win Rate (%)':<25} {bt_wr:<20.1f} {live_wr:<20.1f} {delta_wr:+.1f}")

    # Total Trades
    print(f"{'Total Trades':<25} {backtest_results.total_trades:<20} {snapshot.trades_total:<20} {snapshot.trades_total - backtest_results.total_trades:+d}")

    # Profit Factor
    print(f"{'Profit Factor':<25} {backtest_results.profit_factor:<20.2f} {snapshot.profit_factor:<20.2f} {snapshot.profit_factor - backtest_results.profit_factor:+.2f}")

    # Total Return
    bt_return = backtest_results.total_return_pct
    live_return = ((snapshot.balance - 10000) / 10000) * 100
    delta_return = live_return - bt_return
    print(f"{'Total Return (%)':<25} {bt_return:<20.2f} {live_return:<20.2f} {delta_return:+.2f}")

    print("\n" + "="*80)

    # Analysis
    print("\n🔍 ANALYSIS:")
    if abs(delta_wr) < 10:
        print("   ✅ Win rate is within 10% of backtest")
    else:
        print("   ⚠️  Win rate differs significantly from backtest")

    if abs(delta_return) < 5:
        print("   ✅ Returns are within 5% of backtest")
    else:
        print("   ⚠️  Returns differ significantly from backtest")

    print("\n" + "="*80 + "\n")


def main():
    """Main demo function"""
    print("\n" + "="*80)
    print("NIJA LIVE EXECUTION + BACKTESTING ENGINE DEMO")
    print("="*80)
    print("\nThis demo shows:")
    print("  1. Running a backtest with performance metrics")
    print("  2. Tracking live trades with risk monitoring")
    print("  3. Comparing backtest vs live performance")
    print("\n" + "="*80)

    # Part 1: Backtest
    backtest_results = run_backtest_demo()

    # Part 2: Live tracking
    live_tracker = run_live_demo()

    # Part 3: Comparison
    compare_results(backtest_results, live_tracker)

    print("\n✅ Demo complete!")
    print("\nNext steps:")
    print("  - Review generated files in ./results/ and ./data/")
    print("  - Integrate with actual NIJA APEX strategies")
    print("  - Connect to real broker APIs for live trading")
    print("  - Set up automated daily reporting")
    print("\nFor more information, see: LIVE_EXECUTION_BACKTESTING_GUIDE.md")
    print()


if __name__ == "__main__":
    main()
