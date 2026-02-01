"""
Follower PnL Attribution System
================================

Tracks individual follower profit/loss and compares to master performance.
Provides attribution metrics to understand copy trading effectiveness.

Key Metrics:
- Follower PnL (absolute and %)
- Master PnL for comparison
- Copy efficiency (follower % vs master %)
- Slippage impact
- Trade success rate

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
import json
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('nija.follower_pnl')


@dataclass
class FollowerTrade:
    """Individual follower trade record."""
    follower_id: str
    master_trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float]
    size: float
    size_type: str
    timestamp: float
    status: str  # 'open', 'closed', 'failed'
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class MasterTradeReference:
    """Master trade reference for comparison."""
    master_trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float]
    size: float
    master_pnl: Optional[float] = None
    master_pnl_pct: Optional[float] = None


@dataclass
class FollowerPnLMetrics:
    """PnL metrics for a follower."""
    follower_id: str
    total_trades: int
    successful_copies: int
    failed_copies: int
    open_positions: int
    closed_positions: int
    
    # PnL metrics
    total_pnl: float
    total_pnl_pct: float
    realized_pnl: float
    unrealized_pnl: float
    
    # Comparison to master
    platform_total_pnl: float
    platform_total_pnl_pct: float
    copy_efficiency: float  # Follower PnL% / Master PnL%
    
    # Performance metrics
    win_rate: float  # % of profitable closed trades
    avg_slippage_pct: float
    avg_trade_size: float
    
    # Timestamps
    first_trade_timestamp: Optional[float] = None
    last_trade_timestamp: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class FollowerPnLAttribution:
    """
    Tracks and attributes PnL for individual followers.
    
    Maintains a record of all follower trades and calculates performance
    metrics including absolute PnL, percentage returns, and comparison to master.
    """
    
    def __init__(self, data_dir: str = "data/follower_pnl"):
        """
        Initialize follower PnL attribution system.
        
        Args:
            data_dir: Directory to store follower PnL data
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.follower_trades: Dict[str, List[FollowerTrade]] = {}  # follower_id -> trades
        self.master_trades: Dict[str, MasterTradeReference] = {}  # master_trade_id -> master trade
        
        self._load_data()
        
        logger.info("=" * 70)
        logger.info("📊 FOLLOWER PNL ATTRIBUTION INITIALIZED")
        logger.info("=" * 70)
        logger.info(f"   Data directory: {self.data_dir}")
        logger.info(f"   Tracking {len(self.follower_trades)} followers")
        logger.info("=" * 70)
    
    def _load_data(self):
        """Load existing follower PnL data from disk."""
        try:
            # Load follower trades
            follower_file = self.data_dir / "follower_trades.json"
            if follower_file.exists():
                with open(follower_file, 'r') as f:
                    data = json.load(f)
                    for follower_id, trades_data in data.items():
                        self.follower_trades[follower_id] = [
                            FollowerTrade(**trade) for trade in trades_data
                        ]
            
            # Load master trades
            master_file = self.data_dir / "master_trades.json"
            if master_file.exists():
                with open(master_file, 'r') as f:
                    data = json.load(f)
                    self.master_trades = {
                        trade_id: MasterTradeReference(**trade_data)
                        for trade_id, trade_data in data.items()
                    }
        except Exception as e:
            logger.error(f"Error loading follower PnL data: {e}")
    
    def _save_data(self):
        """Save follower PnL data to disk."""
        try:
            # Save follower trades
            follower_file = self.data_dir / "follower_trades.json"
            with open(follower_file, 'w') as f:
                data = {
                    follower_id: [trade.to_dict() for trade in trades]
                    for follower_id, trades in self.follower_trades.items()
                }
                json.dump(data, f, indent=2)
            
            # Save master trades
            master_file = self.data_dir / "master_trades.json"
            with open(master_file, 'w') as f:
                data = {
                    trade_id: trade.to_dict()
                    for trade_id, trade in self.master_trades.items()
                }
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving follower PnL data: {e}")
    
    def record_master_trade(
        self,
        master_trade_id: str,
        symbol: str,
        side: str,
        price: float,
        size: float
    ):
        """
        Record a master trade for reference.
        
        Args:
            master_trade_id: Unique master trade ID
            symbol: Trading pair
            side: 'buy' or 'sell'
            price: Entry price
            size: Position size
        """
        self.master_trades[master_trade_id] = MasterTradeReference(
            master_trade_id=master_trade_id,
            symbol=symbol,
            side=side,
            entry_price=price,
            exit_price=None,
            size=size
        )
        self._save_data()
    
    def record_follower_trade(
        self,
        follower_id: str,
        master_trade_id: str,
        symbol: str,
        side: str,
        price: float,
        size: float,
        size_type: str,
        status: str = 'open'
    ):
        """
        Record a follower trade.
        
        Args:
            follower_id: Follower account ID
            master_trade_id: Corresponding master trade ID
            symbol: Trading pair
            side: 'buy' or 'sell'
            price: Execution price
            size: Position size
            size_type: 'base' or 'quote'
            status: Trade status ('open', 'closed', 'failed')
        """
        if follower_id not in self.follower_trades:
            self.follower_trades[follower_id] = []
        
        trade = FollowerTrade(
            follower_id=follower_id,
            master_trade_id=master_trade_id,
            symbol=symbol,
            side=side,
            entry_price=price,
            exit_price=None,
            size=size,
            size_type=size_type,
            timestamp=datetime.now().timestamp(),
            status=status
        )
        
        self.follower_trades[follower_id].append(trade)
        self._save_data()
        
        logger.info(f"📊 Recorded follower trade: {follower_id} {side} {symbol} @ ${price:.2f}")
    
    def update_follower_exit(
        self,
        follower_id: str,
        master_trade_id: str,
        exit_price: float
    ):
        """
        Update follower trade with exit price and calculate PnL.
        
        Args:
            follower_id: Follower account ID
            master_trade_id: Master trade ID
            exit_price: Exit price
        """
        if follower_id not in self.follower_trades:
            logger.warning(f"No trades found for follower {follower_id}")
            return
        
        # Find the trade
        for trade in self.follower_trades[follower_id]:
            if trade.master_trade_id == master_trade_id and trade.status == 'open':
                trade.exit_price = exit_price
                trade.status = 'closed'
                
                # Calculate PnL
                if trade.side.lower() == 'buy':
                    trade.pnl = (exit_price - trade.entry_price) * trade.size
                    trade.pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
                else:  # sell
                    trade.pnl = (trade.entry_price - exit_price) * trade.size
                    trade.pnl_pct = ((trade.entry_price - exit_price) / trade.entry_price) * 100
                
                self._save_data()
                
                logger.info(f"📊 Updated follower exit: {follower_id} PnL: ${trade.pnl:.2f} ({trade.pnl_pct:+.2f}%)")
                break
    
    def get_follower_metrics(self, follower_id: str) -> Optional[FollowerPnLMetrics]:
        """
        Calculate comprehensive PnL metrics for a follower.
        
        Args:
            follower_id: Follower account ID
        
        Returns:
            FollowerPnLMetrics object or None if no trades
        """
        if follower_id not in self.follower_trades or not self.follower_trades[follower_id]:
            return None
        
        trades = self.follower_trades[follower_id]
        
        # Count trades by status
        total_trades = len(trades)
        successful_copies = sum(1 for t in trades if t.status in ('open', 'closed'))
        failed_copies = sum(1 for t in trades if t.status == 'failed')
        open_positions = sum(1 for t in trades if t.status == 'open')
        closed_positions = sum(1 for t in trades if t.status == 'closed')
        
        # Calculate PnL
        realized_pnl = sum(t.pnl for t in trades if t.status == 'closed' and t.pnl is not None)
        unrealized_pnl = 0.0  # Would need current prices to calculate
        total_pnl = realized_pnl + unrealized_pnl
        
        # Calculate percentage PnL (weighted by trade size)
        total_invested = sum(t.entry_price * t.size for t in trades if t.status == 'closed')
        total_pnl_pct = (realized_pnl / total_invested * 100) if total_invested > 0 else 0.0
        
        # Calculate master comparison
        platform_total_pnl = 0.0
        platform_total_pnl_pct = 0.0
        for trade in trades:
            if trade.master_trade_id in self.master_trades:
                master_trade = self.master_trades[trade.master_trade_id]
                if master_trade.master_pnl is not None:
                    platform_total_pnl += master_trade.master_pnl
        
        copy_efficiency = (total_pnl_pct / platform_total_pnl_pct * 100) if platform_total_pnl_pct != 0 else 100.0
        
        # Calculate win rate
        closed_trades = [t for t in trades if t.status == 'closed' and t.pnl is not None]
        winning_trades = sum(1 for t in closed_trades if t.pnl > 0)
        win_rate = (winning_trades / len(closed_trades) * 100) if closed_trades else 0.0
        
        # Calculate avg slippage
        avg_slippage_pct = 0.0  # Would need to compare to master entry prices
        
        # Calculate avg trade size
        avg_trade_size = sum(t.entry_price * t.size for t in trades) / total_trades if total_trades > 0 else 0.0
        
        # Timestamps
        first_trade_timestamp = min(t.timestamp for t in trades) if trades else None
        last_trade_timestamp = max(t.timestamp for t in trades) if trades else None
        
        return FollowerPnLMetrics(
            follower_id=follower_id,
            total_trades=total_trades,
            successful_copies=successful_copies,
            failed_copies=failed_copies,
            open_positions=open_positions,
            closed_positions=closed_positions,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            platform_total_pnl=platform_total_pnl,
            platform_total_pnl_pct=platform_total_pnl_pct,
            copy_efficiency=copy_efficiency,
            win_rate=win_rate,
            avg_slippage_pct=avg_slippage_pct,
            avg_trade_size=avg_trade_size,
            first_trade_timestamp=first_trade_timestamp,
            last_trade_timestamp=last_trade_timestamp
        )
    
    def get_all_follower_metrics(self) -> Dict[str, FollowerPnLMetrics]:
        """
        Get metrics for all followers.
        
        Returns:
            Dictionary mapping follower_id to FollowerPnLMetrics
        """
        return {
            follower_id: self.get_follower_metrics(follower_id)
            for follower_id in self.follower_trades
            if self.get_follower_metrics(follower_id) is not None
        }
    
    def print_summary(self, follower_id: Optional[str] = None):
        """
        Print PnL summary for follower(s).
        
        Args:
            follower_id: Specific follower ID, or None for all followers
        """
        if follower_id:
            metrics = self.get_follower_metrics(follower_id)
            if metrics:
                self._print_follower_summary(metrics)
            else:
                logger.warning(f"No metrics available for follower {follower_id}")
        else:
            all_metrics = self.get_all_follower_metrics()
            for follower_id, metrics in all_metrics.items():
                self._print_follower_summary(metrics)
                print()
    
    def _print_follower_summary(self, metrics: FollowerPnLMetrics):
        """Print summary for a single follower."""
        print("=" * 70)
        print(f"📊 FOLLOWER PNL SUMMARY: {metrics.follower_id}")
        print("=" * 70)
        print(f"   Total Trades: {metrics.total_trades}")
        print(f"   Successful Copies: {metrics.successful_copies}")
        print(f"   Failed Copies: {metrics.failed_copies}")
        print(f"   Open Positions: {metrics.open_positions}")
        print(f"   Closed Positions: {metrics.closed_positions}")
        print()
        print(f"   📈 PNL METRICS:")
        print(f"      Total PnL: ${metrics.total_pnl:.2f} ({metrics.total_pnl_pct:+.2f}%)")
        print(f"      Realized PnL: ${metrics.realized_pnl:.2f}")
        print(f"      Unrealized PnL: ${metrics.unrealized_pnl:.2f}")
        print()
        print(f"   🎯 PERFORMANCE:")
        print(f"      Win Rate: {metrics.win_rate:.1f}%")
        print(f"      Avg Trade Size: ${metrics.avg_trade_size:.2f}")
        print(f"      Copy Efficiency: {metrics.copy_efficiency:.1f}%")
        print("=" * 70)


# Global instance
_follower_pnl_attribution = None


def get_follower_pnl_attribution() -> FollowerPnLAttribution:
    """Get global follower PnL attribution instance."""
    global _follower_pnl_attribution
    if _follower_pnl_attribution is None:
        _follower_pnl_attribution = FollowerPnLAttribution()
    return _follower_pnl_attribution
