"""
NIJA Balance Models
===================

FIX 1: Balance Model - Split balances into 3 values per broker

This module defines the balance data structures that address the issue
where NIJA was only trading using free cash, not total equity.

BalanceSnapshot:
    - total_equity_usd: Total account value (cash + positions)
    - available_usd: Free cash available for new trades
    - locked_in_positions_usd: Value locked in open positions

UserBrokerState:
    - Tracks per-user, per-broker account state
    - Includes balance snapshot and open positions
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum


@dataclass
class BalanceSnapshot:
    """
    Three-part balance model for accurate trading capital tracking.
    
    This replaces the old single-value balance approach that caused
    NIJA to only trade with free cash instead of total equity.
    
    Attributes:
        total_equity_usd: Total account value (available + locked in positions)
        available_usd: Free cash available for new trades  
        locked_in_positions_usd: Value currently locked in open positions
        timestamp: When this snapshot was taken
        broker_name: Which broker this balance is from
    """
    total_equity_usd: float
    available_usd: float
    locked_in_positions_usd: float
    timestamp: datetime = field(default_factory=datetime.now)
    broker_name: str = ""
    
    def __post_init__(self):
        """Validate balance invariants."""
        # Allow small floating point differences
        epsilon = 0.01
        calculated_total = self.available_usd + self.locked_in_positions_usd
        
        if abs(calculated_total - self.total_equity_usd) > epsilon:
            # Log warning but don't fail - broker APIs can have slight discrepancies
            import logging
            logger = logging.getLogger('nija.balance')
            logger.warning(
                f"Balance snapshot mismatch for {self.broker_name}: "
                f"total_equity={self.total_equity_usd:.2f}, "
                f"available+locked={calculated_total:.2f} "
                f"(diff={abs(calculated_total - self.total_equity_usd):.2f})"
            )
    
    @property
    def utilization_pct(self) -> float:
        """Calculate percentage of capital locked in positions."""
        if self.total_equity_usd <= 0:
            return 0.0
        return (self.locked_in_positions_usd / self.total_equity_usd) * 100.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'total_equity_usd': self.total_equity_usd,
            'available_usd': self.available_usd,
            'locked_in_positions_usd': self.locked_in_positions_usd,
            'timestamp': self.timestamp.isoformat(),
            'broker_name': self.broker_name,
            'utilization_pct': self.utilization_pct
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'BalanceSnapshot':
        """Create from dictionary."""
        return cls(
            total_equity_usd=data['total_equity_usd'],
            available_usd=data['available_usd'],
            locked_in_positions_usd=data['locked_in_positions_usd'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            broker_name=data.get('broker_name', '')
        )


@dataclass
class UserBrokerState:
    """
    FIX 5: User Account Visibility
    
    Tracks the complete state of a user's account on a specific broker.
    This enables NIJA to properly snapshot and display user balances.
    
    Attributes:
        broker: Broker name (coinbase, kraken, alpaca)
        user_id: User identifier
        balance: Current balance snapshot
        open_positions: List of open position symbols
        last_updated: When this state was last refreshed
        connected: Whether the broker connection is active
    """
    broker: str
    user_id: str
    balance: BalanceSnapshot
    open_positions: List[Dict] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.now)
    connected: bool = True
    
    @property
    def total_equity(self) -> float:
        """Get total equity from balance snapshot."""
        return self.balance.total_equity_usd
    
    @property
    def available_cash(self) -> float:
        """Get available cash from balance snapshot."""
        return self.balance.available_usd
    
    @property
    def position_count(self) -> int:
        """Number of open positions."""
        return len(self.open_positions)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'broker': self.broker,
            'user_id': self.user_id,
            'balance': self.balance.to_dict(),
            'open_positions': self.open_positions,
            'last_updated': self.last_updated.isoformat(),
            'connected': self.connected,
            'position_count': self.position_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UserBrokerState':
        """Create from dictionary."""
        return cls(
            broker=data['broker'],
            user_id=data['user_id'],
            balance=BalanceSnapshot.from_dict(data['balance']),
            open_positions=data.get('open_positions', []),
            last_updated=datetime.fromisoformat(data['last_updated']),
            connected=data.get('connected', True)
        )


def create_balance_snapshot_from_broker_response(
    broker_name: str,
    total_balance: float,
    available_balance: float,
    positions_value: float = 0.0
) -> BalanceSnapshot:
    """
    Helper function to create BalanceSnapshot from broker API responses.
    
    Data sources by broker:
    - Coinbase: accounts + open positions
    - Kraken: Balance + OpenPositions  
    - Alpaca: equity vs buying_power
    
    Args:
        broker_name: Name of the broker
        total_balance: Total account value (equity)
        available_balance: Free cash available
        positions_value: Value locked in positions (if not already calculated)
        
    Returns:
        BalanceSnapshot with all three values populated
    """
    # Calculate locked value if not provided
    if positions_value == 0.0:
        locked_in_positions = total_balance - available_balance
        # Ensure non-negative (handle rounding errors)
        locked_in_positions = max(0.0, locked_in_positions)
    else:
        locked_in_positions = positions_value
    
    return BalanceSnapshot(
        total_equity_usd=total_balance,
        available_usd=available_balance,
        locked_in_positions_usd=locked_in_positions,
        broker_name=broker_name
    )


__all__ = [
    'BalanceSnapshot',
    'UserBrokerState',
    'create_balance_snapshot_from_broker_response'
]
