"""
NIJA Per-Account Performance Tracker
=====================================

Track expectancy, drawdown, and trade history separately per account.
NEVER aggregate metrics across accounts.

Addresses requirements:
- Track expectancy + drawdown separately per account
- Never aggregate trade histories
- Ensure no cross-contamination between accounts

Author: NIJA Trading Systems
Date: February 17, 2026
Version: 1.0
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
import json
from pathlib import Path

logger = logging.getLogger("nija.account_performance")


@dataclass
class TradeRecord:
    """Individual trade record"""
    trade_id: str
    account_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    entry_price: float
    exit_price: float
    quantity: float
    size_usd: float
    pnl: float
    pnl_pct: float
    fees: float
    net_pnl: float
    entry_time: datetime
    exit_time: datetime
    hold_time_seconds: float
    is_win: bool
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'trade_id': self.trade_id,
            'account_id': self.account_id,
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'quantity': self.quantity,
            'size_usd': self.size_usd,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'fees': self.fees,
            'net_pnl': self.net_pnl,
            'entry_time': self.entry_time.isoformat(),
            'exit_time': self.exit_time.isoformat(),
            'hold_time_seconds': self.hold_time_seconds,
            'is_win': self.is_win,
        }


@dataclass
class AccountPerformanceMetrics:
    """Performance metrics for a single account"""
    account_id: str
    
    # Trade statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    # P&L statistics
    total_pnl: float = 0.0
    total_fees: float = 0.0
    net_pnl: float = 0.0
    
    # Win/Loss statistics
    average_win: float = 0.0
    average_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    
    # Expectancy (most important metric)
    expectancy: float = 0.0  # Expected return per dollar risked
    expectancy_per_trade: float = 0.0  # Expected return per trade in USD
    
    # Drawdown tracking
    peak_balance: float = 0.0
    current_balance: float = 0.0
    current_drawdown: float = 0.0  # Current drawdown from peak
    max_drawdown: float = 0.0  # Maximum drawdown ever experienced
    max_drawdown_pct: float = 0.0
    
    # Consecutive statistics
    current_streak: int = 0  # Positive for wins, negative for losses
    max_win_streak: int = 0
    max_loss_streak: int = 0
    
    # Profit factor
    profit_factor: float = 0.0  # Total wins / Total losses
    
    # Risk metrics
    sharpe_ratio: float = 0.0  # Risk-adjusted returns
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'account_id': self.account_id,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'total_pnl': self.total_pnl,
            'total_fees': self.total_fees,
            'net_pnl': self.net_pnl,
            'average_win': self.average_win,
            'average_loss': self.average_loss,
            'largest_win': self.largest_win,
            'largest_loss': self.largest_loss,
            'expectancy': self.expectancy,
            'expectancy_per_trade': self.expectancy_per_trade,
            'peak_balance': self.peak_balance,
            'current_balance': self.current_balance,
            'current_drawdown': self.current_drawdown,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'current_streak': self.current_streak,
            'max_win_streak': self.max_win_streak,
            'max_loss_streak': self.max_loss_streak,
            'profit_factor': self.profit_factor,
            'sharpe_ratio': self.sharpe_ratio,
        }


class AccountPerformanceTracker:
    """
    Track performance metrics separately per account
    
    CRITICAL: Never aggregate metrics across accounts.
    Each account has its own:
    - Trade history
    - Expectancy calculation
    - Drawdown tracking
    - Performance metrics
    """
    
    def __init__(self, data_dir: str = "./data"):
        """Initialize account performance tracker"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        
        # Separate data per account
        self.trade_history_by_account: Dict[str, List[TradeRecord]] = defaultdict(list)
        self.metrics_by_account: Dict[str, AccountPerformanceMetrics] = {}
        
        # Track balance history per account for drawdown calculation
        self.balance_history_by_account: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        
        # Configuration
        self.max_trade_history_per_account = 1000  # Keep last 1000 trades per account
        
        logger.info("✅ Account Performance Tracker initialized")
        logger.info("   ⚠️ CRITICAL: Metrics are NEVER aggregated across accounts")
        
        # Load existing state
        self._load_state()
    
    def record_trade(self, trade: TradeRecord) -> None:
        """
        Record a trade for an account
        
        Args:
            trade: TradeRecord to record
        """
        account_id = trade.account_id
        
        # Add to trade history
        self.trade_history_by_account[account_id].append(trade)
        
        # Trim history if too long
        if len(self.trade_history_by_account[account_id]) > self.max_trade_history_per_account:
            self.trade_history_by_account[account_id] = self.trade_history_by_account[account_id][-self.max_trade_history_per_account:]
        
        logger.info(
            f"📊 Recorded trade for {account_id}: {trade.symbol} {trade.side} "
            f"{'WIN' if trade.is_win else 'LOSS'} ${trade.net_pnl:.2f}"
        )
        
        # Recalculate metrics for this account only
        self._calculate_metrics(account_id)
        
        # Save state
        self._save_state()
    
    def update_balance(self, account_id: str, balance: float) -> None:
        """
        Update account balance and track drawdown
        
        Args:
            account_id: Account ID
            balance: Current account balance
        """
        # Record balance history
        self.balance_history_by_account[account_id].append((datetime.now(), balance))
        
        # Update metrics
        if account_id not in self.metrics_by_account:
            self.metrics_by_account[account_id] = AccountPerformanceMetrics(account_id=account_id)
        
        metrics = self.metrics_by_account[account_id]
        metrics.current_balance = balance
        
        # Update peak balance
        if balance > metrics.peak_balance:
            metrics.peak_balance = balance
            metrics.current_drawdown = 0.0
        else:
            # Calculate current drawdown
            if metrics.peak_balance > 0:
                metrics.current_drawdown = metrics.peak_balance - balance
                current_dd_pct = (metrics.current_drawdown / metrics.peak_balance) * 100
                
                # Update max drawdown
                if metrics.current_drawdown > metrics.max_drawdown:
                    metrics.max_drawdown = metrics.current_drawdown
                    metrics.max_drawdown_pct = current_dd_pct
        
        # Trim balance history (keep last 1000 entries)
        if len(self.balance_history_by_account[account_id]) > 1000:
            self.balance_history_by_account[account_id] = self.balance_history_by_account[account_id][-1000:]
        
        self._save_state()
    
    def _calculate_metrics(self, account_id: str) -> None:
        """
        Calculate performance metrics for a specific account
        
        Args:
            account_id: Account ID to calculate metrics for
        """
        trades = self.trade_history_by_account[account_id]
        
        if not trades:
            # No trades yet - initialize empty metrics
            self.metrics_by_account[account_id] = AccountPerformanceMetrics(account_id=account_id)
            return
        
        # Initialize metrics
        metrics = AccountPerformanceMetrics(account_id=account_id)
        
        # Calculate basic stats
        metrics.total_trades = len(trades)
        metrics.winning_trades = sum(1 for t in trades if t.is_win)
        metrics.losing_trades = metrics.total_trades - metrics.winning_trades
        metrics.win_rate = (metrics.winning_trades / metrics.total_trades * 100) if metrics.total_trades > 0 else 0.0
        
        # Calculate P&L
        metrics.total_pnl = sum(t.pnl for t in trades)
        metrics.total_fees = sum(t.fees for t in trades)
        metrics.net_pnl = sum(t.net_pnl for t in trades)
        
        # Calculate win/loss statistics
        wins = [t.net_pnl for t in trades if t.is_win]
        losses = [abs(t.net_pnl) for t in trades if not t.is_win]
        
        metrics.average_win = sum(wins) / len(wins) if wins else 0.0
        metrics.average_loss = sum(losses) / len(losses) if losses else 0.0
        metrics.largest_win = max(wins) if wins else 0.0
        metrics.largest_loss = max(losses) if losses else 0.0
        
        # Calculate expectancy (CRITICAL METRIC)
        # Expectancy = (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
        loss_rate = 1.0 - (metrics.win_rate / 100.0)
        metrics.expectancy = (metrics.win_rate / 100.0 * metrics.average_win) - (loss_rate * metrics.average_loss)
        
        # Expectancy per trade (in USD)
        metrics.expectancy_per_trade = metrics.net_pnl / metrics.total_trades if metrics.total_trades > 0 else 0.0
        
        # Calculate profit factor
        total_wins = sum(wins) if wins else 0.0
        total_losses = sum(losses) if losses else 1.0  # Avoid division by zero
        metrics.profit_factor = total_wins / total_losses if total_losses > 0 else 0.0
        
        # Calculate streaks
        current_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        
        for trade in trades:
            if trade.is_win:
                if current_streak >= 0:
                    current_streak += 1
                else:
                    current_streak = 1
                max_win_streak = max(max_win_streak, current_streak)
            else:
                if current_streak <= 0:
                    current_streak -= 1
                else:
                    current_streak = -1
                max_loss_streak = max(max_loss_streak, abs(current_streak))
        
        metrics.current_streak = current_streak
        metrics.max_win_streak = max_win_streak
        metrics.max_loss_streak = max_loss_streak
        
        # Calculate Sharpe ratio (simplified - uses trade returns)
        if metrics.total_trades > 1:
            returns = [t.net_pnl for t in trades]
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
            std_dev = variance ** 0.5
            metrics.sharpe_ratio = (mean_return / std_dev) if std_dev > 0 else 0.0
        
        # Store updated metrics
        self.metrics_by_account[account_id] = metrics
        
        logger.debug(
            f"📊 Calculated metrics for {account_id}: "
            f"{metrics.total_trades} trades, {metrics.win_rate:.1f}% WR, "
            f"${metrics.expectancy_per_trade:.2f} expectancy per trade"
        )
    
    def get_metrics(self, account_id: str) -> AccountPerformanceMetrics:
        """
        Get performance metrics for an account
        
        Args:
            account_id: Account ID
            
        Returns:
            AccountPerformanceMetrics object
        """
        if account_id not in self.metrics_by_account:
            # Calculate if not already done
            self._calculate_metrics(account_id)
        
        return self.metrics_by_account[account_id]
    
    def get_trade_history(self, account_id: str, limit: Optional[int] = None) -> List[TradeRecord]:
        """
        Get trade history for an account
        
        Args:
            account_id: Account ID
            limit: Maximum number of trades to return (most recent first)
            
        Returns:
            List of TradeRecord objects
        """
        trades = self.trade_history_by_account[account_id]
        
        if limit:
            return trades[-limit:]
        return trades
    
    def get_all_accounts(self) -> List[str]:
        """
        Get list of all tracked accounts
        
        Returns:
            List of account IDs
        """
        return list(set(self.trade_history_by_account.keys()) | set(self.metrics_by_account.keys()))
    
    def get_all_metrics(self) -> Dict[str, AccountPerformanceMetrics]:
        """
        Get metrics for all accounts
        
        WARNING: This returns metrics for each account separately.
        DO NOT aggregate these metrics!
        
        Returns:
            Dictionary mapping account_id to AccountPerformanceMetrics
        """
        all_metrics = {}
        for account_id in self.get_all_accounts():
            all_metrics[account_id] = self.get_metrics(account_id)
        return all_metrics
    
    def verify_no_aggregation(self) -> Dict[str, str]:
        """
        Verify that accounts are properly separated (no cross-contamination)
        
        Returns:
            Dictionary with verification results
        """
        results = {}
        
        all_accounts = self.get_all_accounts()
        
        # Check that each account's trades only belong to that account
        for account_id in all_accounts:
            trades = self.trade_history_by_account[account_id]
            
            # Verify all trades belong to this account
            invalid_trades = [t for t in trades if t.account_id != account_id]
            
            if invalid_trades:
                results[account_id] = f"❌ CONTAMINATION: {len(invalid_trades)} trades belong to other accounts!"
            else:
                results[account_id] = f"✅ Clean: All {len(trades)} trades belong to {account_id}"
        
        return results
    
    def print_account_summary(self, account_id: str) -> None:
        """
        Print detailed summary for an account
        
        Args:
            account_id: Account ID to print summary for
        """
        metrics = self.get_metrics(account_id)
        trades = self.get_trade_history(account_id)
        
        print(f"\n{'='*70}")
        print(f"PERFORMANCE SUMMARY: {account_id}")
        print(f"{'='*70}")
        print(f"\n📊 TRADE STATISTICS:")
        print(f"   Total Trades:      {metrics.total_trades}")
        print(f"   Winning Trades:    {metrics.winning_trades}")
        print(f"   Losing Trades:     {metrics.losing_trades}")
        print(f"   Win Rate:          {metrics.win_rate:.1f}%")
        print(f"\n💰 P&L STATISTICS:")
        print(f"   Total P&L:         ${metrics.total_pnl:.2f}")
        print(f"   Total Fees:        ${metrics.total_fees:.2f}")
        print(f"   Net P&L:           ${metrics.net_pnl:.2f}")
        print(f"   Average Win:       ${metrics.average_win:.2f}")
        print(f"   Average Loss:      ${metrics.average_loss:.2f}")
        print(f"   Largest Win:       ${metrics.largest_win:.2f}")
        print(f"   Largest Loss:      ${metrics.largest_loss:.2f}")
        print(f"\n📈 KEY METRICS:")
        print(f"   Expectancy:        ${metrics.expectancy:.2f} per dollar risked")
        print(f"   Expectancy/Trade:  ${metrics.expectancy_per_trade:.2f} per trade")
        print(f"   Profit Factor:     {metrics.profit_factor:.2f}")
        print(f"   Sharpe Ratio:      {metrics.sharpe_ratio:.2f}")
        print(f"\n📉 DRAWDOWN:")
        print(f"   Peak Balance:      ${metrics.peak_balance:.2f}")
        print(f"   Current Balance:   ${metrics.current_balance:.2f}")
        print(f"   Current Drawdown:  ${metrics.current_drawdown:.2f} ({(metrics.current_drawdown/metrics.peak_balance*100) if metrics.peak_balance > 0 else 0:.1f}%)")
        print(f"   Max Drawdown:      ${metrics.max_drawdown:.2f} ({metrics.max_drawdown_pct:.1f}%)")
        print(f"\n🔥 STREAKS:")
        print(f"   Current Streak:    {metrics.current_streak} ({'wins' if metrics.current_streak > 0 else 'losses'})")
        print(f"   Max Win Streak:    {metrics.max_win_streak}")
        print(f"   Max Loss Streak:   {metrics.max_loss_streak}")
        print(f"{'='*70}\n")
    
    def _save_state(self) -> None:
        """Save tracker state to file (per account)"""
        try:
            # Save each account separately
            for account_id in self.get_all_accounts():
                account_file = self.data_dir / f"performance_{account_id}.json"
                
                state = {
                    'account_id': account_id,
                    'trade_history': [t.to_dict() for t in self.trade_history_by_account[account_id]],
                    'metrics': self.metrics_by_account.get(account_id, AccountPerformanceMetrics(account_id=account_id)).to_dict(),
                    'balance_history': [
                        {'timestamp': ts.isoformat(), 'balance': bal}
                        for ts, bal in self.balance_history_by_account[account_id]
                    ],
                    'timestamp': datetime.now().isoformat()
                }
                
                with open(account_file, 'w') as f:
                    json.dump(state, f, indent=2, default=str)
            
            logger.debug(f"💾 Saved performance state for {len(self.get_all_accounts())} accounts")
            
        except Exception as e:
            logger.error(f"Failed to save performance tracker state: {e}")
    
    def _load_state(self) -> None:
        """Load tracker state from files"""
        try:
            # Load all performance files
            performance_files = list(self.data_dir.glob("performance_*.json"))
            
            if not performance_files:
                logger.info("No saved performance state found (first run)")
                return
            
            for perf_file in performance_files:
                with open(perf_file, 'r') as f:
                    state = json.load(f)
                
                account_id = state['account_id']
                
                # Restore trade history
                self.trade_history_by_account[account_id] = [
                    TradeRecord(
                        trade_id=t['trade_id'],
                        account_id=t['account_id'],
                        symbol=t['symbol'],
                        side=t['side'],
                        entry_price=t['entry_price'],
                        exit_price=t['exit_price'],
                        quantity=t['quantity'],
                        size_usd=t['size_usd'],
                        pnl=t['pnl'],
                        pnl_pct=t['pnl_pct'],
                        fees=t['fees'],
                        net_pnl=t['net_pnl'],
                        entry_time=datetime.fromisoformat(t['entry_time']),
                        exit_time=datetime.fromisoformat(t['exit_time']),
                        hold_time_seconds=t['hold_time_seconds'],
                        is_win=t['is_win'],
                    )
                    for t in state.get('trade_history', [])
                ]
                
                # Restore balance history
                self.balance_history_by_account[account_id] = [
                    (datetime.fromisoformat(item['timestamp']), item['balance'])
                    for item in state.get('balance_history', [])
                ]
                
                # Recalculate metrics
                self._calculate_metrics(account_id)
            
            logger.info(f"✅ Loaded performance state for {len(performance_files)} accounts")
            
        except Exception as e:
            logger.error(f"Failed to load performance tracker state: {e}")


# Global instance
_global_performance_tracker: Optional[AccountPerformanceTracker] = None


def get_performance_tracker(data_dir: str = "./data") -> AccountPerformanceTracker:
    """Get or create global performance tracker instance"""
    global _global_performance_tracker
    if _global_performance_tracker is None:
        _global_performance_tracker = AccountPerformanceTracker(data_dir=data_dir)
    return _global_performance_tracker
