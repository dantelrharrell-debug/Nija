"""
NIJA Position Tracker
Persistent storage of position entry prices and profit/loss tracking

This module solves the problem that Coinbase API doesn't return entry prices,
making it impossible to calculate profit/loss for exit decisions.
"""

import json
import os
import logging
from typing import Dict, Optional, List
from datetime import datetime
from threading import Lock

logger = logging.getLogger("nija")


class PositionTracker:
    """
    Tracks entry prices and manages position P&L for profit-based exits.

    Persists data to JSON file to survive bot restarts.
    """

    def __init__(self, storage_file: str = "positions.json"):
        """
        Initialize position tracker.

        Args:
            storage_file: Path to JSON file for persistence
        """
        self.storage_file = os.path.abspath(storage_file)
        self.positions: Dict[str, Dict] = {}
        self.lock = Lock()

        # Load existing positions
        self._load_positions()

        logger.info(f"PositionTracker initialized: {len(self.positions)} tracked positions")

    def _load_positions(self):
        """Load positions from JSON file"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r') as f:
                    data = json.load(f)
                    self.positions = data.get('positions', {})
                logger.info(f"Loaded {len(self.positions)} positions from {self.storage_file}")
            else:
                logger.info("No existing positions file found - starting fresh")
        except Exception as e:
            logger.error(f"Error loading positions: {e}")
            self.positions = {}

    def _save_positions(self):
        """Save positions to JSON file (assumes lock is already held)"""
        try:
            data = {
                'positions': self.positions,
                'last_updated': datetime.now().isoformat()
            }
            # Write to temp file first, then rename for atomicity
            temp_file = self.storage_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self.storage_file)
        except Exception as e:
            logger.error(f"Error saving positions: {e}")

    def track_entry(self, symbol: str, entry_price: float, quantity: float,
                   size_usd: float, strategy: str = "APEX_v7.1", 
                   position_source: str = "nija_strategy") -> bool:
        """
        Record a new position entry.

        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            entry_price: Entry price
            quantity: Quantity of asset purchased
            size_usd: Position size in USD
            strategy: Strategy name for tracking
            position_source: Source of position ('nija_strategy', 'broker_existing', 'manual')

        Returns:
            True if tracked successfully
        """
        try:
            with self.lock:
                # If position already exists, calculate average entry price
                if symbol in self.positions:
                    existing = self.positions[symbol]
                    old_qty = existing['quantity']
                    old_price = existing['entry_price']
                    old_size = existing['size_usd']

                    # Calculate new weighted average entry price correctly
                    # Formula: (old_qty * old_price + new_qty * new_price) / total_qty
                    total_qty = old_qty + quantity
                    total_cost = (old_qty * old_price) + (quantity * entry_price)
                    avg_price = total_cost / total_qty if total_qty > 0 else entry_price
                    total_size = old_size + size_usd

                    self.positions[symbol] = {
                        'entry_price': avg_price,
                        'quantity': total_qty,
                        'size_usd': total_size,
                        'first_entry_time': existing['first_entry_time'],
                        'last_entry_time': datetime.now().isoformat(),
                        'strategy': strategy,
                        'num_adds': existing.get('num_adds', 0) + 1,
                        'previous_profit_pct': existing.get('previous_profit_pct', 0.0),  # Preserve previous profit tracking
                        'position_source': existing.get('position_source', position_source)  # Keep original source
                    }
                    logger.info(f"Updated position {symbol}: avg_entry=${avg_price:.2f}, qty={total_qty:.8f}")
                else:
                    # New position
                    self.positions[symbol] = {
                        'entry_price': entry_price,
                        'quantity': quantity,
                        'size_usd': size_usd,
                        'first_entry_time': datetime.now().isoformat(),
                        'last_entry_time': datetime.now().isoformat(),
                        'strategy': strategy,
                        'num_adds': 0,
                        'previous_profit_pct': 0.0,  # Initialize previous profit tracking
                        'position_source': position_source  # Track position source
                    }
                    logger.info(f"Tracking new position {symbol}: entry=${entry_price:.2f}, qty={quantity:.8f}, source={position_source}")

                self._save_positions()
                return True
        except Exception as e:
            logger.error(f"Error tracking entry for {symbol}: {e}")
            return False

    def track_exit(self, symbol: str, exit_quantity: float = None) -> bool:
        """
        Record a position exit (partial or full).

        Args:
            symbol: Trading symbol
            exit_quantity: Quantity sold (None = full exit)

        Returns:
            True if tracked successfully
        """
        try:
            with self.lock:
                if symbol not in self.positions:
                    logger.warning(f"Attempted to exit untracked position: {symbol}")
                    return False

                if exit_quantity is None:
                    # Full exit - remove position
                    del self.positions[symbol]
                    logger.info(f"Removed position {symbol} (full exit)")
                else:
                    # Partial exit - reduce quantity
                    position = self.positions[symbol]
                    remaining_qty = position['quantity'] - exit_quantity

                    if remaining_qty <= 0:
                        # Exit consumed entire position
                        del self.positions[symbol]
                        logger.info(f"Removed position {symbol} (partial exit cleared position)")
                    else:
                        # Update remaining quantity and proportional size
                        # Preserve proportional cost basis
                        remaining_size = position['size_usd'] * (remaining_qty / position['quantity'])
                        position['quantity'] = remaining_qty
                        position['size_usd'] = remaining_size
                        logger.info(f"Reduced position {symbol}: remaining_qty={remaining_qty:.8f}, remaining_size=${remaining_size:.2f}")

                self._save_positions()
                return True
        except Exception as e:
            logger.error(f"Error tracking exit for {symbol}: {e}")
            return False

    def get_position(self, symbol: str) -> Optional[Dict]:
        """
        Get tracked position data.

        Args:
            symbol: Trading symbol

        Returns:
            Position dict with entry_price, quantity, size_usd, etc. or None
        """
        with self.lock:
            return self.positions.get(symbol)

    def calculate_pnl(self, symbol: str, current_price: float) -> Optional[Dict]:
        """
        Calculate profit/loss for a position.

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            Dict with pnl_dollars, pnl_percent, current_value, previous_profit_pct, or None if not tracked
        """
        position = self.get_position(symbol)
        if not position:
            return None

        entry_price = position['entry_price']
        quantity = position['quantity']
        entry_value = position['size_usd']

        current_value = quantity * current_price
        pnl_dollars = current_value - entry_value
        # NORMALIZED FORMAT (Option A - Fractional): -0.01 = -1%, not -1.0 = -1%
        pnl_pct = (pnl_dollars / entry_value) if entry_value > 0 else 0

        # CRITICAL: Validate PnL is in fractional format
        # Large values (>1 or <-1) could indicate bugs or extreme market moves (>100%)
        # This is a monitoring warning - no corrective action needed, just alerting
        if abs(pnl_pct) >= 1.0:
            logger.warning(f"⚠️ Large PnL detected for {symbol}: {pnl_pct*100:.2f}% - this is unusual but valid for extreme moves")

        # Track previous profit for immediate exit on profit decrease
        # NIJA takes profit as soon as profit starts to decrease
        with self.lock:
            previous_profit = position.get('previous_profit_pct', 0.0)
            # Update previous profit for next check
            position['previous_profit_pct'] = pnl_pct
            # Save updated previous profit
            self._save_positions()

        return {
            'symbol': symbol,
            'entry_price': entry_price,
            'current_price': current_price,
            'quantity': quantity,
            'entry_value': entry_value,
            'current_value': current_value,
            'pnl_dollars': pnl_dollars,
            'pnl_percent': pnl_pct,  # FRACTIONAL: -0.01 = -1%, -0.12 = -12%
            'previous_profit_pct': previous_profit  # Profit from previous check
        }

    def get_all_positions(self) -> List[str]:
        """Get list of all tracked symbols"""
        with self.lock:
            return list(self.positions.keys())

    def sync_with_broker(self, broker_positions: List[Dict]) -> int:
        """
        Sync tracker with actual broker positions.
        Remove any tracked positions that no longer exist at broker.

        Args:
            broker_positions: List of position dicts from broker

        Returns:
            Number of positions removed
        """
        try:
            with self.lock:
                broker_symbols = {pos.get('symbol') for pos in broker_positions if pos.get('symbol')}
                tracked_symbols = set(self.positions.keys())

                # Find positions we're tracking but broker doesn't have
                orphaned = tracked_symbols - broker_symbols

                if orphaned:
                    logger.info(f"Removing {len(orphaned)} orphaned tracked positions: {orphaned}")
                    for symbol in orphaned:
                        del self.positions[symbol]
                    self._save_positions()
                    return len(orphaned)

                return 0
        except Exception as e:
            logger.error(f"Error syncing with broker: {e}")
            return 0

    def clear_all(self) -> bool:
        """Clear all tracked positions (emergency use only)"""
        try:
            with self.lock:
                count = len(self.positions)
                self.positions = {}
                self._save_positions()
                logger.warning(f"Cleared all {count} tracked positions")
                return True
        except Exception as e:
            logger.error(f"Error clearing positions: {e}")
            return False
