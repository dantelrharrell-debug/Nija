"""
NIJA Profit Proven Rule System
================================

Implements formal "profit proven" criteria to validate strategy performance
before enabling live trading with real capital.

Profit Proven Criteria (default):
- Time window: 24 hours minimum
- Trade count: 50 trades minimum
- Net profit: +5% minimum (after all fees)

The system tracks performance in real-time and determines when a strategy
has "proven" itself profitable according to objective metrics.

Author: NIJA Trading Systems
Version: 1.0
Date: February 6, 2026
"""

import logging
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import json

logger = logging.getLogger("nija.profit_proven")


class ProfitProvenStatus(Enum):
    """Status of profit proven validation"""
    NOT_STARTED = "not_started"  # No trades yet
    IN_PROGRESS = "in_progress"  # Accumulating data
    PROVEN = "proven"  # Met all criteria
    FAILED = "failed"  # Failed to meet criteria


@dataclass
class ProfitProvenCriteria:
    """
    Criteria for determining if a strategy is "profit proven".
    
    Attributes:
        min_time_hours: Minimum time window in hours (default: 24)
        min_trades: Minimum number of trades (default: 50)
        min_net_profit_pct: Minimum net profit percentage (default: 5.0%)
        max_drawdown_pct: Maximum allowed drawdown (default: 15.0%)
        min_win_rate_pct: Minimum win rate percentage (default: 45.0%)
    """
    min_time_hours: float = 24.0
    min_trades: int = 50
    min_net_profit_pct: float = 5.0  # 5% net profit
    max_drawdown_pct: float = 15.0  # Max 15% drawdown
    min_win_rate_pct: float = 45.0  # Min 45% win rate
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)
    
    def __str__(self) -> str:
        """Human-readable criteria"""
        return (f"Profit Proven Criteria: "
                f"{self.min_time_hours}h, "
                f"{self.min_trades} trades, "
                f"NET ≥{self.min_net_profit_pct}%, "
                f"DD ≤{self.max_drawdown_pct}%, "
                f"WR ≥{self.min_win_rate_pct}%")


@dataclass
class TradeRecord:
    """Individual trade record for profit tracking"""
    trade_id: str
    timestamp: datetime
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    exit_price: float
    position_size_usd: float
    gross_pnl_usd: float
    fees_usd: float
    net_pnl_usd: float
    is_win: bool
    
    def to_dict(self) -> Dict:
        """Convert to dictionary with ISO timestamp"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data


class ProfitProvenTracker:
    """
    Tracks trading performance against profit proven criteria.
    
    Maintains a rolling window of trades and validates against criteria
    to determine if a strategy has "proven" itself profitable.
    """
    
    def __init__(self, criteria: Optional[ProfitProvenCriteria] = None):
        """
        Initialize profit proven tracker.
        
        Args:
            criteria: Custom criteria (uses defaults if None)
        """
        self.criteria = criteria or ProfitProvenCriteria()
        self.trades: List[TradeRecord] = []
        self.start_time = datetime.now()
        self.initial_capital = 0.0
        self.current_capital = 0.0
        self.peak_capital = 0.0
        self.status = ProfitProvenStatus.NOT_STARTED
        
        logger.info("✅ Profit Proven Tracker initialized")
        logger.info(f"   {self.criteria}")
    
    def set_initial_capital(self, capital: float) -> None:
        """Set initial capital for profit calculations"""
        self.initial_capital = capital
        self.current_capital = capital
        self.peak_capital = capital
        logger.info(f"Initial capital set: ${capital:.2f}")
    
    def record_trade(self, trade: TradeRecord) -> None:
        """
        Record a completed trade.
        
        Args:
            trade: Trade record to add
        """
        self.trades.append(trade)
        
        # Update capital tracking
        self.current_capital += trade.net_pnl_usd
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital
        
        # Update status
        if self.status == ProfitProvenStatus.NOT_STARTED:
            self.status = ProfitProvenStatus.IN_PROGRESS
        
        logger.info(f"Trade recorded: {trade.symbol} {trade.side} "
                   f"NET P&L: ${trade.net_pnl_usd:.2f} "
                   f"(Total: {len(self.trades)} trades)")
    
    def get_window_trades(self, hours: Optional[float] = None) -> List[TradeRecord]:
        """
        Get trades within time window.
        
        Args:
            hours: Time window in hours (uses criteria default if None)
        
        Returns:
            List of trades within window
        """
        if hours is None:
            hours = self.criteria.min_time_hours
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [t for t in self.trades if t.timestamp >= cutoff_time]
    
    def calculate_metrics(self, window_hours: Optional[float] = None) -> Dict:
        """
        Calculate performance metrics.
        
        Args:
            window_hours: Time window (uses criteria default if None)
        
        Returns:
            Dict with metrics: trades, win_rate, net_profit_pct, drawdown_pct, etc.
        """
        window_trades = self.get_window_trades(window_hours)
        
        if not window_trades:
            return {
                'trade_count': 0,
                'win_count': 0,
                'loss_count': 0,
                'win_rate_pct': 0.0,
                'gross_profit_usd': 0.0,
                'total_fees_usd': 0.0,
                'net_profit_usd': 0.0,
                'net_profit_pct': 0.0,
                'drawdown_pct': 0.0,
                'time_elapsed_hours': 0.0,
            }
        
        # Count wins/losses
        wins = [t for t in window_trades if t.is_win]
        losses = [t for t in window_trades if not t.is_win]
        
        # Calculate totals
        gross_profit = sum(t.gross_pnl_usd for t in window_trades)
        total_fees = sum(t.fees_usd for t in window_trades)
        net_profit = sum(t.net_pnl_usd for t in window_trades)
        
        # Calculate percentages
        win_rate_pct = (len(wins) / len(window_trades)) * 100 if window_trades else 0
        
        # Net profit percentage (relative to initial capital)
        net_profit_pct = 0.0
        if self.initial_capital > 0:
            net_profit_pct = (net_profit / self.initial_capital) * 100
        
        # Drawdown calculation
        drawdown_pct = 0.0
        if self.peak_capital > 0:
            drawdown = self.peak_capital - self.current_capital
            drawdown_pct = (drawdown / self.peak_capital) * 100
        
        # Time elapsed
        time_elapsed = datetime.now() - self.start_time
        time_elapsed_hours = time_elapsed.total_seconds() / 3600
        
        return {
            'trade_count': len(window_trades),
            'win_count': len(wins),
            'loss_count': len(losses),
            'win_rate_pct': win_rate_pct,
            'gross_profit_usd': gross_profit,
            'total_fees_usd': total_fees,
            'net_profit_usd': net_profit,
            'net_profit_pct': net_profit_pct,
            'drawdown_pct': drawdown_pct,
            'time_elapsed_hours': time_elapsed_hours,
            'initial_capital': self.initial_capital,
            'current_capital': self.current_capital,
            'peak_capital': self.peak_capital,
        }
    
    def check_profit_proven(self) -> Tuple[bool, ProfitProvenStatus, Dict]:
        """
        Check if strategy meets profit proven criteria.
        
        Returns:
            Tuple of (is_proven, status, metrics)
        """
        metrics = self.calculate_metrics()
        
        # Check each criterion
        checks = {
            'time_requirement': metrics['time_elapsed_hours'] >= self.criteria.min_time_hours,
            'trade_count_requirement': metrics['trade_count'] >= self.criteria.min_trades,
            'profit_requirement': metrics['net_profit_pct'] >= self.criteria.min_net_profit_pct,
            'drawdown_requirement': metrics['drawdown_pct'] <= self.criteria.max_drawdown_pct,
            'win_rate_requirement': metrics['win_rate_pct'] >= self.criteria.min_win_rate_pct,
        }
        
        # All criteria must pass
        all_passed = all(checks.values())
        
        # Determine status
        if not self.trades:
            status = ProfitProvenStatus.NOT_STARTED
        elif all_passed:
            status = ProfitProvenStatus.PROVEN
        elif metrics['time_elapsed_hours'] >= self.criteria.min_time_hours:
            # Time is up but didn't meet criteria
            status = ProfitProvenStatus.FAILED
        else:
            # Still accumulating data
            status = ProfitProvenStatus.IN_PROGRESS
        
        self.status = status
        
        # Add check results to metrics
        metrics['checks'] = checks
        metrics['status'] = status.value
        metrics['is_proven'] = all_passed
        
        return (all_passed, status, metrics)
    
    def get_progress_report(self) -> str:
        """
        Get human-readable progress report.
        
        Returns:
            Multi-line status report
        """
        is_proven, status, metrics = self.check_profit_proven()
        
        report = [
            "=" * 80,
            "PROFIT PROVEN STATUS REPORT",
            "=" * 80,
            f"Status: {status.value.upper()}",
            "",
            "Criteria vs. Current Performance:",
            f"  Time:       {metrics['time_elapsed_hours']:.1f}h / {self.criteria.min_time_hours}h "
            f"{'✅' if metrics['checks']['time_requirement'] else '⏳'}",
            f"  Trades:     {metrics['trade_count']} / {self.criteria.min_trades} "
            f"{'✅' if metrics['checks']['trade_count_requirement'] else '⏳'}",
            f"  Net Profit: {metrics['net_profit_pct']:.2f}% / {self.criteria.min_net_profit_pct}% "
            f"{'✅' if metrics['checks']['profit_requirement'] else '❌'}",
            f"  Drawdown:   {metrics['drawdown_pct']:.2f}% / {self.criteria.max_drawdown_pct}% max "
            f"{'✅' if metrics['checks']['drawdown_requirement'] else '❌'}",
            f"  Win Rate:   {metrics['win_rate_pct']:.1f}% / {self.criteria.min_win_rate_pct}% "
            f"{'✅' if metrics['checks']['win_rate_requirement'] else '❌'}",
            "",
            "Performance Summary:",
            f"  Wins:        {metrics['win_count']} ({metrics['win_rate_pct']:.1f}%)",
            f"  Losses:      {metrics['loss_count']}",
            f"  Gross P&L:   ${metrics['gross_profit_usd']:.2f}",
            f"  Fees:        ${metrics['total_fees_usd']:.2f}",
            f"  Net P&L:     ${metrics['net_profit_usd']:.2f}",
            f"  Capital:     ${self.initial_capital:.2f} → ${self.current_capital:.2f}",
            "=" * 80,
        ]
        
        if is_proven:
            report.append("✅ PROFIT PROVEN: Strategy has met all criteria!")
        elif status == ProfitProvenStatus.FAILED:
            report.append("❌ PROFIT PROVEN FAILED: Did not meet criteria within time window")
        elif status == ProfitProvenStatus.IN_PROGRESS:
            report.append("⏳ IN PROGRESS: Continue trading to validate profitability")
        
        report.append("=" * 80)
        
        return "\n".join(report)
    
    def export_to_json(self) -> str:
        """Export full state to JSON for audit trail"""
        is_proven, status, metrics = self.check_profit_proven()
        
        export_data = {
            'criteria': self.criteria.to_dict(),
            'status': status.value,
            'is_proven': is_proven,
            'metrics': metrics,
            'timestamp': datetime.now().isoformat(),
            'trades': [t.to_dict() for t in self.trades],
        }
        
        return json.dumps(export_data, indent=2)


# Global tracker instance
_global_tracker: Optional[ProfitProvenTracker] = None


def get_profit_proven_tracker(
    criteria: Optional[ProfitProvenCriteria] = None
) -> ProfitProvenTracker:
    """
    Get or create global profit proven tracker.
    
    Args:
        criteria: Custom criteria (only used on first creation)
    
    Returns:
        Global tracker instance
    """
    global _global_tracker
    
    if _global_tracker is None:
        _global_tracker = ProfitProvenTracker(criteria)
    
    return _global_tracker


__all__ = [
    'ProfitProvenStatus',
    'ProfitProvenCriteria',
    'TradeRecord',
    'ProfitProvenTracker',
    'get_profit_proven_tracker',
]
