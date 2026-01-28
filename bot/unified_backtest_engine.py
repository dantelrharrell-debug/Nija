"""
NIJA Unified Backtesting Engine
================================

Comprehensive backtesting engine with investor-grade performance metrics.

Features:
- Multiple strategy backtesting (APEX v7.1, v7.2, v7.3, etc.)
- Detailed performance metrics (Sharpe, Sortino, Profit Factor, Win Rate, etc.)
- Regime-aware analysis (trending, ranging, volatile markets)
- Trade-by-trade breakdown
- Equity curve generation
- Statistical analysis
- Export to HTML/JSON reports

Author: NIJA Trading Systems
Date: January 28, 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import logging
import json
from pathlib import Path

logger = logging.getLogger("nija.backtest")


@dataclass
class Trade:
    """Represents a single trade"""
    entry_time: datetime
    exit_time: Optional[datetime]
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    exit_price: Optional[float]
    size: float
    pnl: float
    pnl_pct: float
    commission: float
    stop_loss: float
    take_profit: Optional[float]
    regime: Optional[str]
    entry_score: Optional[float]
    exit_reason: Optional[str]
    
    def to_dict(self) -> Dict:
        """Convert trade to dictionary"""
        d = asdict(self)
        d['entry_time'] = self.entry_time.isoformat() if self.entry_time else None
        d['exit_time'] = self.exit_time.isoformat() if self.exit_time else None
        return d


@dataclass
class BacktestResults:
    """Container for backtest results"""
    
    # Basic metrics
    initial_balance: float
    final_balance: float
    total_pnl: float
    total_return_pct: float
    
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    
    # Performance metrics
    profit_factor: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    
    # Trade metrics
    avg_win: float
    avg_win_pct: float
    avg_loss: float
    avg_loss_pct: float
    largest_win: float
    largest_loss: float
    
    # Risk metrics
    risk_reward_ratio: float
    expectancy: float
    expectancy_r: float
    
    # Time metrics
    avg_hold_time: timedelta
    total_duration: timedelta
    
    # Detailed data
    trades: List[Trade]
    equity_curve: pd.DataFrame
    monthly_returns: pd.Series
    
    # Regime breakdown (optional)
    regime_stats: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        """Convert results to dictionary for export"""
        # Convert equity curve timestamps to strings
        equity_records = []
        for record in self.equity_curve.to_dict(orient='records'):
            # Convert any timestamps to ISO format strings
            converted_record = {}
            for key, value in record.items():
                if isinstance(value, pd.Timestamp):
                    converted_record[key] = value.isoformat()
                else:
                    converted_record[key] = value
            equity_records.append(converted_record)
        
        # Convert monthly returns index to strings
        monthly_returns_dict = {}
        for key, value in self.monthly_returns.items():
            if isinstance(key, pd.Timestamp):
                monthly_returns_dict[key.isoformat()] = value
            else:
                monthly_returns_dict[str(key)] = value
        
        result = {
            'summary': {
                'initial_balance': self.initial_balance,
                'final_balance': self.final_balance,
                'total_pnl': self.total_pnl,
                'total_return_pct': self.total_return_pct,
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'win_rate': self.win_rate,
                'profit_factor': self.profit_factor,
                'sharpe_ratio': self.sharpe_ratio,
                'sortino_ratio': self.sortino_ratio,
                'max_drawdown': self.max_drawdown,
                'max_drawdown_pct': self.max_drawdown_pct,
                'avg_win': self.avg_win,
                'avg_win_pct': self.avg_win_pct,
                'avg_loss': self.avg_loss,
                'avg_loss_pct': self.avg_loss_pct,
                'largest_win': self.largest_win,
                'largest_loss': self.largest_loss,
                'risk_reward_ratio': self.risk_reward_ratio,
                'expectancy': self.expectancy,
                'expectancy_r': self.expectancy_r,
                'avg_hold_time': str(self.avg_hold_time),
                'total_duration': str(self.total_duration),
            },
            'trades': [t.to_dict() for t in self.trades],
            'equity_curve': equity_records,
            'monthly_returns': monthly_returns_dict,
            'regime_stats': self.regime_stats,
        }
        return result
    
    def print_summary(self):
        """Print formatted summary of backtest results"""
        print("\n" + "="*80)
        print("BACKTEST RESULTS SUMMARY")
        print("="*80)
        
        print(f"\n📊 OVERALL PERFORMANCE")
        print(f"   Initial Balance:     ${self.initial_balance:,.2f}")
        print(f"   Final Balance:       ${self.final_balance:,.2f}")
        print(f"   Total P&L:           ${self.total_pnl:,.2f} ({self.total_return_pct:+.2f}%)")
        print(f"   Duration:            {self.total_duration.days} days")
        
        print(f"\n📈 TRADE STATISTICS")
        print(f"   Total Trades:        {self.total_trades}")
        print(f"   Winning Trades:      {self.winning_trades} ({self.win_rate*100:.1f}%)")
        print(f"   Losing Trades:       {self.losing_trades}")
        print(f"   Avg Hold Time:       {self.avg_hold_time}")
        
        print(f"\n💰 PERFORMANCE METRICS")
        print(f"   Profit Factor:       {self.profit_factor:.2f}")
        print(f"   Sharpe Ratio:        {self.sharpe_ratio:.2f}")
        print(f"   Sortino Ratio:       {self.sortino_ratio:.2f}")
        print(f"   Max Drawdown:        ${self.max_drawdown:,.2f} ({self.max_drawdown_pct:.2f}%)")
        
        print(f"\n🎯 TRADE METRICS")
        print(f"   Avg Win:             ${self.avg_win:,.2f} ({self.avg_win_pct:+.2f}%)")
        print(f"   Avg Loss:            ${self.avg_loss:,.2f} ({self.avg_loss_pct:+.2f}%)")
        print(f"   Largest Win:         ${self.largest_win:,.2f}")
        print(f"   Largest Loss:        ${self.largest_loss:,.2f}")
        
        print(f"\n⚖️ RISK METRICS")
        print(f"   Risk:Reward Ratio:   1:{self.risk_reward_ratio:.2f}")
        print(f"   Expectancy:          ${self.expectancy:.2f} per trade")
        print(f"   Expectancy (R):      {self.expectancy_r:+.3f}R per trade")
        
        # Regime breakdown if available
        if self.regime_stats:
            print(f"\n🌐 REGIME BREAKDOWN")
            for regime, stats in self.regime_stats.items():
                if stats['trades'] > 0:
                    print(f"   {regime}:")
                    print(f"      Trades: {stats['trades']}, Win Rate: {stats['win_rate']*100:.1f}%, "
                          f"Avg P&L: ${stats['avg_pnl']:,.2f}")
        
        print("\n" + "="*80 + "\n")


class UnifiedBacktestEngine:
    """
    Unified backtesting engine for NIJA strategies
    """
    
    def __init__(
        self, 
        initial_balance: float = 10000.0,
        commission_pct: float = 0.001,
        slippage_pct: float = 0.0005
    ):
        """
        Initialize backtest engine
        
        Args:
            initial_balance: Starting balance in USD
            commission_pct: Commission as decimal (0.001 = 0.1%)
            slippage_pct: Slippage as decimal (0.0005 = 0.05%)
        """
        self.initial_balance = initial_balance
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        
        self.reset()
        
        logger.info(f"Backtest engine initialized: ${initial_balance:,.2f}, "
                   f"commission={commission_pct*100:.2f}%, slippage={slippage_pct*100:.3f}%")
    
    def reset(self):
        """Reset backtest state"""
        self.current_balance = self.initial_balance
        self.peak_balance = self.initial_balance
        self.trades: List[Trade] = []
        self.positions: Dict = {}
        self.equity_curve: List[Dict] = []
        self.current_time: Optional[datetime] = None
        
    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        stop_loss: float,
        take_profit: Optional[float] = None,
        entry_time: Optional[datetime] = None,
        regime: Optional[str] = None,
        entry_score: Optional[float] = None
    ) -> Optional[str]:
        """
        Open a new position
        
        Args:
            symbol: Trading symbol
            side: 'long' or 'short'
            entry_price: Entry price
            size: Position size in base asset
            stop_loss: Stop loss price
            take_profit: Take profit price (optional)
            entry_time: Entry timestamp
            regime: Market regime (optional)
            entry_score: Entry score (optional)
            
        Returns:
            position_id or None if failed
        """
        entry_time = entry_time or self.current_time or datetime.now()
        
        # Calculate position value
        position_value = size * entry_price
        
        # Calculate commission
        commission = position_value * self.commission_pct
        
        # Check if enough balance
        total_cost = position_value + commission
        if total_cost > self.current_balance:
            logger.warning(f"Insufficient balance: ${self.current_balance:.2f} < ${total_cost:.2f}")
            return None
        
        # Apply slippage (simulates real market conditions)
        if side == 'long':
            entry_price *= (1 + self.slippage_pct)
        else:
            entry_price *= (1 - self.slippage_pct)
        
        # Create position
        position_id = f"{symbol}-{side}-{len(self.positions)+1}"
        
        self.positions[position_id] = {
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'size': size,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'entry_time': entry_time,
            'regime': regime,
            'entry_score': entry_score,
            'commission_paid': commission,
        }
        
        # Deduct from balance
        self.current_balance -= total_cost
        
        logger.debug(f"Opened {side.upper()} {size} {symbol} @ ${entry_price:.4f}, "
                    f"SL: ${stop_loss:.4f}, Commission: ${commission:.2f}")
        
        return position_id
    
    def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_time: Optional[datetime] = None,
        exit_reason: str = "manual"
    ) -> Optional[Trade]:
        """
        Close an open position
        
        Args:
            position_id: Position identifier
            exit_price: Exit price
            exit_time: Exit timestamp
            exit_reason: Reason for exit
            
        Returns:
            Trade object or None if failed
        """
        if position_id not in self.positions:
            logger.warning(f"Position not found: {position_id}")
            return None
        
        exit_time = exit_time or self.current_time or datetime.now()
        
        pos = self.positions[position_id]
        
        # Apply slippage
        if pos['side'] == 'long':
            exit_price *= (1 - self.slippage_pct)
        else:
            exit_price *= (1 + self.slippage_pct)
        
        # Calculate P&L
        if pos['side'] == 'long':
            pnl_before_commission = (exit_price - pos['entry_price']) * pos['size']
        else:  # short
            pnl_before_commission = (pos['entry_price'] - exit_price) * pos['size']
        
        # Exit commission
        exit_value = pos['size'] * exit_price
        exit_commission = exit_value * self.commission_pct
        
        # Net P&L
        total_commission = pos['commission_paid'] + exit_commission
        pnl = pnl_before_commission - total_commission
        pnl_pct = (pnl / (pos['size'] * pos['entry_price'])) * 100
        
        # Return capital + P&L
        self.current_balance += exit_value + pnl
        
        # Update peak
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        
        # Create trade record
        trade = Trade(
            entry_time=pos['entry_time'],
            exit_time=exit_time,
            symbol=pos['symbol'],
            side=pos['side'],
            entry_price=pos['entry_price'],
            exit_price=exit_price,
            size=pos['size'],
            pnl=pnl,
            pnl_pct=pnl_pct,
            commission=total_commission,
            stop_loss=pos['stop_loss'],
            take_profit=pos.get('take_profit'),
            regime=pos.get('regime'),
            entry_score=pos.get('entry_score'),
            exit_reason=exit_reason
        )
        
        self.trades.append(trade)
        
        # Remove position
        del self.positions[position_id]
        
        logger.debug(f"Closed {pos['side'].upper()} {pos['symbol']} @ ${exit_price:.4f}, "
                    f"P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%), Reason: {exit_reason}")
        
        return trade
    
    def update_equity_curve(self, timestamp: datetime, current_prices: Dict[str, float]):
        """
        Update equity curve with current market prices
        
        Args:
            timestamp: Current timestamp
            current_prices: Dict of symbol -> current price
        """
        self.current_time = timestamp
        
        # Calculate unrealized P&L from open positions
        unrealized_pnl = 0.0
        for pos_id, pos in self.positions.items():
            symbol = pos['symbol']
            if symbol in current_prices:
                current_price = current_prices[symbol]
                
                if pos['side'] == 'long':
                    position_pnl = (current_price - pos['entry_price']) * pos['size']
                else:
                    position_pnl = (pos['entry_price'] - current_price) * pos['size']
                
                unrealized_pnl += position_pnl
        
        # Total equity = cash + unrealized P&L
        total_equity = self.current_balance + unrealized_pnl
        
        self.equity_curve.append({
            'timestamp': timestamp,
            'balance': self.current_balance,
            'unrealized_pnl': unrealized_pnl,
            'total_equity': total_equity,
            'open_positions': len(self.positions)
        })
    
    def calculate_metrics(self) -> BacktestResults:
        """
        Calculate comprehensive performance metrics
        
        Returns:
            BacktestResults object
        """
        if not self.trades:
            logger.warning("No trades to analyze")
            return self._empty_results()
        
        # Convert equity curve to DataFrame
        equity_df = pd.DataFrame(self.equity_curve)
        if not equity_df.empty:
            equity_df.set_index('timestamp', inplace=True)
        
        # Basic metrics
        final_balance = self.current_balance
        total_pnl = final_balance - self.initial_balance
        total_return_pct = (total_pnl / self.initial_balance) * 100
        
        # Trade statistics
        total_trades = len(self.trades)
        winning_trades = sum(1 for t in self.trades if t.pnl > 0)
        losing_trades = sum(1 for t in self.trades if t.pnl < 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # Win/Loss metrics
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        losses = [t.pnl for t in self.trades if t.pnl < 0]
        
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        avg_win_pct = np.mean([t.pnl_pct for t in self.trades if t.pnl > 0]) if wins else 0
        avg_loss_pct = np.mean([t.pnl_pct for t in self.trades if t.pnl < 0]) if losses else 0
        
        largest_win = max(wins) if wins else 0
        largest_loss = min(losses) if losses else 0
        
        # Profit factor
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Risk:Reward ratio
        risk_reward_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        # Expectancy
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        
        # Expectancy in R (risk units)
        avg_risk = abs(avg_loss) if avg_loss != 0 else 1
        expectancy_r = expectancy / avg_risk if avg_risk != 0 else 0
        
        # Sharpe ratio
        if not equity_df.empty and len(equity_df) > 1:
            returns = equity_df['total_equity'].pct_change().dropna()
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
            
            # Sortino ratio (uses downside deviation)
            downside_returns = returns[returns < 0]
            downside_std = downside_returns.std() if len(downside_returns) > 0 else returns.std()
            sortino_ratio = (returns.mean() / downside_std) * np.sqrt(252) if downside_std > 0 else 0
        else:
            sharpe_ratio = 0
            sortino_ratio = 0
        
        # Maximum drawdown
        if not equity_df.empty:
            equity_curve = equity_df['total_equity']
            cummax = equity_curve.cummax()
            drawdown = (equity_curve - cummax) / cummax
            max_drawdown_pct = abs(drawdown.min()) * 100 if not drawdown.empty else 0
            max_drawdown = abs((equity_curve - cummax).min()) if not drawdown.empty else 0
        else:
            max_drawdown = 0
            max_drawdown_pct = 0
        
        # Time metrics
        hold_times = [(t.exit_time - t.entry_time) for t in self.trades if t.exit_time]
        avg_hold_time = np.mean(hold_times) if hold_times else timedelta(0)
        
        total_duration = (self.trades[-1].exit_time - self.trades[0].entry_time) if len(self.trades) > 0 and self.trades[-1].exit_time else timedelta(0)
        
        # Monthly returns
        if not equity_df.empty:
            monthly_equity = equity_df['total_equity'].resample('ME').last()
            monthly_returns = monthly_equity.pct_change() * 100
        else:
            monthly_returns = pd.Series()
        
        # Regime statistics (if available)
        regime_stats = self._calculate_regime_stats()
        
        return BacktestResults(
            initial_balance=self.initial_balance,
            final_balance=final_balance,
            total_pnl=total_pnl,
            total_return_pct=total_return_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            avg_win=avg_win,
            avg_win_pct=avg_win_pct,
            avg_loss=avg_loss,
            avg_loss_pct=avg_loss_pct,
            largest_win=largest_win,
            largest_loss=largest_loss,
            risk_reward_ratio=risk_reward_ratio,
            expectancy=expectancy,
            expectancy_r=expectancy_r,
            avg_hold_time=avg_hold_time,
            total_duration=total_duration,
            trades=self.trades,
            equity_curve=equity_df,
            monthly_returns=monthly_returns,
            regime_stats=regime_stats
        )
    
    def _calculate_regime_stats(self) -> Optional[Dict]:
        """Calculate statistics broken down by market regime"""
        regime_trades = {}
        
        for trade in self.trades:
            if trade.regime:
                if trade.regime not in regime_trades:
                    regime_trades[trade.regime] = []
                regime_trades[trade.regime].append(trade)
        
        if not regime_trades:
            return None
        
        stats = {}
        for regime, trades in regime_trades.items():
            wins = [t for t in trades if t.pnl > 0]
            
            stats[regime] = {
                'trades': len(trades),
                'wins': len(wins),
                'win_rate': len(wins) / len(trades) if trades else 0,
                'avg_pnl': np.mean([t.pnl for t in trades]),
                'total_pnl': sum(t.pnl for t in trades),
            }
        
        return stats
    
    def _empty_results(self) -> BacktestResults:
        """Return empty results when no trades"""
        return BacktestResults(
            initial_balance=self.initial_balance,
            final_balance=self.current_balance,
            total_pnl=0,
            total_return_pct=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0,
            profit_factor=0,
            sharpe_ratio=0,
            sortino_ratio=0,
            max_drawdown=0,
            max_drawdown_pct=0,
            avg_win=0,
            avg_win_pct=0,
            avg_loss=0,
            avg_loss_pct=0,
            largest_win=0,
            largest_loss=0,
            risk_reward_ratio=0,
            expectancy=0,
            expectancy_r=0,
            avg_hold_time=timedelta(0),
            total_duration=timedelta(0),
            trades=[],
            equity_curve=pd.DataFrame(),
            monthly_returns=pd.Series(),
            regime_stats=None
        )
    
    def export_results(self, results: BacktestResults, output_path: str):
        """
        Export results to JSON file
        
        Args:
            results: BacktestResults object
            output_path: Path to output file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(results.to_dict(), f, indent=2, default=str)
        
        logger.info(f"Results exported to {output_path}")


# Example usage
if __name__ == "__main__":
    # Create backtest engine
    engine = UnifiedBacktestEngine(initial_balance=10000.0)
    
    # Simulate some trades
    pos1 = engine.open_position(
        symbol="BTC-USD",
        side="long",
        entry_price=50000.0,
        size=0.1,
        stop_loss=49000.0,
        take_profit=52000.0,
        entry_time=datetime(2024, 1, 1, 10, 0),
        regime="trending"
    )
    
    engine.update_equity_curve(datetime(2024, 1, 1, 12, 0), {"BTC-USD": 50500.0})
    
    engine.close_position(
        pos1,
        exit_price=51000.0,
        exit_time=datetime(2024, 1, 1, 14, 0),
        exit_reason="take_profit"
    )
    
    # Calculate and print results
    results = engine.calculate_metrics()
    results.print_summary()
