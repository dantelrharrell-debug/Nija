#!/usr/bin/env python3
"""
NIJA Execution CLI
==================

Unified command-line interface for backtesting and live execution monitoring.

Commands:
- backtest: Run strategy backtest on historical data
- live: Monitor live trading execution
- compare: Compare backtest vs live performance
- report: Generate investor-grade reports

Author: NIJA Trading Systems
Date: January 28, 2026
"""

import argparse
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import json

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent))

from bot.unified_backtest_engine import UnifiedBacktestEngine, BacktestResults
from bot.live_execution_tracker import LiveExecutionTracker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nija.cli")


class NIJAExecutionCLI:
    """Main CLI controller"""
    
    def __init__(self):
        self.parser = self._create_parser()
    
    def _create_parser(self):
        """Create argument parser"""
        parser = argparse.ArgumentParser(
            description="NIJA Execution CLI - Backtesting and Live Execution Monitoring",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Run backtest on BTC-USD
  python nija_execution_cli.py backtest --symbol BTC-USD --data data/BTC-USD_1h.csv --days 90
  
  # Monitor live execution
  python nija_execution_cli.py live --balance 10000
  
  # Generate performance report
  python nija_execution_cli.py report --backtest results/backtest.json --live data/live_tracking
  
  # Compare backtest vs live
  python nija_execution_cli.py compare --backtest results/backtest.json --live data/live_tracking
            """
        )
        
        subparsers = parser.add_subparsers(dest='command', help='Commands')
        
        # Backtest command
        backtest_parser = subparsers.add_parser('backtest', help='Run strategy backtest')
        backtest_parser.add_argument('--symbol', required=True, help='Trading symbol (e.g., BTC-USD)')
        backtest_parser.add_argument('--data', required=True, help='Path to historical data CSV')
        backtest_parser.add_argument('--initial-balance', type=float, default=10000.0, help='Initial balance (default: 10000)')
        backtest_parser.add_argument('--commission', type=float, default=0.001, help='Commission rate (default: 0.001 = 0.1%%)')
        backtest_parser.add_argument('--slippage', type=float, default=0.0005, help='Slippage rate (default: 0.0005 = 0.05%%)')
        backtest_parser.add_argument('--days', type=int, help='Number of days to backtest (from end of data)')
        backtest_parser.add_argument('--output', help='Output file path for results (JSON)')
        backtest_parser.add_argument('--strategy', default='apex_v71', choices=['apex_v71', 'apex_v72', 'enhanced'], help='Strategy to backtest')
        
        # Live tracking command
        live_parser = subparsers.add_parser('live', help='Monitor live execution')
        live_parser.add_argument('--balance', type=float, required=True, help='Current account balance')
        live_parser.add_argument('--data-dir', default='./data/live_tracking', help='Data directory for live tracking')
        live_parser.add_argument('--max-daily-loss', type=float, default=5.0, help='Max daily loss %% (default: 5.0)')
        live_parser.add_argument('--max-drawdown', type=float, default=12.0, help='Max drawdown %% alert (default: 12.0)')
        live_parser.add_argument('--export-csv', action='store_true', help='Export trades to CSV')
        
        # Report command
        report_parser = subparsers.add_parser('report', help='Generate performance report')
        report_parser.add_argument('--backtest', help='Path to backtest results JSON')
        report_parser.add_argument('--live', help='Path to live tracking data directory')
        report_parser.add_argument('--output', help='Output file path for report (HTML)')
        report_parser.add_argument('--format', choices=['html', 'json', 'text'], default='text', help='Report format')
        
        # Compare command
        compare_parser = subparsers.add_parser('compare', help='Compare backtest vs live performance')
        compare_parser.add_argument('--backtest', required=True, help='Path to backtest results JSON')
        compare_parser.add_argument('--live', required=True, help='Path to live tracking data directory')
        
        return parser
    
    def run_backtest(self, args):
        """Run backtest command"""
        logger.info(f"Starting backtest: {args.symbol}")
        
        # Load historical data
        try:
            df = pd.read_csv(args.data)
            logger.info(f"Loaded {len(df)} rows from {args.data}")
            
            # Parse timestamp column
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
            elif 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'])
                df.set_index('time', inplace=True)
            elif 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
            
            # Filter to last N days if specified
            if args.days:
                cutoff = df.index[-1] - timedelta(days=args.days)
                df = df[df.index >= cutoff]
                logger.info(f"Filtered to last {args.days} days: {len(df)} rows")
            
        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            return 1
        
        # Create backtest engine
        engine = UnifiedBacktestEngine(
            initial_balance=args.initial_balance,
            commission_pct=args.commission,
            slippage_pct=args.slippage
        )
        
        # Run simple backtest (placeholder - needs strategy integration)
        logger.info("Running backtest...")
        logger.warning("Note: This is a placeholder. Full strategy integration needed.")
        
        # For now, run a simple example
        # TODO: Integrate with actual NIJA strategy (apex_v71, etc.)
        self._run_simple_backtest(engine, df, args.symbol)
        
        # Calculate results
        results = engine.calculate_metrics()
        
        # Print summary
        results.print_summary()
        
        # Export if requested
        if args.output:
            engine.export_results(results, args.output)
            logger.info(f"Results saved to {args.output}")
        
        return 0
    
    def _run_simple_backtest(self, engine, df, symbol):
        """
        Run simple backtest (placeholder for full strategy integration)
        
        This is a simplified example. In production, this would integrate with
        the actual NIJA APEX strategy.
        """
        # Simple moving average crossover strategy as placeholder
        df['sma_fast'] = df['close'].rolling(window=10).mean()
        df['sma_slow'] = df['close'].rolling(window=30).mean()
        
        position_id = None
        
        for i in range(30, len(df)):
            timestamp = df.index[i]
            row = df.iloc[i]
            
            # Update equity curve
            engine.update_equity_curve(timestamp, {symbol: row['close']})
            
            # Entry signal: fast SMA crosses above slow SMA
            if position_id is None:
                prev_row = df.iloc[i-1]
                if prev_row['sma_fast'] < prev_row['sma_slow'] and row['sma_fast'] > row['sma_slow']:
                    # Buy signal
                    size = (engine.current_balance * 0.02) / row['close']  # 2% position
                    stop_loss = row['close'] * 0.995  # 0.5% stop loss
                    take_profit = row['close'] * 1.015  # 1.5% take profit
                    
                    position_id = engine.open_position(
                        symbol=symbol,
                        side='long',
                        entry_price=row['close'],
                        size=size,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        entry_time=timestamp
                    )
            
            # Exit signals
            elif position_id:
                pos = engine.positions.get(position_id)
                if pos:
                    # Stop loss hit
                    if row['low'] <= pos['stop_loss']:
                        engine.close_position(position_id, pos['stop_loss'], timestamp, "stop_loss")
                        position_id = None
                    # Take profit hit
                    elif pos['take_profit'] and row['high'] >= pos['take_profit']:
                        engine.close_position(position_id, pos['take_profit'], timestamp, "take_profit")
                        position_id = None
                    # Exit signal: fast SMA crosses below slow SMA
                    elif row['sma_fast'] < row['sma_slow']:
                        engine.close_position(position_id, row['close'], timestamp, "signal")
                        position_id = None
    
    def run_live(self, args):
        """Run live tracking command"""
        logger.info("Starting live execution tracker")
        
        # Initialize tracker
        tracker = LiveExecutionTracker(
            initial_balance=args.balance,
            data_dir=args.data_dir,
            max_daily_loss_pct=args.max_daily_loss,
            max_drawdown_pct=args.max_drawdown
        )
        
        # Get performance snapshot
        snapshot = tracker.get_performance_snapshot(current_balance=args.balance)
        
        # Print summary
        print("\n" + "="*80)
        print("LIVE EXECUTION STATUS")
        print("="*80)
        print(f"\n💰 BALANCE")
        print(f"   Current Balance:     ${snapshot.balance:,.2f}")
        print(f"   Total Equity:        ${snapshot.equity:,.2f}")
        print(f"   Unrealized P&L:      ${snapshot.unrealized_pnl:+,.2f}")
        
        print(f"\n📊 TODAY'S PERFORMANCE")
        print(f"   Realized P&L:        ${snapshot.realized_pnl_today:+,.2f}")
        print(f"   Trades:              {snapshot.trades_today}")
        
        print(f"\n📈 OVERALL PERFORMANCE")
        print(f"   Total P&L:           ${snapshot.realized_pnl_total:+,.2f}")
        print(f"   Total Trades:        {snapshot.trades_total}")
        print(f"   Win Rate:            {snapshot.win_rate*100:.1f}%")
        print(f"   Profit Factor:       {snapshot.profit_factor:.2f}")
        print(f"   Sharpe Ratio:        {snapshot.sharpe_ratio:.2f}")
        print(f"   Max Drawdown:        {snapshot.max_drawdown_pct:.2f}%")
        
        print(f"\n🔵 OPEN POSITIONS")
        print(f"   Count:               {snapshot.open_positions}")
        
        print("\n" + "="*80 + "\n")
        
        # Print daily summary
        tracker.print_daily_summary()
        
        # Export to CSV if requested
        if args.export_csv:
            tracker.export_to_csv()
            logger.info("Trades exported to CSV")
        
        return 0
    
    def run_report(self, args):
        """Generate performance report"""
        logger.info("Generating performance report")
        
        data = {}
        
        # Load backtest results if provided
        if args.backtest:
            try:
                with open(args.backtest, 'r') as f:
                    data['backtest'] = json.load(f)
                logger.info(f"Loaded backtest results from {args.backtest}")
            except Exception as e:
                logger.error(f"Failed to load backtest results: {e}")
        
        # Load live tracking data if provided
        if args.live:
            try:
                tracker_state = Path(args.live) / "tracker_state.json"
                with open(tracker_state, 'r') as f:
                    data['live'] = json.load(f)
                logger.info(f"Loaded live tracking data from {args.live}")
            except Exception as e:
                logger.error(f"Failed to load live tracking data: {e}")
        
        if not data:
            logger.error("No data to report. Provide --backtest and/or --live")
            return 1
        
        # Generate report based on format
        if args.format == 'text':
            self._print_text_report(data)
        elif args.format == 'json':
            output = args.output or 'report.json'
            with open(output, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Report saved to {output}")
        elif args.format == 'html':
            logger.warning("HTML report generation not yet implemented")
            logger.info("Use --format json or --format text for now")
        
        return 0
    
    def _print_text_report(self, data):
        """Print text format report"""
        print("\n" + "="*80)
        print("NIJA PERFORMANCE REPORT")
        print("="*80)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if 'backtest' in data:
            print("\n" + "-"*80)
            print("BACKTEST RESULTS")
            print("-"*80)
            summary = data['backtest']['summary']
            print(f"Return: {summary['total_return_pct']:+.2f}%")
            print(f"Trades: {summary['total_trades']}")
            print(f"Win Rate: {summary['win_rate']*100:.1f}%")
            print(f"Profit Factor: {summary['profit_factor']:.2f}")
            print(f"Sharpe Ratio: {summary['sharpe_ratio']:.2f}")
            print(f"Max Drawdown: {summary['max_drawdown_pct']:.2f}%")
        
        if 'live' in data:
            print("\n" + "-"*80)
            print("LIVE TRADING RESULTS")
            print("-"*80)
            trades = data['live']['trades']
            closed_trades = [t for t in trades if t['status'] == 'closed']
            
            if closed_trades:
                total_pnl = sum(t['pnl'] for t in closed_trades)
                wins = [t for t in closed_trades if t['pnl'] > 0]
                win_rate = len(wins) / len(closed_trades) * 100
                
                print(f"Total P&L: ${total_pnl:+.2f}")
                print(f"Trades: {len(closed_trades)}")
                print(f"Win Rate: {win_rate:.1f}%")
            else:
                print("No closed trades yet")
        
        print("\n" + "="*80 + "\n")
    
    def run_compare(self, args):
        """Compare backtest vs live performance"""
        logger.info("Comparing backtest vs live performance")
        
        # Load both datasets
        try:
            with open(args.backtest, 'r') as f:
                backtest_data = json.load(f)
            
            tracker_state = Path(args.live) / "tracker_state.json"
            with open(tracker_state, 'r') as f:
                live_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            return 1
        
        # Extract metrics
        bt_summary = backtest_data['summary']
        
        live_trades = [t for t in live_data['trades'] if t['status'] == 'closed']
        
        if not live_trades:
            logger.warning("No live trades to compare")
            return 1
        
        # Calculate live metrics
        live_wins = [t for t in live_trades if t['pnl'] > 0]
        live_win_rate = len(live_wins) / len(live_trades)
        live_total_pnl = sum(t['pnl'] for t in live_trades)
        
        # Print comparison
        print("\n" + "="*80)
        print("BACKTEST VS LIVE COMPARISON")
        print("="*80)
        
        print(f"\n{'Metric':<25} {'Backtest':<20} {'Live':<20} {'Delta':<15}")
        print("-"*80)
        
        # Win rate
        bt_wr = bt_summary['win_rate'] * 100
        live_wr = live_win_rate * 100
        delta_wr = live_wr - bt_wr
        print(f"{'Win Rate (%)':<25} {bt_wr:<20.1f} {live_wr:<20.1f} {delta_wr:+.1f}")
        
        # Total trades
        print(f"{'Total Trades':<25} {bt_summary['total_trades']:<20} {len(live_trades):<20} {len(live_trades) - bt_summary['total_trades']:+d}")
        
        # Profit factor
        if 'profit_factor' in bt_summary:
            print(f"{'Profit Factor':<25} {bt_summary['profit_factor']:<20.2f} {'N/A':<20} {'N/A':<15}")
        
        # Sharpe ratio
        if 'sharpe_ratio' in bt_summary:
            print(f"{'Sharpe Ratio':<25} {bt_summary['sharpe_ratio']:<20.2f} {'N/A':<20} {'N/A':<15}")
        
        print("\n" + "="*80 + "\n")
        
        # Analysis
        print("📊 ANALYSIS")
        if abs(delta_wr) < 5:
            print("✅ Win rate is within 5% of backtest - good alignment")
        else:
            print("⚠️  Win rate differs by more than 5% from backtest")
        
        print("\n" + "="*80 + "\n")
        
        return 0
    
    def run(self):
        """Main entry point"""
        args = self.parser.parse_args()
        
        if not args.command:
            self.parser.print_help()
            return 1
        
        # Route to appropriate command
        if args.command == 'backtest':
            return self.run_backtest(args)
        elif args.command == 'live':
            return self.run_live(args)
        elif args.command == 'report':
            return self.run_report(args)
        elif args.command == 'compare':
            return self.run_compare(args)
        else:
            logger.error(f"Unknown command: {args.command}")
            return 1


def main():
    """Main entry point"""
    cli = NIJAExecutionCLI()
    sys.exit(cli.run())


if __name__ == "__main__":
    main()
