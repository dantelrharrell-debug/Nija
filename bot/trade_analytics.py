"""
NIJA Trade Analytics Module
Tracks fees, performance metrics, and generates reports
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

logger = logging.getLogger("nija.analytics")


@dataclass
class TradeRecord:
    """Single trade record with all details"""
    timestamp: str
    symbol: str
    side: str  # BUY or SELL
    entry_price: float
    exit_price: Optional[float] = None
    size_usd: float = 0.0
    quantity: float = 0.0

    # Fees
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    total_fees: float = 0.0

    # Performance
    gross_profit: float = 0.0  # Before fees
    net_profit: float = 0.0    # After fees
    profit_pct: float = 0.0

    # Execution details
    expected_price: float = 0.0
    actual_fill_price: float = 0.0
    slippage: float = 0.0
    slippage_pct: float = 0.0

    # Risk management
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_reason: str = ""

    # Trade duration
    entry_time: str = ""
    exit_time: Optional[str] = None
    duration_seconds: float = 0.0


class TradeAnalytics:
    """
    Comprehensive trade analytics and performance tracking
    """

    # Coinbase Advanced Trade fee tier (default: taker)
    COINBASE_TAKER_FEE = 0.006  # 0.6%
    COINBASE_MAKER_FEE = 0.004  # 0.4%

    def __init__(self, data_dir: str = "./data"):
        """
        Initialize analytics tracker

        Args:
            data_dir: Directory to store trade history and reports
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)

        self.trades_file = self.data_dir / "trade_history.json"
        self.daily_summary_file = self.data_dir / "daily_summary.json"

        # Load existing trade history
        self.trades: List[TradeRecord] = self._load_trades()

        # Session tracking
        self.session_start = datetime.now()
        self.session_trades: List[TradeRecord] = []

        logger.info(f"📊 Analytics initialized - {len(self.trades)} historical trades loaded")

    def calculate_entry_fee(self, size_usd: float, is_maker: bool = False) -> float:
        """
        Calculate Coinbase fee for entry order

        Args:
            size_usd: Position size in USD
            is_maker: True if maker order (limit), False if taker (market)

        Returns:
            Fee amount in USD
        """
        fee_rate = self.COINBASE_MAKER_FEE if is_maker else self.COINBASE_TAKER_FEE
        return size_usd * fee_rate

    def calculate_exit_fee(self, size_usd: float, is_maker: bool = False) -> float:
        """Calculate Coinbase fee for exit order"""
        return self.calculate_entry_fee(size_usd, is_maker)

    def record_entry(self, symbol: str, side: str, price: float, size_usd: float,
                    expected_price: float, actual_fill_price: float,
                    stop_loss: float = 0.0, take_profit: float = 0.0) -> str:
        """
        Record trade entry with fee calculation

        Returns:
            Trade ID for tracking
        """
        entry_fee = self.calculate_entry_fee(size_usd)
        slippage = actual_fill_price - expected_price
        slippage_pct = (slippage / expected_price) * 100 if expected_price > 0 else 0.0

        quantity = size_usd / actual_fill_price if actual_fill_price > 0 else 0.0

        trade = TradeRecord(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            side=side,
            entry_price=actual_fill_price,
            size_usd=size_usd,
            quantity=quantity,
            entry_fee=entry_fee,
            expected_price=expected_price,
            actual_fill_price=actual_fill_price,
            slippage=slippage,
            slippage_pct=slippage_pct,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.now().isoformat()
        )

        self.session_trades.append(trade)

        logger.info(f"💰 Entry recorded: {symbol} {side}")
        logger.info(f"   Size: ${size_usd:.2f} ({quantity:.6f} {symbol.split('-')[0]})")
        logger.info(f"   Entry fee: ${entry_fee:.4f} ({self.COINBASE_TAKER_FEE*100}%)")
        if abs(slippage_pct) > 0.01:
            logger.info(f"   Slippage: ${slippage:.4f} ({slippage_pct:+.2f}%)")

        return trade.timestamp

    def record_exit(self, symbol: str, exit_price: float, exit_reason: str = "manual") -> Optional[TradeRecord]:
        """
        Record trade exit and calculate performance

        Returns:
            Completed trade record with full P&L
        """
        # Find open trade for this symbol
        open_trade = None
        for trade in reversed(self.session_trades):
            if trade.symbol == symbol and trade.exit_price is None:
                open_trade = trade
                break

        if not open_trade:
            logger.warning(f"No open trade found for {symbol}")
            return None

        # Calculate exit fee
        exit_value = open_trade.quantity * exit_price
        exit_fee = self.calculate_exit_fee(exit_value)

        # Calculate P&L
        if open_trade.side == 'BUY':
            gross_profit = exit_value - open_trade.size_usd
        else:  # SELL/SHORT
            gross_profit = open_trade.size_usd - exit_value

        total_fees = open_trade.entry_fee + exit_fee
        net_profit = gross_profit - total_fees
        profit_pct = (net_profit / open_trade.size_usd) * 100

        # Calculate duration
        entry_dt = datetime.fromisoformat(open_trade.entry_time)
        exit_dt = datetime.now()
        duration = (exit_dt - entry_dt).total_seconds()

        # Update trade record
        open_trade.exit_price = exit_price
        open_trade.exit_fee = exit_fee
        open_trade.total_fees = total_fees
        open_trade.gross_profit = gross_profit
        open_trade.net_profit = net_profit
        open_trade.profit_pct = profit_pct
        open_trade.exit_reason = exit_reason
        open_trade.exit_time = exit_dt.isoformat()
        open_trade.duration_seconds = duration

        # Save to history
        self.trades.append(open_trade)
        self._save_trades()

        # Log results
        profit_emoji = "🟢" if net_profit > 0 else "🔴" if net_profit < 0 else "⚪"
        logger.info(f"{profit_emoji} Exit recorded: {symbol}")
        logger.info(f"   Entry: ${open_trade.entry_price:.6f} → Exit: ${exit_price:.6f}")
        logger.info(f"   Gross P&L: ${gross_profit:.4f}")
        logger.info(f"   Total fees: ${total_fees:.4f} (entry: ${open_trade.entry_fee:.4f} + exit: ${exit_fee:.4f})")
        logger.info(f"   Net P&L: ${net_profit:.4f} ({profit_pct:+.2f}%)")
        logger.info(f"   Duration: {duration:.0f}s ({duration/60:.1f}m)")
        logger.info(f"   Exit reason: {exit_reason}")

        return open_trade

    def get_session_stats(self) -> Dict:
        """Get statistics for current trading session"""
        completed = [t for t in self.session_trades if t.exit_price is not None]

        if not completed:
            return {
                'trades_count': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'total_fees': 0.0,
                'avg_profit': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'profit_factor': 0.0,
                'avg_duration_min': 0.0
            }

        wins = [t for t in completed if t.net_profit > 0]
        losses = [t for t in completed if t.net_profit < 0]

        total_pnl = sum(t.net_profit for t in completed)
        total_fees = sum(t.total_fees for t in completed)

        return {
            'trades_count': len(completed),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': (len(wins) / len(completed) * 100) if completed else 0.0,
            'total_pnl': total_pnl,
            'total_fees': total_fees,
            'avg_profit': total_pnl / len(completed) if completed else 0.0,
            'avg_win': sum(t.net_profit for t in wins) / len(wins) if wins else 0.0,
            'avg_loss': sum(t.net_profit for t in losses) / len(losses) if losses else 0.0,
            'best_trade': max((t.net_profit for t in completed), default=0.0),
            'worst_trade': min((t.net_profit for t in completed), default=0.0),
            'profit_factor': abs(sum(t.net_profit for t in wins) / sum(t.net_profit for t in losses)) if losses else float('inf'),
            'avg_duration_min': sum(t.duration_seconds for t in completed) / len(completed) / 60 if completed else 0.0
        }

    def print_session_report(self):
        """Print formatted session performance report"""
        stats = self.get_session_stats()

        logger.info("\n" + "="*70)
        logger.info("📊 SESSION PERFORMANCE REPORT")
        logger.info("="*70)
        logger.info(f"Total Trades: {stats['trades_count']}")
        logger.info(f"Wins: {stats['wins']} | Losses: {stats['losses']} | Win Rate: {stats['win_rate']:.1f}%")
        logger.info(f"")
        logger.info(f"💰 P&L:")
        logger.info(f"   Total P&L: ${stats['total_pnl']:.2f}")
        logger.info(f"   Total Fees: ${stats['total_fees']:.2f}")
        logger.info(f"   Net After Fees: ${stats['total_pnl']:.2f}")
        logger.info(f"")
        logger.info(f"📈 Averages:")
        logger.info(f"   Avg Profit per Trade: ${stats['avg_profit']:.4f}")
        logger.info(f"   Avg Winning Trade: ${stats['avg_win']:.4f}")
        logger.info(f"   Avg Losing Trade: ${stats['avg_loss']:.4f}")
        logger.info(f"   Avg Trade Duration: {stats['avg_duration_min']:.1f}m")
        logger.info(f"")
        logger.info(f"🎯 Best/Worst:")
        logger.info(f"   Best Trade: ${stats['best_trade']:.4f}")
        logger.info(f"   Worst Trade: ${stats['worst_trade']:.4f}")
        if stats['profit_factor'] != float('inf'):
            logger.info(f"   Profit Factor: {stats['profit_factor']:.2f}")
        logger.info("="*70 + "\n")

    def export_to_csv(self, filename: Optional[str] = None) -> str:
        """
        Export trade history to CSV

        Returns:
            Path to exported CSV file
        """
        if filename is None:
            filename = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        csv_path = self.data_dir / filename

        with open(csv_path, 'w') as f:
            # Header
            f.write("timestamp,symbol,side,entry_price,exit_price,size_usd,quantity,")
            f.write("entry_fee,exit_fee,total_fees,gross_profit,net_profit,profit_pct,")
            f.write("slippage,slippage_pct,duration_seconds,exit_reason\n")

            # Data rows
            for trade in self.trades:
                if trade.exit_price is not None:  # Only completed trades
                    f.write(f"{trade.timestamp},{trade.symbol},{trade.side},")
                    f.write(f"{trade.entry_price:.6f},{trade.exit_price:.6f},")
                    f.write(f"{trade.size_usd:.2f},{trade.quantity:.6f},")
                    f.write(f"{trade.entry_fee:.4f},{trade.exit_fee:.4f},{trade.total_fees:.4f},")
                    f.write(f"{trade.gross_profit:.4f},{trade.net_profit:.4f},{trade.profit_pct:.2f},")
                    f.write(f"{trade.slippage:.4f},{trade.slippage_pct:.2f},")
                    f.write(f"{trade.duration_seconds:.0f},{trade.exit_reason}\n")

        logger.info(f"📄 Trade history exported to {csv_path}")
        return str(csv_path)

    def _load_trades(self) -> List[TradeRecord]:
        """Load trade history from JSON file"""
        if not self.trades_file.exists():
            return []

        try:
            with open(self.trades_file, 'r') as f:
                data = json.load(f)
                return [TradeRecord(**t) for t in data]
        except Exception as e:
            logger.warning(f"Could not load trade history: {e}")
            return []

    def _save_trades(self):
        """Save trade history to JSON file"""
        try:
            with open(self.trades_file, 'w') as f:
                data = [asdict(t) for t in self.trades]
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save trade history: {e}")
