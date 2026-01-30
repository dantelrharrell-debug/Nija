"""
NIJA KPI Tracker

Comprehensive Key Performance Indicator (KPI) tracking system for NIJA trading bot.
Tracks, calculates, and reports on critical trading performance metrics.

Features:
- Real-time KPI calculations
- Historical KPI tracking
- Performance benchmarking
- Multi-timeframe analysis
- Export and reporting capabilities

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import statistics

logger = logging.getLogger(__name__)


@dataclass
class KPISnapshot:
    """Snapshot of KPIs at a specific point in time"""
    timestamp: str
    
    # Trading Performance KPIs
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    
    # Financial KPIs
    total_profit: float
    total_loss: float
    net_profit: float
    total_fees: float
    average_win: float
    average_loss: float
    
    # Risk KPIs
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    current_drawdown: float
    calmar_ratio: float
    
    # Efficiency KPIs
    expectancy: float
    risk_reward_ratio: float
    profit_per_trade: float
    roi_percentage: float
    
    # Activity KPIs
    trades_per_day: float
    active_days: int
    uptime_hours: float
    
    # Portfolio KPIs
    account_balance: float
    account_equity: float
    account_growth: float
    
    # Strategy KPIs
    active_strategies: int
    best_strategy: str
    worst_strategy: str


class KPITracker:
    """
    Comprehensive KPI tracking system for trading performance.
    
    Tracks and calculates key performance indicators including:
    - Win rate, profit factor, expectancy
    - Sharpe ratio, Sortino ratio, Calmar ratio
    - Drawdown metrics
    - Trading activity metrics
    - Portfolio growth metrics
    """
    
    def __init__(self, data_dir: str = "/tmp/nija_kpis", initial_capital: float = 1000.0):
        """
        Initialize KPI tracker.
        
        Args:
            data_dir: Directory to store KPI data
            initial_capital: Starting capital amount
            
        Raises:
            ValueError: If initial_capital is zero or negative
        """
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.kpi_file = self.data_dir / "kpi_snapshots.json"
        self.config_file = self.data_dir / "kpi_config.json"
        
        self.initial_capital = initial_capital
        self.start_time = datetime.now()
        
        # KPI data storage
        self.snapshots: List[KPISnapshot] = []
        self.trade_history: List[Dict] = []
        self.daily_returns: List[float] = []
        self.equity_curve: List[float] = []
        
        # Strategy performance tracking
        self.strategy_performance: Dict[str, Dict] = defaultdict(lambda: {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'total_profit': 0.0,
            'total_loss': 0.0
        })
        
        # Peak tracking
        self.peak_balance = initial_capital
        self.peak_equity = initial_capital
        
        # Load existing data
        self._load_data()
        
        logger.info(f"✅ KPI Tracker initialized with ${initial_capital:,.2f}")
    
    def _load_data(self):
        """Load KPI data from disk"""
        try:
            if self.kpi_file.exists():
                with open(self.kpi_file, 'r') as f:
                    data = json.load(f)
                    self.snapshots = [KPISnapshot(**s) for s in data.get('snapshots', [])]
                    self.trade_history = data.get('trade_history', [])
                    self.daily_returns = data.get('daily_returns', [])
                    self.equity_curve = data.get('equity_curve', [])
                    # Convert loaded dict back to defaultdict
                    loaded_perf = data.get('strategy_performance', {})
                    for strategy, perf in loaded_perf.items():
                        self.strategy_performance[strategy] = perf
                    logger.info(f"📊 Loaded {len(self.snapshots)} KPI snapshots")
        except Exception as e:
            logger.warning(f"Could not load KPI data: {e}")
    
    def _save_data(self):
        """Save KPI data to disk"""
        try:
            data = {
                'snapshots': [asdict(s) for s in self.snapshots],
                'trade_history': self.trade_history,
                'daily_returns': self.daily_returns,
                'equity_curve': self.equity_curve,
                'strategy_performance': dict(self.strategy_performance),
                'last_updated': datetime.now().isoformat()
            }
            with open(self.kpi_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save KPI data: {e}")
    
    def record_trade(self, symbol: str, strategy: str, profit: float, fees: float, 
                     is_win: bool, entry_price: float, exit_price: float,
                     position_size: float):
        """
        Record a trade for KPI calculations.
        
        Args:
            symbol: Trading symbol
            strategy: Strategy name
            profit: Profit/loss amount (positive for wins, negative for losses)
            fees: Trading fees
            is_win: Whether trade was profitable
            entry_price: Entry price
            exit_price: Exit price
            position_size: Position size
        """
        trade = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'strategy': strategy,
            'profit': profit,
            'fees': fees,
            'net_profit': profit - fees,
            'is_win': is_win,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'position_size': position_size
        }
        
        self.trade_history.append(trade)
        
        # Update strategy performance
        self.strategy_performance[strategy]['trades'] += 1
        if is_win:
            self.strategy_performance[strategy]['wins'] += 1
            self.strategy_performance[strategy]['total_profit'] += profit
        else:
            self.strategy_performance[strategy]['losses'] += 1
            self.strategy_performance[strategy]['total_loss'] += abs(profit)
        
        logger.info(f"📝 Trade recorded: {symbol} {strategy} {'WIN' if is_win else 'LOSS'} ${profit:.2f}")
    
    def update_balance(self, balance: float, equity: float):
        """
        Update account balance and equity.
        
        Args:
            balance: Current account balance
            equity: Current account equity
        """
        self.equity_curve.append(equity)
        
        # Update peaks
        if equity > self.peak_equity:
            self.peak_equity = equity
        if balance > self.peak_balance:
            self.peak_balance = balance
        
        # Calculate daily return
        if len(self.equity_curve) > 1:
            daily_return = (equity - self.equity_curve[-2]) / self.equity_curve[-2]
            self.daily_returns.append(daily_return)
    
    def calculate_kpis(self, current_balance: float, current_equity: float) -> KPISnapshot:
        """
        Calculate current KPIs.
        
        Args:
            current_balance: Current account balance
            current_equity: Current account equity
            
        Returns:
            KPISnapshot with calculated KPIs
        """
        # Basic trade statistics
        total_trades = len(self.trade_history)
        winning_trades = sum(1 for t in self.trade_history if t['is_win'])
        losing_trades = total_trades - winning_trades
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        # Profit/loss calculations
        total_profit = sum(t['profit'] for t in self.trade_history if t['is_win'])
        total_loss = sum(abs(t['profit']) for t in self.trade_history if not t['is_win'])
        total_fees = sum(t['fees'] for t in self.trade_history)
        net_profit = sum(t['net_profit'] for t in self.trade_history)
        
        average_win = total_profit / winning_trades if winning_trades > 0 else 0.0
        average_loss = total_loss / losing_trades if losing_trades > 0 else 0.0
        
        # Risk metrics
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf') if total_profit > 0 else 0.0
        risk_reward_ratio = average_win / average_loss if average_loss > 0 else 0.0
        expectancy = (win_rate/100 * average_win) - ((100-win_rate)/100 * average_loss)
        
        # Sharpe ratio (simplified)
        sharpe_ratio = 0.0
        if self.daily_returns and len(self.daily_returns) > 1:
            avg_return = statistics.mean(self.daily_returns)
            std_return = statistics.stdev(self.daily_returns)
            sharpe_ratio = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0.0
        
        # Sortino ratio (simplified - using downside deviation)
        sortino_ratio = 0.0
        if self.daily_returns and len(self.daily_returns) > 1:
            downside_returns = [r for r in self.daily_returns if r < 0]
            if downside_returns and len(downside_returns) > 1:
                downside_dev = statistics.stdev(downside_returns)
                avg_return = statistics.mean(self.daily_returns)
                sortino_ratio = (avg_return / downside_dev * (252 ** 0.5)) if downside_dev > 0 else 0.0
        
        # Drawdown calculations
        current_drawdown = ((self.peak_equity - current_equity) / self.peak_equity * 100) if self.peak_equity > 0 else 0.0
        max_drawdown = self._calculate_max_drawdown()
        
        # Calmar ratio
        annualized_return = ((current_equity / self.initial_capital) ** (365 / max(1, (datetime.now() - self.start_time).days)) - 1) * 100
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0.0
        
        # Activity metrics
        days_active = max(1, (datetime.now() - self.start_time).days)
        trades_per_day = total_trades / days_active
        uptime_hours = (datetime.now() - self.start_time).total_seconds() / 3600
        
        # Portfolio metrics
        account_growth = ((current_equity - self.initial_capital) / self.initial_capital * 100) if self.initial_capital > 0 else 0.0
        roi_percentage = account_growth
        profit_per_trade = net_profit / total_trades if total_trades > 0 else 0.0
        
        # Strategy metrics
        active_strategies = len(self.strategy_performance)
        best_strategy = self._get_best_strategy()
        worst_strategy = self._get_worst_strategy()
        
        snapshot = KPISnapshot(
            timestamp=datetime.now().isoformat(),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_profit=total_profit,
            total_loss=total_loss,
            net_profit=net_profit,
            total_fees=total_fees,
            average_win=average_win,
            average_loss=average_loss,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            calmar_ratio=calmar_ratio,
            expectancy=expectancy,
            risk_reward_ratio=risk_reward_ratio,
            profit_per_trade=profit_per_trade,
            roi_percentage=roi_percentage,
            trades_per_day=trades_per_day,
            active_days=days_active,
            uptime_hours=uptime_hours,
            account_balance=current_balance,
            account_equity=current_equity,
            account_growth=account_growth,
            active_strategies=active_strategies,
            best_strategy=best_strategy,
            worst_strategy=worst_strategy
        )
        
        self.snapshots.append(snapshot)
        self._save_data()
        
        return snapshot
    
    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown from equity curve"""
        if not self.equity_curve or len(self.equity_curve) < 2:
            return 0.0
        
        max_dd = 0.0
        peak = self.equity_curve[0]
        
        for equity in self.equity_curve:
            if equity > peak:
                peak = equity
            # Protect against division by zero
            if peak > 0:
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        
        return max_dd
    
    def _get_best_strategy(self) -> str:
        """Get best performing strategy by net profit"""
        if not self.strategy_performance:
            return "N/A"
        
        best = max(
            self.strategy_performance.items(),
            key=lambda x: x[1]['total_profit'] - x[1]['total_loss']
        )
        return best[0]
    
    def _get_worst_strategy(self) -> str:
        """Get worst performing strategy by net profit"""
        if not self.strategy_performance:
            return "N/A"
        
        worst = min(
            self.strategy_performance.items(),
            key=lambda x: x[1]['total_profit'] - x[1]['total_loss']
        )
        return worst[0]
    
    def get_kpi_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive KPI summary.
        
        Returns:
            Dictionary with current KPIs
        """
        if not self.snapshots:
            return {'error': 'No KPI data available'}
        
        latest = self.snapshots[-1]
        return asdict(latest)
    
    def get_kpi_trends(self, days: int = 30) -> Dict[str, List]:
        """
        Get KPI trends over time.
        
        Args:
            days: Number of days to include
            
        Returns:
            Dictionary with KPI time series
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent_snapshots = [
            s for s in self.snapshots
            if datetime.fromisoformat(s.timestamp) >= cutoff
        ]
        
        if not recent_snapshots:
            return {'error': 'No data available for specified period'}
        
        return {
            'timestamps': [s.timestamp for s in recent_snapshots],
            'win_rate': [s.win_rate for s in recent_snapshots],
            'profit_factor': [s.profit_factor for s in recent_snapshots],
            'sharpe_ratio': [s.sharpe_ratio for s in recent_snapshots],
            'account_equity': [s.account_equity for s in recent_snapshots],
            'drawdown': [s.current_drawdown for s in recent_snapshots],
            'roi': [s.roi_percentage for s in recent_snapshots]
        }
    
    def export_kpis(self, output_file: str = None) -> str:
        """
        Export KPIs to JSON file.
        
        Args:
            output_file: Output file path (optional)
            
        Returns:
            Path to exported file
        """
        if output_file is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = str(self.data_dir / f"kpi_export_{timestamp}.json")
        
        export_data = {
            'export_date': datetime.now().isoformat(),
            'initial_capital': self.initial_capital,
            'current_kpis': self.get_kpi_summary(),
            'kpi_history': [asdict(s) for s in self.snapshots],
            'strategy_performance': dict(self.strategy_performance),
            'trade_count': len(self.trade_history)
        }
        
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"📄 KPIs exported to {output_file}")
        return output_file


# Global KPI tracker instance
_kpi_tracker: Optional[KPITracker] = None


def get_kpi_tracker(initial_capital: float = 1000.0, reset: bool = False) -> KPITracker:
    """
    Get or create the global KPI tracker instance.
    
    Args:
        initial_capital: Initial capital (only used on first creation)
        reset: Force reset and create new instance
        
    Returns:
        KPITracker instance
    """
    global _kpi_tracker
    
    if _kpi_tracker is None or reset:
        _kpi_tracker = KPITracker(initial_capital=initial_capital)
    
    return _kpi_tracker


if __name__ == "__main__":
    # Test the KPI tracker
    logging.basicConfig(level=logging.INFO)
    
    print("Testing KPI Tracker...")
    
    tracker = get_kpi_tracker(initial_capital=1000.0)
    
    # Simulate some trades
    tracker.record_trade("BTC-USD", "APEX_V71", 50.0, 1.0, True, 45000, 46000, 0.1)
    tracker.update_balance(1049.0, 1049.0)
    
    tracker.record_trade("ETH-USD", "DUAL_RSI", -25.0, 1.0, False, 3000, 2950, 1.0)
    tracker.update_balance(1023.0, 1023.0)
    
    tracker.record_trade("SOL-USD", "APEX_V71", 75.0, 1.0, True, 120, 125, 10.0)
    tracker.update_balance(1097.0, 1097.0)
    
    # Calculate KPIs
    kpis = tracker.calculate_kpis(1097.0, 1097.0)
    
    # Print summary
    print("\n" + "="*70)
    print("KPI SUMMARY")
    print("="*70)
    print(f"Total Trades: {kpis.total_trades}")
    print(f"Win Rate: {kpis.win_rate:.1f}%")
    print(f"Profit Factor: {kpis.profit_factor:.2f}")
    print(f"Net Profit: ${kpis.net_profit:.2f}")
    print(f"ROI: {kpis.roi_percentage:.2f}%")
    print(f"Sharpe Ratio: {kpis.sharpe_ratio:.2f}")
    print(f"Best Strategy: {kpis.best_strategy}")
    print("="*70)
    
    # Export KPIs
    export_path = tracker.export_kpis()
    print(f"\n✅ KPI tracker test complete! Data exported to {export_path}")
