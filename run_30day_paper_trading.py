#!/usr/bin/env python3
"""
NIJA 30-Day Live Paper Trading Monitor
=======================================

Comprehensive paper trading system for 30-day strategy validation before
deploying real capital.

Features:
- Real-time paper trading execution
- Daily performance reports
- Comparison vs backtests
- Performance degradation alerts
- Risk metric monitoring
- Auto-generated summary emails/logs
- Ready-to-review investor reports

Author: NIJA Trading Systems
Date: January 28, 2026
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
import sys

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

from bot.paper_trading import PaperTradingAccount

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('nija.paper_monitor')


@dataclass
class DailyMetrics:
    """Daily performance metrics"""
    date: str
    starting_balance: float
    ending_balance: float
    daily_pnl: float
    daily_return_pct: float
    trades_executed: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    largest_win: float
    largest_loss: float
    open_positions: int
    total_exposure: float


@dataclass
class WeeklyMetrics:
    """Weekly performance summary"""
    week_number: int
    start_date: str
    end_date: str
    weekly_return_pct: float
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    avg_daily_return_pct: float


class PaperTradingMonitor:
    """
    Monitor and analyze 30-day paper trading performance
    """
    
    def __init__(
        self,
        paper_account: PaperTradingAccount,
        data_dir: str = "data/paper_trading_30day"
    ):
        self.account = paper_account
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.metrics_file = self.data_dir / "daily_metrics.json"
        self.alerts_file = self.data_dir / "alerts.json"
        
        # Load or initialize metrics
        self.daily_metrics: List[DailyMetrics] = []
        self.alerts: List[Dict] = []
        self._load_metrics()
    
    def _load_metrics(self):
        """Load historical metrics"""
        if self.metrics_file.exists():
            with open(self.metrics_file, 'r') as f:
                data = json.load(f)
                self.daily_metrics = [DailyMetrics(**m) for m in data.get('daily', [])]
                self.alerts = data.get('alerts', [])
    
    def _save_metrics(self):
        """Save metrics to disk"""
        with open(self.metrics_file, 'w') as f:
            json.dump({
                'daily': [asdict(m) for m in self.daily_metrics],
                'alerts': self.alerts,
                'last_updated': datetime.now().isoformat()
            }, f, indent=2)
    
    def record_daily_metrics(self) -> DailyMetrics:
        """
        Record daily performance metrics
        """
        today = datetime.now().date().isoformat()
        
        # Calculate metrics from account state
        trades_today = [
            t for t in self.account.trades
            if datetime.fromisoformat(t['entry_time']).date().isoformat() == today
        ]
        
        winning_trades = [t for t in trades_today if t.get('pnl', 0) > 0]
        losing_trades = [t for t in trades_today if t.get('pnl', 0) < 0]
        
        daily_pnl = sum(t.get('pnl', 0) for t in trades_today)
        
        # Get starting balance (yesterday's ending balance)
        if self.daily_metrics:
            starting_balance = self.daily_metrics[-1].ending_balance
        else:
            starting_balance = self.account.initial_balance
        
        daily_return_pct = (daily_pnl / starting_balance) * 100 if starting_balance > 0 else 0
        
        # Calculate exposure
        total_exposure = sum(
            pos['size'] * pos['current_price']
            for pos in self.account.positions.values()
        )
        
        metrics = DailyMetrics(
            date=today,
            starting_balance=starting_balance,
            ending_balance=self.account.balance + total_exposure,
            daily_pnl=daily_pnl,
            daily_return_pct=daily_return_pct,
            trades_executed=len(trades_today),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=len(winning_trades) / len(trades_today) if trades_today else 0,
            largest_win=max([t.get('pnl', 0) for t in winning_trades], default=0),
            largest_loss=min([t.get('pnl', 0) for t in losing_trades], default=0),
            open_positions=len(self.account.positions),
            total_exposure=total_exposure
        )
        
        self.daily_metrics.append(metrics)
        self._save_metrics()
        
        # Check for alerts
        self._check_alerts(metrics)
        
        return metrics
    
    def _check_alerts(self, metrics: DailyMetrics):
        """Check for performance degradation or risk alerts"""
        alerts = []
        
        # Daily loss alert
        if metrics.daily_return_pct < -5.0:
            alerts.append({
                'type': 'daily_loss',
                'severity': 'high',
                'message': f'Daily loss exceeds 5%: {metrics.daily_return_pct:.2f}%',
                'timestamp': datetime.now().isoformat()
            })
        
        # Win rate alert
        if metrics.trades_executed >= 5 and metrics.win_rate < 0.4:
            alerts.append({
                'type': 'low_win_rate',
                'severity': 'medium',
                'message': f'Win rate below 40%: {metrics.win_rate*100:.1f}%',
                'timestamp': datetime.now().isoformat()
            })
        
        # Drawdown alert
        if len(self.daily_metrics) >= 2:
            peak_balance = max(m.ending_balance for m in self.daily_metrics)
            current_dd = ((peak_balance - metrics.ending_balance) / peak_balance) * 100
            
            if current_dd > 12.0:
                alerts.append({
                    'type': 'max_drawdown',
                    'severity': 'high',
                    'message': f'Drawdown exceeds 12%: {current_dd:.2f}%',
                    'timestamp': datetime.now().isoformat()
                })
        
        # Overexposure alert
        exposure_pct = (metrics.total_exposure / metrics.ending_balance) * 100 if metrics.ending_balance > 0 else 0
        if exposure_pct > 80.0:
            alerts.append({
                'type': 'overexposure',
                'severity': 'medium',
                'message': f'Total exposure exceeds 80%: {exposure_pct:.1f}%',
                'timestamp': datetime.now().isoformat()
            })
        
        # Log and save alerts
        for alert in alerts:
            logger.warning(f"⚠️ ALERT: {alert['message']}")
            self.alerts.append(alert)
        
        if alerts:
            self._save_metrics()
    
    def generate_weekly_report(self, week_number: int = None) -> WeeklyMetrics:
        """Generate weekly performance summary"""
        if not self.daily_metrics:
            logger.warning("No daily metrics available")
            return None
        
        # Get metrics for the specified week (or latest week)
        if week_number is None:
            week_number = (len(self.daily_metrics) - 1) // 7
        
        start_idx = week_number * 7
        end_idx = min(start_idx + 7, len(self.daily_metrics))
        
        if start_idx >= len(self.daily_metrics):
            logger.warning(f"Week {week_number} not available")
            return None
        
        week_metrics = self.daily_metrics[start_idx:end_idx]
        
        if not week_metrics:
            return None
        
        # Calculate weekly metrics
        start_balance = week_metrics[0].starting_balance
        end_balance = week_metrics[-1].ending_balance
        weekly_return = ((end_balance - start_balance) / start_balance) * 100
        
        total_trades = sum(m.trades_executed for m in week_metrics)
        total_wins = sum(m.winning_trades for m in week_metrics)
        win_rate = total_wins / total_trades if total_trades > 0 else 0
        
        # Daily returns for Sharpe calculation
        daily_returns = [m.daily_return_pct for m in week_metrics]
        sharpe = (np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(252) if len(daily_returns) > 1 and np.std(daily_returns) > 0 else 0
        
        # Max drawdown for the week
        peak = start_balance
        max_dd = 0
        for m in week_metrics:
            peak = max(peak, m.ending_balance)
            dd = ((peak - m.ending_balance) / peak) * 100
            max_dd = max(max_dd, dd)
        
        # Profit factor (simplified)
        total_profit = sum(m.daily_pnl for m in week_metrics if m.daily_pnl > 0)
        total_loss = abs(sum(m.daily_pnl for m in week_metrics if m.daily_pnl < 0))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0
        
        return WeeklyMetrics(
            week_number=week_number + 1,
            start_date=week_metrics[0].date,
            end_date=week_metrics[-1].date,
            weekly_return_pct=weekly_return,
            total_trades=total_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            avg_daily_return_pct=np.mean(daily_returns)
        )
    
    def generate_30day_report(self) -> Dict:
        """
        Generate comprehensive 30-day report
        """
        if not self.daily_metrics:
            return {'error': 'No data available'}
        
        # Overall metrics
        start_balance = self.daily_metrics[0].starting_balance
        end_balance = self.daily_metrics[-1].ending_balance
        total_return = ((end_balance - start_balance) / start_balance) * 100
        
        total_trades = sum(m.trades_executed for m in self.daily_metrics)
        total_wins = sum(m.winning_trades for m in self.daily_metrics)
        total_losses = sum(m.losing_trades for m in self.daily_metrics)
        
        # Calculate metrics
        daily_returns = [m.daily_return_pct for m in self.daily_metrics]
        
        sharpe = (np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(252) if np.std(daily_returns) > 0 else 0
        sortino = self._calculate_sortino(daily_returns)
        
        # Max drawdown
        peak = start_balance
        max_dd = 0
        max_dd_duration = 0
        current_dd_duration = 0
        
        for m in self.daily_metrics:
            if m.ending_balance > peak:
                peak = m.ending_balance
                current_dd_duration = 0
            else:
                current_dd_duration += 1
                dd = ((peak - m.ending_balance) / peak) * 100
                if dd > max_dd:
                    max_dd = dd
                    max_dd_duration = current_dd_duration
        
        # Weekly breakdowns
        weekly_reports = []
        num_weeks = (len(self.daily_metrics) - 1) // 7 + 1
        for week in range(num_weeks):
            weekly = self.generate_weekly_report(week)
            if weekly:
                weekly_reports.append(asdict(weekly))
        
        # Best and worst days
        best_day = max(self.daily_metrics, key=lambda m: m.daily_return_pct)
        worst_day = min(self.daily_metrics, key=lambda m: m.daily_return_pct)
        
        return {
            'summary': {
                'period': f"{self.daily_metrics[0].date} to {self.daily_metrics[-1].date}",
                'trading_days': len(self.daily_metrics),
                'starting_balance': start_balance,
                'ending_balance': end_balance,
                'total_return_pct': total_return,
                'total_pnl': end_balance - start_balance
            },
            'trading_metrics': {
                'total_trades': total_trades,
                'winning_trades': total_wins,
                'losing_trades': total_losses,
                'win_rate': total_wins / total_trades if total_trades > 0 else 0,
                'avg_trades_per_day': total_trades / len(self.daily_metrics)
            },
            'risk_metrics': {
                'sharpe_ratio': sharpe,
                'sortino_ratio': sortino,
                'max_drawdown_pct': max_dd,
                'max_drawdown_duration_days': max_dd_duration,
                'avg_daily_return': np.mean(daily_returns),
                'daily_return_std': np.std(daily_returns),
                'best_day': {
                    'date': best_day.date,
                    'return_pct': best_day.daily_return_pct
                },
                'worst_day': {
                    'date': worst_day.date,
                    'return_pct': worst_day.daily_return_pct
                }
            },
            'weekly_breakdown': weekly_reports,
            'alerts': {
                'total_alerts': len(self.alerts),
                'high_severity': len([a for a in self.alerts if a.get('severity') == 'high']),
                'recent_alerts': self.alerts[-5:] if len(self.alerts) > 5 else self.alerts
            },
            'generated_at': datetime.now().isoformat()
        }
    
    def _calculate_sortino(self, returns: List[float]) -> float:
        """Calculate Sortino ratio (like Sharpe but only penalizes downside volatility)"""
        if not returns:
            return 0
        
        downside_returns = [r for r in returns if r < 0]
        if not downside_returns:
            return 0
        
        downside_std = np.std(downside_returns)
        if downside_std == 0:
            return 0
        
        return (np.mean(returns) / downside_std) * np.sqrt(252)
    
    def compare_to_backtest(self, backtest_file: str) -> Dict:
        """
        Compare paper trading results to backtest expectations
        """
        if not Path(backtest_file).exists():
            logger.warning(f"Backtest file not found: {backtest_file}")
            return {}
        
        with open(backtest_file, 'r') as f:
            backtest = json.load(f)
        
        backtest_perf = backtest.get('overall_performance', {})
        paper_report = self.generate_30day_report()
        
        # Compare key metrics
        comparison = {
            'win_rate': {
                'backtest': backtest_perf.get('win_rate', 0),
                'paper': paper_report['trading_metrics']['win_rate'],
                'difference': paper_report['trading_metrics']['win_rate'] - backtest_perf.get('win_rate', 0)
            },
            'sharpe_ratio': {
                'backtest': backtest_perf.get('sharpe_ratio', 0),
                'paper': paper_report['risk_metrics']['sharpe_ratio'],
                'difference': paper_report['risk_metrics']['sharpe_ratio'] - backtest_perf.get('sharpe_ratio', 0)
            },
            'max_drawdown': {
                'backtest': backtest_perf.get('max_drawdown_pct', 0),
                'paper': paper_report['risk_metrics']['max_drawdown_pct'],
                'difference': paper_report['risk_metrics']['max_drawdown_pct'] - backtest_perf.get('max_drawdown_pct', 0)
            },
            'assessment': self._assess_performance(paper_report, backtest_perf)
        }
        
        return comparison
    
    def _assess_performance(self, paper: Dict, backtest: Dict) -> str:
        """Assess whether paper trading is meeting expectations"""
        paper_wr = paper['trading_metrics']['win_rate']
        backtest_wr = backtest.get('win_rate', 0)
        
        paper_sharpe = paper['risk_metrics']['sharpe_ratio']
        backtest_sharpe = backtest.get('sharpe_ratio', 0)
        
        # Performance is good if within 10% of backtest metrics
        if abs(paper_wr - backtest_wr) < 0.1 and abs(paper_sharpe - backtest_sharpe) < 0.2:
            return "✅ EXCELLENT - Paper trading matches backtest expectations"
        elif paper_wr > backtest_wr * 0.8:
            return "✅ GOOD - Paper trading performance acceptable"
        else:
            return "⚠️ UNDERPERFORMING - Paper trading below backtest expectations"
    
    def print_daily_report(self, metrics: DailyMetrics):
        """Print daily summary"""
        print("\n" + "="*60)
        print(f"DAILY PAPER TRADING REPORT - {metrics.date}")
        print("="*60)
        print(f"\n💰 BALANCE")
        print(f"Starting: ${metrics.starting_balance:,.2f}")
        print(f"Ending:   ${metrics.ending_balance:,.2f}")
        print(f"P&L:      ${metrics.daily_pnl:+,.2f} ({metrics.daily_return_pct:+.2f}%)")
        
        print(f"\n📊 TRADING")
        print(f"Trades:   {metrics.trades_executed}")
        if metrics.trades_executed > 0:
            print(f"Wins:     {metrics.winning_trades} ({metrics.win_rate*100:.1f}%)")
            print(f"Losses:   {metrics.losing_trades}")
            print(f"Best:     ${metrics.largest_win:+,.2f}")
            print(f"Worst:    ${metrics.largest_loss:+,.2f}")
        
        print(f"\n📍 POSITIONS")
        print(f"Open:     {metrics.open_positions}")
        print(f"Exposure: ${metrics.total_exposure:,.2f} ({(metrics.total_exposure/metrics.ending_balance*100):.1f}% of balance)")
        print("="*60 + "\n")
    
    def save_report(self, report: Dict, filename: str):
        """Save report to JSON file"""
        output_path = self.data_dir / filename
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"Report saved to: {output_path}")


def main():
    """Main entry point for paper trading monitor"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='NIJA 30-Day Paper Trading Monitor'
    )
    parser.add_argument(
        '--record-daily',
        action='store_true',
        help='Record daily metrics (run this once per day)'
    )
    parser.add_argument(
        '--weekly-report',
        type=int,
        help='Generate weekly report for specified week number'
    )
    parser.add_argument(
        '--final-report',
        action='store_true',
        help='Generate final 30-day report'
    )
    parser.add_argument(
        '--compare-backtest',
        type=str,
        help='Compare to backtest results (provide path to backtest JSON)'
    )
    parser.add_argument(
        '--data-dir',
        type=str,
        default='data/paper_trading_30day',
        help='Data directory for paper trading (default: data/paper_trading_30day)'
    )
    
    args = parser.parse_args()
    
    # Initialize paper trading account
    paper_account = PaperTradingAccount(initial_balance=10000.0)
    monitor = PaperTradingMonitor(paper_account, data_dir=args.data_dir)
    
    if args.record_daily:
        logger.info("Recording daily metrics...")
        metrics = monitor.record_daily_metrics()
        monitor.print_daily_report(metrics)
    
    elif args.weekly_report is not None:
        logger.info(f"Generating weekly report for week {args.weekly_report}...")
        weekly = monitor.generate_weekly_report(args.weekly_report - 1)  # 0-indexed
        if weekly:
            print(f"\n📊 WEEK {weekly.week_number} REPORT")
            print(f"Period: {weekly.start_date} to {weekly.end_date}")
            print(f"Return: {weekly.weekly_return_pct:+.2f}%")
            print(f"Trades: {weekly.total_trades}")
            print(f"Win Rate: {weekly.win_rate*100:.1f}%")
            print(f"Profit Factor: {weekly.profit_factor:.2f}")
            print(f"Sharpe: {weekly.sharpe_ratio:.2f}")
            print(f"Max DD: {weekly.max_drawdown_pct:.2f}%")
    
    elif args.final_report:
        logger.info("Generating 30-day final report...")
        report = monitor.generate_30day_report()
        monitor.save_report(report, '30day_final_report.json')
        
        # Print summary
        print("\n" + "="*80)
        print("30-DAY PAPER TRADING FINAL REPORT")
        print("="*80)
        print(f"\n📅 Period: {report['summary']['period']}")
        print(f"💰 Return: {report['summary']['total_return_pct']:+.2f}%")
        print(f"📊 Trades: {report['trading_metrics']['total_trades']}")
        print(f"✅ Win Rate: {report['trading_metrics']['win_rate']*100:.1f}%")
        print(f"📈 Sharpe: {report['risk_metrics']['sharpe_ratio']:.2f}")
        print(f"📉 Max DD: {report['risk_metrics']['max_drawdown_pct']:.2f}%")
        print("="*80 + "\n")
    
    elif args.compare_backtest:
        logger.info(f"Comparing to backtest: {args.compare_backtest}")
        comparison = monitor.compare_to_backtest(args.compare_backtest)
        
        if comparison:
            print("\n" + "="*80)
            print("PAPER vs BACKTEST COMPARISON")
            print("="*80)
            for metric, values in comparison.items():
                if metric == 'assessment':
                    print(f"\n{values}")
                elif isinstance(values, dict):
                    print(f"\n{metric.upper()}:")
                    print(f"  Backtest: {values['backtest']:.3f}")
                    print(f"  Paper:    {values['paper']:.3f}")
                    print(f"  Diff:     {values['difference']:+.3f}")
            print("="*80 + "\n")
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
