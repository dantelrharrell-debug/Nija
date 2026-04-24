"""
NIJA Paper Trading Analytics System

Comprehensive analytics for paper trading to collect data and evaluate strategy performance.
This system supports the 3-phase process:
1. Run paper trading with analytics ON (collect 100-300 trades)
2. Kill losers ruthlessly (disable underperforming signal types and exits)
3. Lock a "profit-ready" definition (define and validate profitability criteria)

Features:
- Signal type performance tracking (RSI, breakout, trend, etc.)
- Exit strategy performance tracking (profit target, stop loss, trailing, etc.)
- Trade-by-trade analytics with full context
- Performance quartile analysis
- Automatic underperformer identification
- Profitability criteria validation

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from collections import defaultdict
import numpy as np

logger = logging.getLogger("nija.paper_analytics")


class SignalType(Enum):
    """Types of entry signals"""
    DUAL_RSI = "dual_rsi"  # RSI_9 + RSI_14
    RSI_OVERSOLD = "rsi_oversold"  # Single RSI oversold
    RSI_OVERBOUGHT = "rsi_overbought"  # Single RSI overbought
    BREAKOUT = "breakout"  # Price breakout
    TREND_FOLLOWING = "trend_following"  # Momentum trend
    MEAN_REVERSION = "mean_reversion"  # Mean reversion
    VOLATILITY_EXPANSION = "volatility_expansion"  # Volatility-based
    WEBHOOK = "webhook"  # TradingView webhook


class ExitReason(Enum):
    """Types of exit strategies"""
    PROFIT_TARGET = "profit_target"  # Hit profit target
    STOP_LOSS = "stop_loss"  # Hit stop loss
    TRAILING_STOP = "trailing_stop"  # Trailing stop hit
    PARTIAL_PROFIT = "partial_profit"  # Partial profit taking
    TIME_EXIT = "time_exit"  # Time-based exit
    SIGNAL_REVERSAL = "signal_reversal"  # Opposite signal
    MANUAL = "manual"  # Manual exit


@dataclass
class TradeAnalytics:
    """Detailed analytics for a single trade"""
    trade_id: str
    timestamp: str
    symbol: str
    
    # Entry details
    signal_type: str  # SignalType
    entry_price: float
    entry_size_usd: float
    entry_time: str
    
    # Exit details
    exit_reason: str  # ExitReason
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    
    # Performance
    gross_pnl: float = 0.0
    net_pnl: float = 0.0  # After fees
    pnl_pct: float = 0.0
    duration_minutes: float = 0.0
    
    # Risk metrics
    max_favorable_excursion: float = 0.0  # MFE - best price reached
    max_adverse_excursion: float = 0.0  # MAE - worst price reached
    risk_reward_ratio: float = 0.0
    
    # Market context
    market_regime: str = "unknown"  # trending, ranging, volatile
    scan_time_seconds: float = 0.0
    
    # Strategy context
    rsi_9: Optional[float] = None
    rsi_14: Optional[float] = None
    volatility: Optional[float] = None


@dataclass
class SignalPerformance:
    """Performance metrics for a specific signal type"""
    signal_type: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_duration_minutes: float = 0.0
    sharpe_ratio: float = 0.0
    enabled: bool = True  # Can be disabled if underperforming


@dataclass
class ExitPerformance:
    """Performance metrics for a specific exit strategy"""
    exit_reason: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    capital_allocation_pct: float = 100.0  # Can be reduced for underperformers


@dataclass
class ProfitReadyCriteria:
    """Criteria for determining if bot is profit-ready for live trading"""
    # Return criteria
    min_total_return_pct: float = 5.0  # Minimum 5% return
    min_trades: int = 100  # Minimum trades to evaluate
    max_trades: int = 300  # Maximum trades before requiring decision
    
    # Risk criteria
    max_drawdown_pct: float = 15.0  # Maximum 15% drawdown
    min_sharpe_ratio: float = 1.0  # Minimum Sharpe ratio
    
    # Performance criteria
    min_win_rate: float = 45.0  # Minimum 45% win rate
    min_profit_factor: float = 1.5  # Minimum 1.5 profit factor
    
    # Operational criteria
    max_scan_time_seconds: float = 30.0  # Maximum scan time
    min_utilization_pct: float = 60.0  # Minimum capital utilization
    max_utilization_pct: float = 80.0  # Maximum capital utilization
    
    # Time criteria
    min_days_trading: int = 14  # Minimum 14 days of data


@dataclass
class ProfitReadyStatus:
    """Status of profit-ready validation"""
    is_ready: bool
    criteria_met: Dict[str, bool] = field(default_factory=dict)
    criteria_values: Dict[str, float] = field(default_factory=dict)
    message: str = ""
    timestamp: str = ""


class PaperTradingAnalytics:
    """
    Comprehensive analytics system for paper trading
    
    Tracks:
    - Individual trade performance with full context
    - Signal type performance (to identify winners/losers)
    - Exit strategy performance (to optimize exits)
    - Overall system performance
    - Profitability criteria validation
    """
    
    def __init__(self, data_dir: str = "./data/paper_analytics"):
        """
        Initialize analytics system
        
        Args:
            data_dir: Directory to store analytics data
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        
        # Data files
        self.trades_file = self.data_dir / "trades_analytics.json"
        self.signals_file = self.data_dir / "signal_performance.json"
        self.exits_file = self.data_dir / "exit_performance.json"
        self.criteria_file = self.data_dir / "profit_ready_criteria.json"
        self.disabled_signals_file = self.data_dir / "disabled_signals.json"
        
        # In-memory data
        self.trades: List[TradeAnalytics] = []
        self.signal_performance: Dict[str, SignalPerformance] = {}
        self.exit_performance: Dict[str, ExitPerformance] = {}
        self.profit_criteria = ProfitReadyCriteria()
        self.disabled_signals: List[str] = []
        
        # Load existing data
        self._load_data()
        
        logger.info(f"✅ Paper Trading Analytics initialized")
        logger.info(f"   Trades recorded: {len(self.trades)}")
        logger.info(f"   Signal types tracked: {len(self.signal_performance)}")
        logger.info(f"   Exit strategies tracked: {len(self.exit_performance)}")
    
    def record_trade(self, trade: TradeAnalytics) -> None:
        """
        Record a completed trade with full analytics
        
        Args:
            trade: TradeAnalytics object with trade details
        """
        self.trades.append(trade)
        
        # Update signal performance
        self._update_signal_performance(trade)
        
        # Update exit performance
        self._update_exit_performance(trade)
        
        # Save data
        self._save_data()
        
        logger.info(f"📊 Trade recorded: {trade.symbol} | Signal: {trade.signal_type} | "
                   f"Exit: {trade.exit_reason} | P&L: ${trade.net_pnl:+.2f}")
    
    def _update_signal_performance(self, trade: TradeAnalytics) -> None:
        """Update performance metrics for the signal type"""
        signal_type = trade.signal_type
        
        if signal_type not in self.signal_performance:
            self.signal_performance[signal_type] = SignalPerformance(
                signal_type=signal_type
            )
        
        perf = self.signal_performance[signal_type]
        perf.total_trades += 1
        
        if trade.net_pnl > 0:
            perf.winning_trades += 1
        elif trade.net_pnl < 0:
            perf.losing_trades += 1
        
        perf.total_pnl += trade.net_pnl
        
        # Recalculate aggregates
        self._recalculate_signal_metrics(signal_type)
    
    def _update_exit_performance(self, trade: TradeAnalytics) -> None:
        """Update performance metrics for the exit strategy"""
        exit_reason = trade.exit_reason
        
        if exit_reason not in self.exit_performance:
            self.exit_performance[exit_reason] = ExitPerformance(
                exit_reason=exit_reason
            )
        
        perf = self.exit_performance[exit_reason]
        perf.total_trades += 1
        
        if trade.net_pnl > 0:
            perf.winning_trades += 1
        elif trade.net_pnl < 0:
            perf.losing_trades += 1
        
        perf.total_pnl += trade.net_pnl
        
        # Recalculate aggregates
        self._recalculate_exit_metrics(exit_reason)
    
    def _recalculate_signal_metrics(self, signal_type: str) -> None:
        """Recalculate all metrics for a signal type"""
        perf = self.signal_performance[signal_type]
        
        # Get all trades for this signal
        signal_trades = [t for t in self.trades if t.signal_type == signal_type]
        
        if not signal_trades:
            return
        
        # Calculate metrics
        wins = [t.net_pnl for t in signal_trades if t.net_pnl > 0]
        losses = [t.net_pnl for t in signal_trades if t.net_pnl < 0]
        
        perf.avg_pnl = perf.total_pnl / perf.total_trades if perf.total_trades > 0 else 0.0
        perf.win_rate = (perf.winning_trades / perf.total_trades * 100) if perf.total_trades > 0 else 0.0
        perf.avg_win = np.mean(wins) if wins else 0.0
        perf.avg_loss = np.mean(losses) if losses else 0.0
        perf.best_trade = max(wins) if wins else 0.0
        perf.worst_trade = min(losses) if losses else 0.0
        
        # Profit factor
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        perf.profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
        
        # Average duration
        durations = [t.duration_minutes for t in signal_trades if t.duration_minutes > 0]
        perf.avg_duration_minutes = np.mean(durations) if durations else 0.0
        
        # Sharpe ratio (simplified - using trade returns)
        returns = [t.pnl_pct for t in signal_trades]
        if len(returns) > 1:
            perf.sharpe_ratio = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if np.std(returns) > 0 else 0.0
        else:
            perf.sharpe_ratio = 0.0
    
    def _recalculate_exit_metrics(self, exit_reason: str) -> None:
        """Recalculate all metrics for an exit strategy"""
        perf = self.exit_performance[exit_reason]
        
        # Get all trades for this exit
        exit_trades = [t for t in self.trades if t.exit_reason == exit_reason]
        
        if not exit_trades:
            return
        
        # Calculate metrics
        wins = [t.net_pnl for t in exit_trades if t.net_pnl > 0]
        losses = [t.net_pnl for t in exit_trades if t.net_pnl < 0]
        
        perf.avg_pnl = perf.total_pnl / perf.total_trades if perf.total_trades > 0 else 0.0
        perf.win_rate = (perf.winning_trades / perf.total_trades * 100) if perf.total_trades > 0 else 0.0
        perf.avg_win = np.mean(wins) if wins else 0.0
        perf.avg_loss = np.mean(losses) if losses else 0.0
        
        # Profit factor
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        perf.profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
    
    def identify_underperformers(self, percentile: float = 25.0) -> Dict[str, List[str]]:
        """
        Identify underperforming signals and exits (bottom quartile)
        
        Args:
            percentile: Bottom percentile to identify as underperformers (default: 25 = bottom quartile)
        
        Returns:
            Dictionary with 'signals' and 'exits' lists of underperformers
        """
        underperformers = {'signals': [], 'exits': []}
        
        # Identify underperforming signals
        if self.signal_performance:
            # Rank by profit factor
            sorted_signals = sorted(
                self.signal_performance.items(),
                key=lambda x: x[1].profit_factor
            )
            
            # Get bottom percentile
            cutoff_idx = max(1, int(len(sorted_signals) * (percentile / 100)))
            bottom_signals = sorted_signals[:cutoff_idx]
            
            for signal_type, perf in bottom_signals:
                # Also check if losing money overall
                if perf.total_pnl < 0 or perf.win_rate < 40.0 or perf.profit_factor < 1.0:
                    underperformers['signals'].append(signal_type)
                    logger.warning(f"⚠️ Underperforming signal: {signal_type} | "
                                  f"Win rate: {perf.win_rate:.1f}% | "
                                  f"Profit factor: {perf.profit_factor:.2f} | "
                                  f"Total P&L: ${perf.total_pnl:+.2f}")
        
        # Identify underperforming exits
        if self.exit_performance:
            # Rank by profit factor
            sorted_exits = sorted(
                self.exit_performance.items(),
                key=lambda x: x[1].profit_factor
            )
            
            # Get bottom percentile
            cutoff_idx = max(1, int(len(sorted_exits) * (percentile / 100)))
            bottom_exits = sorted_exits[:cutoff_idx]
            
            for exit_reason, perf in bottom_exits:
                # Also check if losing money overall
                if perf.total_pnl < 0 or perf.win_rate < 40.0:
                    underperformers['exits'].append(exit_reason)
                    logger.warning(f"⚠️ Underperforming exit: {exit_reason} | "
                                  f"Win rate: {perf.win_rate:.1f}% | "
                                  f"Profit factor: {perf.profit_factor:.2f} | "
                                  f"Total P&L: ${perf.total_pnl:+.2f}")
        
        return underperformers
    
    def disable_underperformers(self, signal_types: List[str]) -> None:
        """
        Disable underperforming signal types
        
        Args:
            signal_types: List of signal types to disable
        """
        for signal_type in signal_types:
            if signal_type in self.signal_performance:
                self.signal_performance[signal_type].enabled = False
                if signal_type not in self.disabled_signals:
                    self.disabled_signals.append(signal_type)
                logger.info(f"🚫 Disabled signal type: {signal_type}")
        
        self._save_data()
    
    def reduce_exit_allocation(self, exit_reasons: List[str], reduction_pct: float = 50.0) -> None:
        """
        Reduce capital allocation for underperforming exits
        
        Args:
            exit_reasons: List of exit strategies to reduce
            reduction_pct: Percentage to reduce (default: 50%)
        """
        for exit_reason in exit_reasons:
            if exit_reason in self.exit_performance:
                current = self.exit_performance[exit_reason].capital_allocation_pct
                new_allocation = current * (1 - reduction_pct / 100)
                self.exit_performance[exit_reason].capital_allocation_pct = new_allocation
                logger.info(f"📉 Reduced allocation for {exit_reason}: {current:.0f}% → {new_allocation:.0f}%")
        
        self._save_data()
    
    def promote_top_performers(self, percentile: float = 75.0) -> Dict[str, List[str]]:
        """
        Identify top-performing signals and exits (top quartile)
        
        Args:
            percentile: Top percentile to identify as performers (default: 75 = top quartile)
        
        Returns:
            Dictionary with 'signals' and 'exits' lists of top performers
        """
        top_performers = {'signals': [], 'exits': []}
        
        # Identify top signals
        if self.signal_performance:
            sorted_signals = sorted(
                self.signal_performance.items(),
                key=lambda x: x[1].profit_factor,
                reverse=True
            )
            
            cutoff_idx = max(1, int(len(sorted_signals) * ((100 - percentile) / 100)))
            top_signals = sorted_signals[:cutoff_idx]
            
            for signal_type, perf in top_signals:
                if perf.profit_factor > 1.5 and perf.win_rate > 50.0:
                    top_performers['signals'].append(signal_type)
                    logger.info(f"🌟 Top performing signal: {signal_type} | "
                               f"Win rate: {perf.win_rate:.1f}% | "
                               f"Profit factor: {perf.profit_factor:.2f} | "
                               f"Total P&L: ${perf.total_pnl:+.2f}")
        
        # Identify top exits
        if self.exit_performance:
            sorted_exits = sorted(
                self.exit_performance.items(),
                key=lambda x: x[1].profit_factor,
                reverse=True
            )
            
            cutoff_idx = max(1, int(len(sorted_exits) * ((100 - percentile) / 100)))
            top_exits = sorted_exits[:cutoff_idx]
            
            for exit_reason, perf in top_exits:
                if perf.profit_factor > 1.5 and perf.win_rate > 50.0:
                    top_performers['exits'].append(exit_reason)
                    logger.info(f"🌟 Top performing exit: {exit_reason} | "
                               f"Win rate: {perf.win_rate:.1f}% | "
                               f"Profit factor: {perf.profit_factor:.2f} | "
                               f"Total P&L: ${perf.total_pnl:+.2f}")
        
        return top_performers
    
    def validate_profit_ready(self, criteria: Optional[ProfitReadyCriteria] = None) -> ProfitReadyStatus:
        """
        Validate if the bot meets profit-ready criteria
        
        Args:
            criteria: Optional custom criteria (uses default if not provided)
        
        Returns:
            ProfitReadyStatus with validation results
        """
        if criteria is None:
            criteria = self.profit_criteria
        
        status = ProfitReadyStatus(
            is_ready=False,
            timestamp=datetime.now().isoformat()
        )
        
        # Need minimum trades
        total_trades = len(self.trades)
        status.criteria_values['total_trades'] = total_trades
        status.criteria_met['min_trades'] = total_trades >= criteria.min_trades
        
        if total_trades < criteria.min_trades:
            status.message = f"Need {criteria.min_trades - total_trades} more trades (have {total_trades})"
            return status
        
        # Calculate overall metrics
        if total_trades > 0:
            total_pnl = sum(t.net_pnl for t in self.trades)
            wins = [t.net_pnl for t in self.trades if t.net_pnl > 0]
            losses = [t.net_pnl for t in self.trades if t.net_pnl < 0]
            
            # Win rate
            win_rate = (len(wins) / total_trades * 100)
            status.criteria_values['win_rate'] = win_rate
            status.criteria_met['min_win_rate'] = win_rate >= criteria.min_win_rate
            
            # Profit factor
            gross_profit = sum(wins) if wins else 0.0
            gross_loss = abs(sum(losses)) if losses else 0.0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
            status.criteria_values['profit_factor'] = profit_factor
            status.criteria_met['min_profit_factor'] = profit_factor >= criteria.min_profit_factor
            
            # Total return (estimate based on P&L vs initial capital)
            # Assuming 10k initial capital for percentage calculation
            total_return_pct = (total_pnl / 10000) * 100
            status.criteria_values['total_return_pct'] = total_return_pct
            status.criteria_met['min_total_return'] = total_return_pct >= criteria.min_total_return_pct
            
            # Drawdown (simplified - using cumulative P&L)
            cumulative_pnl = []
            running_total = 0
            for trade in self.trades:
                running_total += trade.net_pnl
                cumulative_pnl.append(running_total)
            
            peak = 0
            max_drawdown = 0
            for pnl in cumulative_pnl:
                if pnl > peak:
                    peak = pnl
                dd = ((peak - pnl) / max(peak, 1)) * 100
                if dd > max_drawdown:
                    max_drawdown = dd
            
            status.criteria_values['max_drawdown_pct'] = max_drawdown
            status.criteria_met['max_drawdown'] = max_drawdown <= criteria.max_drawdown_pct
            
            # Sharpe ratio
            returns = [t.pnl_pct for t in self.trades]
            if len(returns) > 1:
                sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if np.std(returns) > 0 else 0.0
            else:
                sharpe = 0.0
            status.criteria_values['sharpe_ratio'] = sharpe
            status.criteria_met['min_sharpe_ratio'] = sharpe >= criteria.min_sharpe_ratio
            
            # Scan time (average from trades that have it)
            scan_times = [t.scan_time_seconds for t in self.trades if t.scan_time_seconds > 0]
            avg_scan_time = np.mean(scan_times) if scan_times else 0.0
            status.criteria_values['avg_scan_time_seconds'] = avg_scan_time
            status.criteria_met['max_scan_time'] = avg_scan_time <= criteria.max_scan_time_seconds or avg_scan_time == 0
            
            # Days trading (estimate from first to last trade)
            if len(self.trades) >= 2:
                first_trade = datetime.fromisoformat(self.trades[0].timestamp)
                last_trade = datetime.fromisoformat(self.trades[-1].timestamp)
                days_trading = (last_trade - first_trade).days
            else:
                days_trading = 0
            status.criteria_values['days_trading'] = days_trading
            status.criteria_met['min_days_trading'] = days_trading >= criteria.min_days_trading
        
        # Check if all criteria met
        all_met = all(status.criteria_met.values())
        status.is_ready = all_met
        
        if all_met:
            status.message = "✅ All profit-ready criteria met! Ready for live trading."
        else:
            failed = [k for k, v in status.criteria_met.items() if not v]
            status.message = f"⚠️ Criteria not met: {', '.join(failed)}"
        
        logger.info(f"Profit-Ready Validation: {status.message}")
        
        return status
    
    def generate_report(self) -> Dict:
        """
        Generate comprehensive analytics report
        
        Returns:
            Dictionary with full analytics report
        """
        total_trades = len(self.trades)
        
        if total_trades == 0:
            return {
                'error': 'No trades recorded yet',
                'message': 'Start paper trading to collect data'
            }
        
        # Overall performance
        total_pnl = sum(t.net_pnl for t in self.trades)
        wins = [t for t in self.trades if t.net_pnl > 0]
        losses = [t for t in self.trades if t.net_pnl < 0]
        
        # Signal performance summary
        signal_summary = {}
        for signal_type, perf in self.signal_performance.items():
            signal_summary[signal_type] = {
                'total_trades': perf.total_trades,
                'win_rate': perf.win_rate,
                'profit_factor': perf.profit_factor,
                'total_pnl': perf.total_pnl,
                'avg_pnl': perf.avg_pnl,
                'sharpe_ratio': perf.sharpe_ratio,
                'enabled': perf.enabled
            }
        
        # Exit performance summary
        exit_summary = {}
        for exit_reason, perf in self.exit_performance.items():
            exit_summary[exit_reason] = {
                'total_trades': perf.total_trades,
                'win_rate': perf.win_rate,
                'profit_factor': perf.profit_factor,
                'total_pnl': perf.total_pnl,
                'avg_pnl': perf.avg_pnl,
                'capital_allocation_pct': perf.capital_allocation_pct
            }
        
        # Profit-ready validation
        profit_ready_status = self.validate_profit_ready()
        
        return {
            'summary': {
                'total_trades': total_trades,
                'total_pnl': total_pnl,
                'win_rate': (len(wins) / total_trades * 100) if total_trades > 0 else 0,
                'avg_pnl_per_trade': total_pnl / total_trades if total_trades > 0 else 0
            },
            'signal_performance': signal_summary,
            'exit_performance': exit_summary,
            'profit_ready_status': {
                'is_ready': profit_ready_status.is_ready,
                'criteria_met': profit_ready_status.criteria_met,
                'criteria_values': profit_ready_status.criteria_values,
                'message': profit_ready_status.message
            },
            'disabled_signals': self.disabled_signals,
            'generated_at': datetime.now().isoformat()
        }
    
    def _load_data(self) -> None:
        """Load analytics data from disk"""
        # Load trades
        if self.trades_file.exists():
            try:
                with open(self.trades_file, 'r') as f:
                    data = json.load(f)
                    self.trades = [TradeAnalytics(**t) for t in data]
            except Exception as e:
                logger.warning(f"Could not load trades: {e}")
        
        # Load signal performance
        if self.signals_file.exists():
            try:
                with open(self.signals_file, 'r') as f:
                    data = json.load(f)
                    self.signal_performance = {
                        k: SignalPerformance(**v) for k, v in data.items()
                    }
            except Exception as e:
                logger.warning(f"Could not load signal performance: {e}")
        
        # Load exit performance
        if self.exits_file.exists():
            try:
                with open(self.exits_file, 'r') as f:
                    data = json.load(f)
                    self.exit_performance = {
                        k: ExitPerformance(**v) for k, v in data.items()
                    }
            except Exception as e:
                logger.warning(f"Could not load exit performance: {e}")
        
        # Load profit criteria
        if self.criteria_file.exists():
            try:
                with open(self.criteria_file, 'r') as f:
                    data = json.load(f)
                    self.profit_criteria = ProfitReadyCriteria(**data)
            except Exception as e:
                logger.warning(f"Could not load profit criteria: {e}")
        
        # Load disabled signals
        if self.disabled_signals_file.exists():
            try:
                with open(self.disabled_signals_file, 'r') as f:
                    self.disabled_signals = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load disabled signals: {e}")
    
    def _save_data(self) -> None:
        """Save analytics data to disk"""
        try:
            # Save trades
            with open(self.trades_file, 'w') as f:
                json.dump([asdict(t) for t in self.trades], f, indent=2)
            
            # Save signal performance
            with open(self.signals_file, 'w') as f:
                json.dump(
                    {k: asdict(v) for k, v in self.signal_performance.items()},
                    f, indent=2
                )
            
            # Save exit performance
            with open(self.exits_file, 'w') as f:
                json.dump(
                    {k: asdict(v) for k, v in self.exit_performance.items()},
                    f, indent=2
                )
            
            # Save profit criteria
            with open(self.criteria_file, 'w') as f:
                json.dump(asdict(self.profit_criteria), f, indent=2)
            
            # Save disabled signals
            with open(self.disabled_signals_file, 'w') as f:
                json.dump(self.disabled_signals, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save analytics data: {e}")


# Singleton instance
_analytics_instance: Optional[PaperTradingAnalytics] = None


def get_analytics(data_dir: str = "./data/paper_analytics") -> PaperTradingAnalytics:
    """
    Get or create the analytics singleton
    
    Args:
        data_dir: Directory for analytics data
    
    Returns:
        PaperTradingAnalytics instance
    """
    global _analytics_instance
    
    if _analytics_instance is None:
        _analytics_instance = PaperTradingAnalytics(data_dir)
    
    return _analytics_instance
