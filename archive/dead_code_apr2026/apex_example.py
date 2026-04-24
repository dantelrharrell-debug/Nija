"""
NIJA Apex Strategy v7.1 - Example Usage
=========================================

This script demonstrates how to use the Apex Strategy v7.1.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from apex_strategy_v7 import ApexStrategyV7
from apex_backtest import ApexBacktest


def generate_sample_data(num_candles=200):
    """
    Generate sample OHLCV data for testing

    In production, you would fetch this from your broker or data provider.
    """
    np.random.seed(42)

    # Generate realistic price movement
    base_price = 50000.0  # Starting price
    prices = [base_price]

    for _ in range(num_candles - 1):
        change = np.random.normal(0, 0.01)  # 1% volatility
        new_price = prices[-1] * (1 + change)
        prices.append(new_price)

    # Create OHLC from close prices
    data = []
    for i, close in enumerate(prices):
        high = close * (1 + abs(np.random.normal(0, 0.005)))
        low = close * (1 - abs(np.random.normal(0, 0.005)))
        open_price = close * (1 + np.random.normal(0, 0.003))
        volume = np.random.uniform(100000, 1000000)

        data.append({
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        })

    df = pd.DataFrame(data)
    df.index = pd.date_range(start=datetime.now() - timedelta(minutes=5*num_candles),
                             periods=num_candles, freq='5min')

    return df


def example_1_analyze_entry():
    """Example 1: Analyze entry opportunity for a symbol"""
    print("\n" + "="*60)
    print("EXAMPLE 1: Analyze Entry Opportunity")
    print("="*60 + "\n")

    # Generate sample data
    df = generate_sample_data(num_candles=150)

    # Initialize strategy with $10,000 balance
    strategy = ApexStrategyV7(account_balance=10000.0, enable_ai=False)

    # Analyze entry opportunity
    analysis = strategy.analyze_entry_opportunity(df, symbol="BTC-USD")

    # Print results
    print(f"Symbol: {analysis['symbol']}")
    print(f"Should Enter: {analysis['should_enter']}")

    if analysis['should_enter']:
        print(f"\n✅ ENTRY SIGNAL DETECTED!")
        print(f"  Side: {analysis['side'].upper()}")
        print(f"  Entry Price: ${analysis['entry_price']:,.2f}")
        print(f"  Stop Loss: ${analysis['stop_loss']:,.2f}")
        print(f"  Take Profit Levels:")
        for tp, price in analysis['take_profit_levels'].items():
            print(f"    {tp}: ${price:,.2f}")
        print(f"  Position Size: ${analysis['position_size_usd']:,.2f} ({analysis['position_size_pct']*100:.1f}%)")
        print(f"  Risk Amount: ${analysis['risk_amount']:,.2f}")
        print(f"  Trend Direction: {analysis['trend_direction']}")
        print(f"  Trend Quality: {analysis['trend_quality']}")
        print(f"  ADX: {analysis['adx']:.1f}")
        print(f"  Entry Score: {analysis['score']}/5")
        print(f"  Conditions Met: {', '.join(analysis['conditions_met'])}")
    else:
        print(f"\n❌ NO ENTRY SIGNAL")
        print(f"  Reason: {analysis['reason']}")
        if 'adx' in analysis:
            print(f"  ADX: {analysis['adx']:.1f}")


def example_2_backtest():
    """Example 2: Run a backtest"""
    print("\n" + "="*60)
    print("EXAMPLE 2: Backtest Strategy")
    print("="*60 + "\n")

    # Generate sample data (more candles for backtest)
    df = generate_sample_data(num_candles=500)

    # Initialize backtest with $10,000
    backtest = ApexBacktest(initial_balance=10000.0, enable_ai=False)

    # Run backtest
    print("Running backtest...")
    results = backtest.run_backtest(
        df,
        symbol="BTC-USD",
        commission=0.001  # 0.1% commission
    )

    # Print results
    backtest.print_results(results)

    # Show first few trades
    if results['trades']:
        print("\nFirst 5 Trades:")
        print("-" * 60)
        for i, trade in enumerate(results['trades'][:5], 1):
            print(f"{i}. {trade['side'].upper()} @ ${trade['entry_price']:,.2f} → "
                  f"${trade['exit_price']:,.2f} | "
                  f"P&L: ${trade['pnl']:,.2f} ({trade['pnl_pct']*100:+.2f}%) | "
                  f"Reason: {trade['reason']}")


def example_3_position_update():
    """Example 3: Update an existing position"""
    print("\n" + "="*60)
    print("EXAMPLE 3: Update Position with Trailing Stops")
    print("="*60 + "\n")

    # Generate sample data
    df = generate_sample_data(num_candles=150)

    # Initialize strategy
    strategy = ApexStrategyV7(account_balance=10000.0, enable_ai=False)

    # Simulate an open position
    position = {
        'id': 'BTC-USD_1',
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_price': 48000.0,
        'stop_loss': 47500.0,
        'take_profit_levels': {
            'TP1': 48500.0,
            'TP2': 49000.0,
            'TP3': 49500.0,
        },
        'size_usd': 500.0,
    }

    print(f"Position: {position['side'].upper()} {position['symbol']}")
    print(f"Entry: ${position['entry_price']:,.2f}")
    print(f"Current Stop: ${position['stop_loss']:,.2f}")

    # Update position
    update_result = strategy.update_position('BTC-USD_1', df, position)

    print(f"\nUpdate Result:")
    print(f"  Action: {update_result['action']}")

    if update_result['action'] == 'update_stop':
        print(f"  New Stop: ${update_result['new_stop']:,.2f}")
        print(f"  R-Multiple: {update_result['r_multiple']:.2f}R")
        if update_result['action_taken']:
            print(f"  Action Taken: {update_result['action_taken']}")
    elif update_result['action'] == 'exit':
        print(f"  Exit Percentage: {update_result['exit_percentage']*100:.0f}%")
        print(f"  Reason: {update_result['reason']}")


def main():
    """Run all examples"""
    print("\n" + "="*60)
    print("NIJA APEX STRATEGY v7.1 - EXAMPLES")
    print("="*60)

    # Run examples
    example_1_analyze_entry()
    example_2_backtest()
    example_3_position_update()

    print("\n" + "="*60)
    print("Examples Complete!")
    print("="*60 + "\n")

    print("Next Steps:")
    print("1. Review the code in apex_strategy_v7.py")
    print("2. Customize parameters in apex_config.py")
    print("3. Test with real historical data")
    print("4. Paper trade before going live")
    print("5. Start with small position sizes")


if __name__ == "__main__":
    main()
