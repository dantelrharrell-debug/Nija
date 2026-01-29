"""
NIJA Live Execution Tracker
============================

Real-time tracking and monitoring of live trading execution.

Features:
- Real-time performance monitoring
- Trade validation and logging
- Risk monitoring and alerts
- Performance comparison (actual vs backtest)
- Automatic reporting
- Safety checks and circuit breakers

Author: NIJA Trading Systems
Date: January 28, 2026
"""

import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
import pandas as pd
import numpy as np

logger = logging.getLogger("nija.live_tracker")


@dataclass
class LiveTrade:
    """Represents a live trade"""
    trade_id: str
    entry_time: datetime
    exit_time: Optional[datetime]
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float]
    size: float
    status: str  # 'open', 'closed'
    pnl: float
    pnl_pct: float
    commission: float
    stop_loss: float
    take_profit: Optional[float]
    broker: str
    account_id: str
    entry_score: Optional[float]
    exit_reason: Optional[str]
    slippage: Optional[float]

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        d = asdict(self)
        d['entry_time'] = self.entry_time.isoformat() if self.entry_time else None
        d['exit_time'] = self.exit_time.isoformat() if self.exit_time else None
        return d


@dataclass
class LivePerformanceSnapshot:
    """Real-time performance snapshot"""
    timestamp: datetime
    balance: float
    equity: float
    unrealized_pnl: float
    realized_pnl_today: float
    realized_pnl_total: float
    open_positions: int
    trades_today: int
    trades_total: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


class LiveExecutionTracker:
    """
    Track and monitor live trading execution in real-time
    """

    def __init__(
        self,
        initial_balance: float,
        data_dir: str = "./data/live_tracking",
        max_daily_loss_pct: float = 5.0,
        max_drawdown_pct: float = 12.0,
        enable_alerts: bool = True
    ):
        """
        Initialize live execution tracker

        Args:
            initial_balance: Starting account balance
            data_dir: Directory for storing live tracking data
            max_daily_loss_pct: Maximum daily loss % before circuit breaker
            max_drawdown_pct: Maximum drawdown % before alert
            enable_alerts: Enable risk alerts
        """
        self.initial_balance = initial_balance
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Risk limits
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.enable_alerts = enable_alerts

        # State
        self.trades: List[LiveTrade] = []
        self.open_positions: Dict[str, LiveTrade] = {}
        self.performance_snapshots: List[LivePerformanceSnapshot] = []
        self.daily_stats: Dict[str, Dict] = {}

        # Load existing data
        self._load_state()

        logger.info(f"Live execution tracker initialized: ${initial_balance:,.2f}")
        logger.info(f"Risk limits: Max daily loss={max_daily_loss_pct}%, Max DD={max_drawdown_pct}%")

    def _load_state(self):
        """Load existing state from disk"""
        state_file = self.data_dir / "tracker_state.json"

        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    data = json.load(f)

                # Reconstruct trades
                for trade_data in data.get('trades', []):
                    trade = LiveTrade(
                        trade_id=trade_data['trade_id'],
                        entry_time=datetime.fromisoformat(trade_data['entry_time']),
                        exit_time=datetime.fromisoformat(trade_data['exit_time']) if trade_data.get('exit_time') else None,
                        symbol=trade_data['symbol'],
                        side=trade_data['side'],
                        entry_price=trade_data['entry_price'],
                        exit_price=trade_data.get('exit_price'),
                        size=trade_data['size'],
                        status=trade_data['status'],
                        pnl=trade_data['pnl'],
                        pnl_pct=trade_data['pnl_pct'],
                        commission=trade_data['commission'],
                        stop_loss=trade_data['stop_loss'],
                        take_profit=trade_data.get('take_profit'),
                        broker=trade_data['broker'],
                        account_id=trade_data['account_id'],
                        entry_score=trade_data.get('entry_score'),
                        exit_reason=trade_data.get('exit_reason'),
                        slippage=trade_data.get('slippage')
                    )
                    self.trades.append(trade)

                    if trade.status == 'open':
                        self.open_positions[trade.trade_id] = trade

                logger.info(f"Loaded {len(self.trades)} trades from disk ({len(self.open_positions)} open)")

            except Exception as e:
                logger.error(f"Failed to load tracker state: {e}")

    def _save_state(self):
        """Save current state to disk"""
        state_file = self.data_dir / "tracker_state.json"

        try:
            state = {
                'trades': [t.to_dict() for t in self.trades],
                'last_updated': datetime.now().isoformat()
            }

            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2, default=str)

        except Exception as e:
            logger.error(f"Failed to save tracker state: {e}")

    def record_entry(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        stop_loss: float,
        take_profit: Optional[float] = None,
        broker: str = "coinbase",
        account_id: str = "master",
        entry_score: Optional[float] = None,
        commission: float = 0.0,
        slippage: Optional[float] = None
    ):
        """
        Record a new trade entry

        Args:
            trade_id: Unique trade identifier
            symbol: Trading symbol
            side: 'long' or 'short'
            entry_price: Entry price
            size: Position size
            stop_loss: Stop loss price
            take_profit: Take profit price (optional)
            broker: Broker name
            account_id: Account identifier
            entry_score: Entry quality score (optional)
            commission: Commission paid
            slippage: Slippage experienced (optional)
        """
        trade = LiveTrade(
            trade_id=trade_id,
            entry_time=datetime.now(),
            exit_time=None,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=None,
            size=size,
            status='open',
            pnl=0.0,
            pnl_pct=0.0,
            commission=commission,
            stop_loss=stop_loss,
            take_profit=take_profit,
            broker=broker,
            account_id=account_id,
            entry_score=entry_score,
            exit_reason=None,
            slippage=slippage
        )

        self.trades.append(trade)
        self.open_positions[trade_id] = trade

        self._save_state()

        logger.info(f"✅ Recorded entry: {side.upper()} {size} {symbol} @ ${entry_price:.4f} (ID: {trade_id})")

        # Log entry score if available
        if entry_score is not None:
            logger.info(f"   Entry Score: {entry_score:.1f}/100")

    def record_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str = "manual",
        commission: float = 0.0,
        slippage: Optional[float] = None
    ):
        """
        Record trade exit

        Args:
            trade_id: Trade identifier
            exit_price: Exit price
            exit_reason: Reason for exit
            commission: Exit commission
            slippage: Exit slippage (optional)
        """
        if trade_id not in self.open_positions:
            logger.error(f"Trade not found: {trade_id}")
            return

        trade = self.open_positions[trade_id]

        # Calculate P&L
        if trade.side == 'long':
            pnl_before_commission = (exit_price - trade.entry_price) * trade.size
        else:  # short
            pnl_before_commission = (trade.entry_price - exit_price) * trade.size

        # Net P&L after commission
        total_commission = trade.commission + commission
        pnl = pnl_before_commission - total_commission
        pnl_pct = (pnl / (trade.size * trade.entry_price)) * 100

        # Update trade
        trade.exit_time = datetime.now()
        trade.exit_price = exit_price
        trade.status = 'closed'
        trade.pnl = pnl
        trade.pnl_pct = pnl_pct
        trade.commission = total_commission
        trade.exit_reason = exit_reason

        if slippage is not None:
            trade.slippage = (trade.slippage or 0) + slippage

        # Remove from open positions
        del self.open_positions[trade_id]

        self._save_state()

        logger.info(f"✅ Recorded exit: {trade.symbol} @ ${exit_price:.4f}, "
                   f"P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%), Reason: {exit_reason}")

        # Check for risk alerts
        self._check_risk_limits()

    def update_position(
        self,
        trade_id: str,
        current_price: float
    ):
        """
        Update open position with current market price

        Args:
            trade_id: Trade identifier
            current_price: Current market price
        """
        if trade_id not in self.open_positions:
            return

        trade = self.open_positions[trade_id]

        # Calculate unrealized P&L
        if trade.side == 'long':
            unrealized_pnl = (current_price - trade.entry_price) * trade.size
        else:
            unrealized_pnl = (trade.entry_price - current_price) * trade.size

        # Update trade (for monitoring only, doesn't change saved state)
        trade.pnl = unrealized_pnl - trade.commission
        trade.pnl_pct = (trade.pnl / (trade.size * trade.entry_price)) * 100

    def get_performance_snapshot(self, current_balance: float) -> LivePerformanceSnapshot:
        """
        Get current performance snapshot

        Args:
            current_balance: Current account balance

        Returns:
            LivePerformanceSnapshot
        """
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Calculate unrealized P&L
        unrealized_pnl = sum(trade.pnl for trade in self.open_positions.values())

        # Total equity
        equity = current_balance + unrealized_pnl

        # Realized P&L
        closed_trades = [t for t in self.trades if t.status == 'closed']
        realized_pnl_total = sum(t.pnl for t in closed_trades)

        today_trades = [t for t in closed_trades if t.exit_time and t.exit_time >= today_start]
        realized_pnl_today = sum(t.pnl for t in today_trades)

        # Win rate
        wins = [t for t in closed_trades if t.pnl > 0]
        win_rate = len(wins) / len(closed_trades) if closed_trades else 0

        # Profit factor
        total_wins = sum(t.pnl for t in wins) if wins else 0
        losses = [t for t in closed_trades if t.pnl < 0]
        total_losses = abs(sum(t.pnl for t in losses)) if losses else 0
        profit_factor = total_wins / total_losses if total_losses > 0 else 0

        # Sharpe ratio (simplified - based on trade returns)
        if len(closed_trades) > 1:
            returns = pd.Series([t.pnl_pct for t in closed_trades])
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe_ratio = 0

        # Max drawdown
        balances = [self.initial_balance]
        for trade in closed_trades:
            balances.append(balances[-1] + trade.pnl)

        if len(balances) > 1:
            balances_series = pd.Series(balances)
            cummax = balances_series.cummax()
            drawdown = (balances_series - cummax) / cummax
            max_drawdown_pct = abs(drawdown.min()) * 100
        else:
            max_drawdown_pct = 0

        snapshot = LivePerformanceSnapshot(
            timestamp=now,
            balance=current_balance,
            equity=equity,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_today=realized_pnl_today,
            realized_pnl_total=realized_pnl_total,
            open_positions=len(self.open_positions),
            trades_today=len(today_trades),
            trades_total=len(closed_trades),
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown_pct
        )

        self.performance_snapshots.append(snapshot)

        return snapshot

    def _check_risk_limits(self):
        """Check risk limits and trigger alerts if needed"""
        if not self.enable_alerts:
            return

        # Get today's P&L
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_trades = [t for t in self.trades if t.status == 'closed' and t.exit_time and t.exit_time >= today_start]

        if today_trades:
            daily_pnl = sum(t.pnl for t in today_trades)
            daily_pnl_pct = (daily_pnl / self.initial_balance) * 100

            # Daily loss limit
            if daily_pnl_pct < -self.max_daily_loss_pct:
                logger.error("="*80)
                logger.error(f"🚨 CIRCUIT BREAKER: Daily loss limit exceeded!")
                logger.error(f"   Daily P&L: ${daily_pnl:+.2f} ({daily_pnl_pct:+.2f}%)")
                logger.error(f"   Limit: -{self.max_daily_loss_pct}%")
                logger.error(f"   ACTION REQUIRED: Stop trading for today")
                logger.error("="*80)

        # Drawdown alert
        closed_trades = [t for t in self.trades if t.status == 'closed']
        if closed_trades:
            balances = [self.initial_balance]
            for trade in closed_trades:
                balances.append(balances[-1] + trade.pnl)

            balances_series = pd.Series(balances)
            cummax = balances_series.cummax()
            drawdown = (balances_series - cummax) / cummax
            current_drawdown_pct = abs(drawdown.iloc[-1]) * 100

            if current_drawdown_pct > self.max_drawdown_pct:
                logger.warning("="*80)
                logger.warning(f"⚠️  DRAWDOWN ALERT: Maximum drawdown exceeded!")
                logger.warning(f"   Current Drawdown: {current_drawdown_pct:.2f}%")
                logger.warning(f"   Limit: {self.max_drawdown_pct}%")
                logger.warning(f"   Consider reducing position sizes or stopping trading")
                logger.warning("="*80)

    def print_daily_summary(self):
        """Print daily trading summary"""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        today_trades = [t for t in self.trades if t.exit_time and t.exit_time >= today_start]

        print("\n" + "="*80)
        print(f"DAILY TRADING SUMMARY - {now.strftime('%Y-%m-%d')}")
        print("="*80)

        if not today_trades:
            print("\n📊 No trades today")
            print("="*80 + "\n")
            return

        # Calculate stats
        wins = [t for t in today_trades if t.pnl > 0]
        losses = [t for t in today_trades if t.pnl < 0]

        total_pnl = sum(t.pnl for t in today_trades)
        total_pnl_pct = (total_pnl / self.initial_balance) * 100
        win_rate = len(wins) / len(today_trades) * 100

        avg_win = np.mean([t.pnl for t in wins]) if wins else 0
        avg_loss = np.mean([t.pnl for t in losses]) if losses else 0

        print(f"\n📊 TRADES")
        print(f"   Total: {len(today_trades)}")
        print(f"   Wins: {len(wins)} ({win_rate:.1f}%)")
        print(f"   Losses: {len(losses)}")

        print(f"\n💰 P&L")
        print(f"   Total: ${total_pnl:+.2f} ({total_pnl_pct:+.2f}%)")
        print(f"   Avg Win: ${avg_win:.2f}")
        print(f"   Avg Loss: ${avg_loss:.2f}")

        print(f"\n📈 CURRENT STATUS")
        print(f"   Open Positions: {len(self.open_positions)}")

        # List today's trades
        print(f"\n📋 TRADE LOG")
        for trade in today_trades:
            exit_time_str = trade.exit_time.strftime('%H:%M') if trade.exit_time else 'N/A'
            pnl_str = f"${trade.pnl:+.2f} ({trade.pnl_pct:+.2f}%)"
            print(f"   {exit_time_str} | {trade.side.upper():5} {trade.symbol:12} | {pnl_str:20} | {trade.exit_reason or 'N/A'}")

        print("\n" + "="*80 + "\n")

    def export_to_csv(self, output_path: str = None):
        """
        Export trades to CSV

        Args:
            output_path: Output file path (optional)
        """
        if output_path is None:
            output_path = self.data_dir / f"trades_{datetime.now().strftime('%Y%m%d')}.csv"

        trades_df = pd.DataFrame([t.to_dict() for t in self.trades])
        trades_df.to_csv(output_path, index=False)

        logger.info(f"Trades exported to {output_path}")


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Initialize tracker
    tracker = LiveExecutionTracker(
        initial_balance=10000.0,
        max_daily_loss_pct=5.0,
        max_drawdown_pct=12.0
    )

    # Record a trade entry
    tracker.record_entry(
        trade_id="BTC-001",
        symbol="BTC-USD",
        side="long",
        entry_price=50000.0,
        size=0.1,
        stop_loss=49000.0,
        take_profit=52000.0,
        commission=5.0
    )

    # Simulate exit
    tracker.record_exit(
        trade_id="BTC-001",
        exit_price=51000.0,
        exit_reason="take_profit",
        commission=5.1
    )

    # Get performance snapshot
    snapshot = tracker.get_performance_snapshot(current_balance=10090.0)
    print(f"\nCurrent Balance: ${snapshot.balance:.2f}")
    print(f"Total P&L: ${snapshot.realized_pnl_total:+.2f}")
    print(f"Win Rate: {snapshot.win_rate*100:.1f}%")

    # Print daily summary
    tracker.print_daily_summary()
