"""
NIJA Capital Reservation Manager
=================================

Prevents over-promising capital with small accounts by:
- Reserving capital per open position
- Only allowing new entries if free_capital_after_entry >= safety_buffer
- Preventing overlapping partial fills and silent leverage

Key Features:
- Per-position capital tracking
- Safety buffer enforcement
- Prevents capital fragmentation
- Thread-safe operations

Author: NIJA Trading Systems
Version: 1.0
Date: February 8, 2026
"""

import logging
import threading
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("nija.capital_reservation")


@dataclass
class PositionReservation:
    """Tracks capital reserved for a single position"""
    position_id: str
    symbol: str
    reserved_amount: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    account_id: str = "default"
    broker: str = "unknown"
    
    def __repr__(self):
        return (
            f"PositionReservation({self.symbol}, "
            f"${self.reserved_amount:.2f}, {self.position_id})"
        )


class CapitalReservationManager:
    """
    Manages capital reservations to prevent over-promising.
    
    Ensures that:
    1. Each open position has capital reserved
    2. New entries only allowed if sufficient free capital remains
    3. Safety buffer always maintained
    4. No silent leverage through fragmentation
    """
    
    def __init__(
        self,
        safety_buffer_pct: float = 0.20,  # 20% safety buffer
        min_free_capital_usd: float = 5.0  # Minimum $5 free capital
    ):
        """
        Initialize capital reservation manager.
        
        Args:
            safety_buffer_pct: Percentage of capital to keep as safety buffer (0.0-1.0)
            min_free_capital_usd: Minimum free capital in USD
        """
        self.safety_buffer_pct = safety_buffer_pct
        self.min_free_capital_usd = min_free_capital_usd
        
        # Track reservations
        self._reservations: Dict[str, PositionReservation] = {}
        self._lock = threading.Lock()
        
        logger.info(
            f"✅ Capital Reservation Manager initialized: "
            f"{self.safety_buffer_pct * 100:.1f}% safety buffer, "
            f"${self.min_free_capital_usd:.2f} min free capital"
        )
    
    def reserve_capital(
        self,
        position_id: str,
        amount: float,
        symbol: str,
        account_id: str = "default",
        broker: str = "unknown"
    ) -> bool:
        """
        Reserve capital for a position.
        
        Args:
            position_id: Unique position identifier
            amount: Amount to reserve (USD)
            symbol: Trading symbol
            account_id: Account identifier
            broker: Broker name
        
        Returns:
            bool: True if reserved successfully
        """
        with self._lock:
            if position_id in self._reservations:
                logger.warning(
                    f"⚠️ Position {position_id} already has reservation: "
                    f"{self._reservations[position_id]}"
                )
                return False
            
            reservation = PositionReservation(
                position_id=position_id,
                symbol=symbol,
                reserved_amount=amount,
                account_id=account_id,
                broker=broker
            )
            
            self._reservations[position_id] = reservation
            
            logger.info(
                f"✅ Reserved ${amount:.2f} for position {position_id} ({symbol})"
            )
            
            return True
    
    def release_capital(self, position_id: str) -> Optional[float]:
        """
        Release capital reservation for a closed position.
        
        Args:
            position_id: Position identifier
        
        Returns:
            Optional[float]: Amount released, or None if not found
        """
        with self._lock:
            if position_id not in self._reservations:
                logger.warning(
                    f"⚠️ No reservation found for position {position_id}"
                )
                return None
            
            reservation = self._reservations.pop(position_id)
            
            logger.info(
                f"✅ Released ${reservation.reserved_amount:.2f} "
                f"from position {position_id} ({reservation.symbol})"
            )
            
            return reservation.reserved_amount
    
    def update_reservation(
        self,
        position_id: str,
        new_amount: float
    ) -> bool:
        """
        Update capital reservation amount (e.g., after partial exit).
        
        Args:
            position_id: Position identifier
            new_amount: New reservation amount
        
        Returns:
            bool: True if updated successfully
        """
        with self._lock:
            if position_id not in self._reservations:
                logger.warning(
                    f"⚠️ Cannot update - no reservation for position {position_id}"
                )
                return False
            
            old_amount = self._reservations[position_id].reserved_amount
            self._reservations[position_id].reserved_amount = new_amount
            
            logger.info(
                f"📊 Updated reservation for {position_id}: "
                f"${old_amount:.2f} → ${new_amount:.2f}"
            )
            
            return True
    
    def get_total_reserved(self) -> float:
        """
        Get total reserved capital across all positions.
        
        Returns:
            float: Total reserved amount in USD
        """
        with self._lock:
            return sum(r.reserved_amount for r in self._reservations.values())
    
    def get_reserved_by_account(self, account_id: str) -> float:
        """
        Get total reserved capital for specific account.
        
        Args:
            account_id: Account identifier
        
        Returns:
            float: Total reserved for account in USD
        """
        with self._lock:
            return sum(
                r.reserved_amount
                for r in self._reservations.values()
                if r.account_id == account_id
            )
    
    def get_free_capital(
        self,
        total_balance: float,
        account_id: Optional[str] = None
    ) -> float:
        """
        Calculate free (unreserved) capital.
        
        Args:
            total_balance: Total account balance in USD
            account_id: Optional account ID to filter by
        
        Returns:
            float: Free capital in USD
        """
        if account_id:
            reserved = self.get_reserved_by_account(account_id)
        else:
            reserved = self.get_total_reserved()
        
        free = total_balance - reserved
        return max(0, free)  # Never negative
    
    def can_open_position(
        self,
        total_balance: float,
        new_position_size: float,
        account_id: Optional[str] = None
    ) -> Tuple[bool, str, Dict]:
        """
        Check if new position can be opened while maintaining safety buffer.
        
        Args:
            total_balance: Total account balance in USD
            new_position_size: Size of proposed new position in USD
            account_id: Optional account ID to filter by
        
        Returns:
            Tuple of (can_open, message, details)
        """
        # Calculate free capital
        free_capital = self.get_free_capital(total_balance, account_id)
        
        # Calculate what free capital would be after opening position
        free_capital_after = free_capital - new_position_size
        
        # Calculate required safety buffer
        safety_buffer_required = total_balance * self.safety_buffer_pct
        
        # Ensure minimum free capital
        effective_min_free = max(
            safety_buffer_required,
            self.min_free_capital_usd
        )
        
        # Check if we'd maintain sufficient free capital
        can_open = free_capital_after >= effective_min_free
        
        details = {
            'total_balance': total_balance,
            'current_free_capital': free_capital,
            'new_position_size': new_position_size,
            'free_capital_after': free_capital_after,
            'safety_buffer_required': safety_buffer_required,
            'min_free_capital': self.min_free_capital_usd,
            'effective_min_free': effective_min_free,
            'total_reserved': self.get_total_reserved(),
            'open_positions': len(self._reservations)
        }
        
        if can_open:
            message = (
                f"✅ Can open position: "
                f"${free_capital_after:.2f} free capital remaining "
                f"(min required: ${effective_min_free:.2f})"
            )
            logger.debug(message)
        else:
            deficit = effective_min_free - free_capital_after
            message = (
                f"❌ Cannot open position: "
                f"Would leave ${free_capital_after:.2f} free capital, "
                f"need ${effective_min_free:.2f} (deficit: ${deficit:.2f})"
            )
            logger.warning(message)
        
        return can_open, message, details
    
    def get_max_position_size(
        self,
        total_balance: float,
        account_id: Optional[str] = None
    ) -> float:
        """
        Calculate maximum position size that can be opened.
        
        Args:
            total_balance: Total account balance in USD
            account_id: Optional account ID to filter by
        
        Returns:
            float: Maximum position size in USD
        """
        # Calculate free capital
        free_capital = self.get_free_capital(total_balance, account_id)
        
        # Calculate required safety buffer
        safety_buffer_required = total_balance * self.safety_buffer_pct
        
        # Ensure minimum free capital
        effective_min_free = max(
            safety_buffer_required,
            self.min_free_capital_usd
        )
        
        # Max position = free capital - safety buffer
        max_position = free_capital - effective_min_free
        
        return max(0, max_position)  # Never negative
    
    def get_reservations(
        self,
        account_id: Optional[str] = None
    ) -> List[PositionReservation]:
        """
        Get list of current reservations.
        
        Args:
            account_id: Optional account ID to filter by
        
        Returns:
            List of PositionReservation objects
        """
        with self._lock:
            if account_id:
                return [
                    r for r in self._reservations.values()
                    if r.account_id == account_id
                ]
            else:
                return list(self._reservations.values())
    
    def get_reservation_summary(self) -> Dict:
        """
        Get summary of capital reservations.
        
        Returns:
            dict: Summary statistics
        """
        with self._lock:
            reservations = list(self._reservations.values())
            
            if not reservations:
                return {
                    'total_reserved': 0.0,
                    'open_positions': 0,
                    'accounts': 0,
                    'symbols': 0
                }
            
            return {
                'total_reserved': sum(r.reserved_amount for r in reservations),
                'open_positions': len(reservations),
                'accounts': len(set(r.account_id for r in reservations)),
                'symbols': len(set(r.symbol for r in reservations)),
                'positions_by_account': {
                    acc_id: len([r for r in reservations if r.account_id == acc_id])
                    for acc_id in set(r.account_id for r in reservations)
                },
                'reserved_by_account': {
                    acc_id: sum(
                        r.reserved_amount for r in reservations
                        if r.account_id == acc_id
                    )
                    for acc_id in set(r.account_id for r in reservations)
                }
            }


# Global singleton instance
_manager: Optional[CapitalReservationManager] = None
_lock = threading.Lock()


def get_capital_reservation_manager(
    safety_buffer_pct: float = 0.20,
    min_free_capital_usd: float = 5.0
) -> CapitalReservationManager:
    """
    Get or create the global capital reservation manager.
    
    Args:
        safety_buffer_pct: Safety buffer percentage (only used on first call)
        min_free_capital_usd: Minimum free capital (only used on first call)
    
    Returns:
        CapitalReservationManager: Global instance
    """
    global _manager
    
    with _lock:
        if _manager is None:
            _manager = CapitalReservationManager(
                safety_buffer_pct=safety_buffer_pct,
                min_free_capital_usd=min_free_capital_usd
            )
        return _manager


# Convenience functions
def reserve_capital(
    position_id: str,
    amount: float,
    symbol: str,
    account_id: str = "default",
    broker: str = "unknown"
) -> bool:
    """Reserve capital for a position"""
    manager = get_capital_reservation_manager()
    return manager.reserve_capital(position_id, amount, symbol, account_id, broker)


def release_capital(position_id: str) -> Optional[float]:
    """Release capital reservation"""
    manager = get_capital_reservation_manager()
    return manager.release_capital(position_id)


def can_open_position(
    total_balance: float,
    new_position_size: float,
    account_id: Optional[str] = None
) -> Tuple[bool, str, Dict]:
    """Check if new position can be opened"""
    manager = get_capital_reservation_manager()
    return manager.can_open_position(total_balance, new_position_size, account_id)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Capital Reservation Manager Test ===\n")
    
    # Initialize manager
    manager = get_capital_reservation_manager(
        safety_buffer_pct=0.20,  # 20% safety buffer
        min_free_capital_usd=5.0
    )
    
    # Simulate account with $100 balance
    balance = 100.0
    print(f"Account Balance: ${balance:.2f}")
    print(f"Safety Buffer: {manager.safety_buffer_pct * 100:.0f}%")
    print()
    
    # Try to open first position
    print("--- Opening Position 1 ---")
    size1 = 30.0
    can_open, msg, details = manager.can_open_position(balance, size1)
    print(msg)
    print(f"Details: {details}")
    
    if can_open:
        manager.reserve_capital("pos1", size1, "BTC-USD")
    print()
    
    # Try to open second position
    print("--- Opening Position 2 ---")
    size2 = 40.0
    can_open, msg, details = manager.can_open_position(balance, size2)
    print(msg)
    print(f"Details: {details}")
    
    if can_open:
        manager.reserve_capital("pos2", size2, "ETH-USD")
    print()
    
    # Try to open third position (should fail)
    print("--- Opening Position 3 ---")
    size3 = 20.0
    can_open, msg, details = manager.can_open_position(balance, size3)
    print(msg)
    print(f"Details: {details}")
    print()
    
    # Show summary
    print("--- Reservation Summary ---")
    summary = manager.get_reservation_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print()
    
    # Close position 1
    print("--- Closing Position 1 ---")
    released = manager.release_capital("pos1")
    print(f"Released: ${released:.2f}")
    print()
    
    # Now try position 3 again
    print("--- Retry Opening Position 3 ---")
    can_open, msg, details = manager.can_open_position(balance, size3)
    print(msg)
    
    print("\n=== Test Complete ===\n")
