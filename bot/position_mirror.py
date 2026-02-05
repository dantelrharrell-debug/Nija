"""
NIJA Live Position Mirror

Provides real-time view of current open positions even when broker UIs lag.
This is the third visibility layer: "Live Position Mirror"

Features:
- Shows current open positions across all brokers
- Updates in real-time as trades execute
- Doesn't depend on broker API responsiveness
- Tracks entry price, current P&L, stop-loss, take-profit levels
- Shows position health and risk metrics

Author: NIJA Trading Systems
Version: 1.0
Date: January 2026
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import json
import os

logger = logging.getLogger("nija.position_mirror")


@dataclass
class PositionSnapshot:
    """
    Snapshot of an open position.

    This is NIJA's internal view of the position, updated in real-time
    as trades execute, regardless of broker API lag.
    """
    position_id: str
    symbol: str
    broker: str
    side: str  # 'long' or 'short'
    entry_price: float
    current_price: float
    position_size: float  # USD value
    quantity: float  # Base currency quantity
    entry_time: str  # ISO format
    stop_loss: float
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    take_profit_3: Optional[float] = None
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    fees_paid: float = 0.0
    risk_amount: float = 0.0  # Amount at risk if stop-loss hits
    hold_time_minutes: int = 0
    status: str = "active"  # active, partial_exit, closing
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class LivePositionMirror:
    """
    Real-time position tracking system.

    This maintains NIJA's view of all open positions, updating immediately
    as trades execute without waiting for broker confirmations.
    """

    def __init__(self, data_dir: str = "./data/positions"):
        """
        Initialize position mirror.

        Args:
            data_dir: Directory to store position data
        """
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        # Active positions indexed by position_id
        self.positions: Dict[str, PositionSnapshot] = {}

        # Position file
        self.positions_file = os.path.join(data_dir, "live_positions.json")

        # Load existing positions
        self._load_positions()

        logger.info(f"Live Position Mirror initialized with {len(self.positions)} active positions")

    def _load_positions(self) -> None:
        """Load positions from file."""
        if not os.path.exists(self.positions_file):
            return

        try:
            with open(self.positions_file, 'r') as f:
                data = json.load(f)
                for pos_id, pos_dict in data.items():
                    self.positions[pos_id] = PositionSnapshot(**pos_dict)
            logger.info(f"Loaded {len(self.positions)} positions from {self.positions_file}")
        except Exception as e:
            logger.error(f"Error loading positions: {e}")

    def _save_positions(self) -> None:
        """Save positions to file."""
        try:
            data = {pos_id: pos.to_dict() for pos_id, pos in self.positions.items()}
            with open(self.positions_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving positions: {e}")

    def open_position(self, position_id: str, symbol: str, broker: str,
                     side: str, entry_price: float, position_size: float,
                     quantity: float, stop_loss: float,
                     take_profit_levels: Optional[Dict[str, float]] = None,
                     notes: str = "") -> None:
        """
        Record a new position opening.

        Args:
            position_id: Unique position identifier
            symbol: Trading pair
            broker: Broker name
            side: 'long' or 'short'
            entry_price: Entry price
            position_size: Position size in USD
            quantity: Quantity in base currency
            stop_loss: Stop-loss price
            take_profit_levels: Dict with tp1, tp2, tp3 (optional)
            notes: Optional notes
        """
        tp_levels = take_profit_levels or {}

        # Calculate risk amount
        if side == 'long':
            risk_amount = (entry_price - stop_loss) * quantity
        else:  # short
            risk_amount = (stop_loss - entry_price) * quantity

        position = PositionSnapshot(
            position_id=position_id,
            symbol=symbol,
            broker=broker,
            side=side,
            entry_price=entry_price,
            current_price=entry_price,
            position_size=position_size,
            quantity=quantity,
            entry_time=datetime.now().isoformat(),
            stop_loss=stop_loss,
            take_profit_1=tp_levels.get('tp1'),
            take_profit_2=tp_levels.get('tp2'),
            take_profit_3=tp_levels.get('tp3'),
            risk_amount=risk_amount,
            notes=notes
        )

        self.positions[position_id] = position
        self._save_positions()

        logger.info(f"Position opened: {position_id} - {side.upper()} {symbol} @ ${entry_price:.2f} on {broker}")

    def update_position_price(self, position_id: str, current_price: float) -> Optional[PositionSnapshot]:
        """
        Update current price and recalculate P&L for a position.

        Args:
            position_id: Position identifier
            current_price: Current market price

        Returns:
            Updated PositionSnapshot or None if position not found
        """
        if position_id not in self.positions:
            logger.warning(f"Position {position_id} not found for price update")
            return None

        position = self.positions[position_id]
        position.current_price = current_price

        # Calculate unrealized P&L
        if position.side == 'long':
            pnl_pct = ((current_price - position.entry_price) / position.entry_price) * 100
        else:  # short
            pnl_pct = ((position.entry_price - current_price) / position.entry_price) * 100

        position.unrealized_pnl_pct = pnl_pct
        position.unrealized_pnl = (pnl_pct / 100) * position.position_size

        # Calculate hold time
        entry_time = datetime.fromisoformat(position.entry_time)
        hold_time = datetime.now() - entry_time
        position.hold_time_minutes = int(hold_time.total_seconds() / 60)

        self._save_positions()

        return position

    def close_position(self, position_id: str, exit_price: float,
                      exit_reason: str, fees: float = 0.0) -> Optional[Dict[str, Any]]:
        """
        Close a position.

        Args:
            position_id: Position identifier
            exit_price: Exit price
            exit_reason: Reason for closing
            fees: Total fees paid

        Returns:
            Position summary dict or None if position not found
        """
        if position_id not in self.positions:
            logger.warning(f"Position {position_id} not found for closing")
            return None

        position = self.positions[position_id]

        # Final P&L calculation
        if position.side == 'long':
            pnl_pct = ((exit_price - position.entry_price) / position.entry_price) * 100
        else:  # short
            pnl_pct = ((position.entry_price - exit_price) / position.entry_price) * 100

        gross_pnl = (pnl_pct / 100) * position.position_size
        net_pnl = gross_pnl - fees

        summary = {
            'position_id': position_id,
            'symbol': position.symbol,
            'broker': position.broker,
            'side': position.side,
            'entry_price': position.entry_price,
            'exit_price': exit_price,
            'entry_time': position.entry_time,
            'exit_time': datetime.now().isoformat(),
            'hold_time_minutes': position.hold_time_minutes,
            'gross_pnl': gross_pnl,
            'fees': fees,
            'net_pnl': net_pnl,
            'pnl_pct': pnl_pct,
            'exit_reason': exit_reason,
            # PROFIT GATE: No neutral outcomes - if not profitable, it's a loss
            'outcome': 'win' if net_pnl > 0 else 'loss'
        }

        # Remove from active positions
        del self.positions[position_id]
        self._save_positions()

        logger.info(f"Position closed: {position_id} - {exit_reason} (P&L: ${net_pnl:.2f})")

        return summary

    def partial_exit(self, position_id: str, exit_pct: float,
                    exit_price: float, reason: str) -> Optional[Dict[str, Any]]:
        """
        Record a partial position exit.

        Args:
            position_id: Position identifier
            exit_pct: Percentage of position to exit (0.0-1.0)
            exit_price: Exit price
            reason: Reason for partial exit

        Returns:
            Partial exit summary or None if position not found
        """
        if position_id not in self.positions:
            logger.warning(f"Position {position_id} not found for partial exit")
            return None

        position = self.positions[position_id]

        # Calculate P&L for exited portion
        exit_quantity = position.quantity * exit_pct
        exit_size = position.position_size * exit_pct

        if position.side == 'long':
            pnl_pct = ((exit_price - position.entry_price) / position.entry_price) * 100
        else:
            pnl_pct = ((position.entry_price - exit_price) / position.entry_price) * 100

        partial_pnl = (pnl_pct / 100) * exit_size

        # Reduce position size
        position.quantity *= (1.0 - exit_pct)
        position.position_size *= (1.0 - exit_pct)
        position.status = "partial_exit"

        self._save_positions()

        summary = {
            'position_id': position_id,
            'symbol': position.symbol,
            'exit_pct': exit_pct * 100,
            'exit_quantity': exit_quantity,
            'exit_price': exit_price,
            'partial_pnl': partial_pnl,
            'remaining_size': position.position_size,
            'reason': reason
        }

        logger.info(f"Partial exit: {position_id} - {exit_pct*100:.1f}% @ ${exit_price:.2f} ({reason})")

        return summary

    def get_position(self, position_id: str) -> Optional[PositionSnapshot]:
        """
        Get a specific position.

        Args:
            position_id: Position identifier

        Returns:
            PositionSnapshot or None if not found
        """
        return self.positions.get(position_id)

    def get_all_positions(self) -> List[PositionSnapshot]:
        """
        Get all active positions.

        Returns:
            List of PositionSnapshot objects
        """
        return list(self.positions.values())

    def get_positions_by_broker(self, broker: str) -> List[PositionSnapshot]:
        """
        Get all positions for a specific broker.

        Args:
            broker: Broker name

        Returns:
            List of PositionSnapshot objects
        """
        return [pos for pos in self.positions.values() if pos.broker.lower() == broker.lower()]

    def get_positions_by_symbol(self, symbol: str) -> List[PositionSnapshot]:
        """
        Get all positions for a specific symbol.

        Args:
            symbol: Trading pair

        Returns:
            List of PositionSnapshot objects
        """
        return [pos for pos in self.positions.values() if pos.symbol == symbol]

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """
        Get overall portfolio summary.

        Returns:
            Dict with portfolio metrics
        """
        total_positions = len(self.positions)
        total_size = sum(pos.position_size for pos in self.positions.values())
        total_unrealized_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())

        # Group by broker
        by_broker = {}
        for pos in self.positions.values():
            if pos.broker not in by_broker:
                by_broker[pos.broker] = {
                    'count': 0,
                    'total_size': 0.0,
                    'total_pnl': 0.0
                }
            by_broker[pos.broker]['count'] += 1
            by_broker[pos.broker]['total_size'] += pos.position_size
            by_broker[pos.broker]['total_pnl'] += pos.unrealized_pnl

        # Group by side
        long_positions = [p for p in self.positions.values() if p.side == 'long']
        short_positions = [p for p in self.positions.values() if p.side == 'short']

        return {
            'total_positions': total_positions,
            'total_size': total_size,
            'total_unrealized_pnl': total_unrealized_pnl,
            'long_positions': len(long_positions),
            'short_positions': len(short_positions),
            'by_broker': by_broker,
            'timestamp': datetime.now().isoformat()
        }

    def update_all_prices(self, price_updates: Dict[str, float]) -> None:
        """
        Batch update prices for multiple positions.

        Args:
            price_updates: Dict mapping symbol to current price
        """
        for position in self.positions.values():
            if position.symbol in price_updates:
                self.update_position_price(position.position_id, price_updates[position.symbol])


# Global position mirror instance
_position_mirror_instance: Optional[LivePositionMirror] = None


def get_position_mirror() -> LivePositionMirror:
    """
    Get the global position mirror instance.

    Returns:
        LivePositionMirror instance
    """
    global _position_mirror_instance

    if _position_mirror_instance is None:
        _position_mirror_instance = LivePositionMirror()

    return _position_mirror_instance
