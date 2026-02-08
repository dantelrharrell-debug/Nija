"""
NIJA Exchange ↔ Internal Reconciliation Watchdog
=================================================

Prevents "ghost risk" by comparing internal position tracker vs exchange balances.

Key Features:
- Detects orphaned assets (exchange has, we don't track)
- Identifies airdrops and forks
- Flags partial fills not tracked internally
- Auto-adopt or liquidate orphaned positions (configurable)
- Periodic reconciliation checks

Author: NIJA Trading Systems
Version: 1.0
Date: February 8, 2026
"""

import logging
import threading
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger("nija.reconciliation")


class DiscrepancyType(Enum):
    """Types of reconciliation discrepancies"""
    ORPHANED_ASSET = "ORPHANED_ASSET"           # Exchange has, we don't track
    PHANTOM_POSITION = "PHANTOM_POSITION"       # We track, exchange doesn't have
    SIZE_MISMATCH = "SIZE_MISMATCH"             # Sizes don't match
    AIRDROP_DETECTED = "AIRDROP_DETECTED"       # Unexpected asset appearance
    PARTIAL_FILL_UNTRACKED = "PARTIAL_FILL"     # Partial fill not in tracker


class ReconciliationAction(Enum):
    """Actions to take on discrepancies"""
    ADOPT = "ADOPT"                 # Adopt orphaned asset into tracking
    LIQUIDATE = "LIQUIDATE"         # Liquidate orphaned asset
    ADJUST = "ADJUST"               # Adjust tracked size to match reality
    ALERT_ONLY = "ALERT_ONLY"       # Flag but don't act


@dataclass
class Discrepancy:
    """Represents a reconciliation discrepancy"""
    discrepancy_type: str
    symbol: str
    exchange_balance: float
    internal_balance: float
    difference: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    account_id: str = "default"
    broker: str = "unknown"
    recommended_action: str = "ALERT_ONLY"
    details: Dict = field(default_factory=dict)
    
    def __repr__(self):
        return (
            f"Discrepancy({self.discrepancy_type}, {self.symbol}, "
            f"exchange={self.exchange_balance}, internal={self.internal_balance})"
        )


class ReconciliationWatchdog:
    """
    Monitors and reconciles exchange balances vs internal tracking.
    
    Prevents:
    - Ghost risk from untracked positions
    - Silent position accumulation
    - Missed airdrops/forks
    - Tracking drift
    """
    
    def __init__(
        self,
        dust_threshold_usd: float = 1.0,
        auto_adopt_threshold_usd: float = 10.0,
        auto_liquidate_threshold_usd: float = 5.0,
        reconciliation_interval_minutes: int = 60,
        enable_auto_actions: bool = False
    ):
        """
        Initialize reconciliation watchdog.
        
        Args:
            dust_threshold_usd: Ignore discrepancies below this value
            auto_adopt_threshold_usd: Auto-adopt orphans above this value
            auto_liquidate_threshold_usd: Auto-liquidate orphans below this value
            reconciliation_interval_minutes: How often to reconcile
            enable_auto_actions: If True, auto-adopt/liquidate. If False, alert only.
        """
        self.dust_threshold_usd = dust_threshold_usd
        self.auto_adopt_threshold_usd = auto_adopt_threshold_usd
        self.auto_liquidate_threshold_usd = auto_liquidate_threshold_usd
        self.reconciliation_interval = timedelta(minutes=reconciliation_interval_minutes)
        self.enable_auto_actions = enable_auto_actions
        
        # Tracking
        self._discrepancies: List[Discrepancy] = []
        self._last_reconciliation: Optional[datetime] = None
        self._lock = threading.Lock()
        
        # Known airdrops/forks to watch for
        self._known_airdrops = {
            'BCH', 'BSV', 'BTG',  # Bitcoin forks
            'ETC',                 # Ethereum Classic
            'LUNA2',              # Luna fork
        }
        
        logger.info(
            f"✅ Reconciliation Watchdog initialized: "
            f"dust_threshold=${self.dust_threshold_usd:.2f}, "
            f"auto_actions={self.enable_auto_actions}"
        )
    
    def should_reconcile(self) -> bool:
        """Check if it's time for reconciliation"""
        if self._last_reconciliation is None:
            return True
        
        elapsed = datetime.now() - self._last_reconciliation
        return elapsed >= self.reconciliation_interval
    
    def reconcile_balances(
        self,
        exchange_balances: Dict[str, float],
        internal_positions: Dict[str, float],
        prices: Dict[str, float],
        account_id: str = "default",
        broker: str = "unknown"
    ) -> List[Discrepancy]:
        """
        Reconcile exchange balances vs internal tracking.
        
        Args:
            exchange_balances: {symbol: balance} from exchange API
            internal_positions: {symbol: balance} from internal tracker
            prices: {symbol: price_usd} for valuation
            account_id: Account identifier
            broker: Broker name
        
        Returns:
            List of discovered discrepancies
        """
        with self._lock:
            discrepancies = []
            
            # Get all symbols from both sources
            all_symbols = set(exchange_balances.keys()) | set(internal_positions.keys())
            
            for symbol in all_symbols:
                exchange_bal = exchange_balances.get(symbol, 0.0)
                internal_bal = internal_positions.get(symbol, 0.0)
                
                # Skip if both are zero or effectively zero
                if exchange_bal == 0 and internal_bal == 0:
                    continue
                
                # Calculate difference
                diff = exchange_bal - internal_bal
                
                # Get USD value
                price = prices.get(symbol, 0.0)
                diff_usd = abs(diff) * price
                exchange_usd = exchange_bal * price
                internal_usd = internal_bal * price
                
                # Skip dust-level discrepancies
                if diff_usd < self.dust_threshold_usd:
                    continue
                
                # Classify discrepancy
                discrepancy_type, action = self._classify_discrepancy(
                    symbol, exchange_bal, internal_bal, diff_usd
                )
                
                # Create discrepancy record
                discrepancy = Discrepancy(
                    discrepancy_type=discrepancy_type.value,
                    symbol=symbol,
                    exchange_balance=exchange_bal,
                    internal_balance=internal_bal,
                    difference=diff,
                    account_id=account_id,
                    broker=broker,
                    recommended_action=action.value,
                    details={
                        'price': price,
                        'exchange_usd': exchange_usd,
                        'internal_usd': internal_usd,
                        'diff_usd': diff_usd
                    }
                )
                
                discrepancies.append(discrepancy)
                
                # Log the discrepancy
                logger.warning(
                    f"🚨 {discrepancy_type.value}: {symbol} - "
                    f"Exchange: {exchange_bal:.8f}, "
                    f"Internal: {internal_bal:.8f}, "
                    f"Diff: ${diff_usd:.2f} USD - "
                    f"Action: {action.value}"
                )
            
            # Store discrepancies
            self._discrepancies.extend(discrepancies)
            self._last_reconciliation = datetime.now()
            
            # Execute auto-actions if enabled
            if self.enable_auto_actions and discrepancies:
                self._execute_auto_actions(discrepancies)
            
            return discrepancies
    
    def _classify_discrepancy(
        self,
        symbol: str,
        exchange_bal: float,
        internal_bal: float,
        diff_usd: float
    ) -> Tuple[DiscrepancyType, ReconciliationAction]:
        """
        Classify discrepancy type and recommend action.
        
        Args:
            symbol: Trading symbol
            exchange_bal: Balance on exchange
            internal_bal: Balance in internal tracker
            diff_usd: Difference in USD
        
        Returns:
            Tuple of (discrepancy_type, recommended_action)
        """
        # Case 1: Exchange has asset, we don't track it
        if exchange_bal > 0 and internal_bal == 0:
            # Check if it's a known airdrop
            if symbol in self._known_airdrops:
                return DiscrepancyType.AIRDROP_DETECTED, ReconciliationAction.ADOPT
            
            # Decide based on value
            if diff_usd >= self.auto_adopt_threshold_usd:
                return DiscrepancyType.ORPHANED_ASSET, ReconciliationAction.ADOPT
            elif diff_usd >= self.auto_liquidate_threshold_usd:
                return DiscrepancyType.ORPHANED_ASSET, ReconciliationAction.LIQUIDATE
            else:
                return DiscrepancyType.ORPHANED_ASSET, ReconciliationAction.ALERT_ONLY
        
        # Case 2: We track asset, exchange doesn't have it
        elif internal_bal > 0 and exchange_bal == 0:
            return DiscrepancyType.PHANTOM_POSITION, ReconciliationAction.ADJUST
        
        # Case 3: Both have it but sizes don't match
        else:
            # Likely partial fill
            if abs(exchange_bal - internal_bal) / max(exchange_bal, internal_bal) > 0.1:
                return DiscrepancyType.PARTIAL_FILL_UNTRACKED, ReconciliationAction.ADJUST
            else:
                return DiscrepancyType.SIZE_MISMATCH, ReconciliationAction.ADJUST
    
    def _execute_auto_actions(self, discrepancies: List[Discrepancy]):
        """
        Execute automatic actions on discrepancies.
        
        NOTE: This is a placeholder. Actual implementation should:
        1. Call broker API to liquidate
        2. Update internal position tracker
        3. Create audit log
        
        Args:
            discrepancies: List of discrepancies to act on
        """
        for discrepancy in discrepancies:
            action = ReconciliationAction(discrepancy.recommended_action)
            
            if action == ReconciliationAction.ALERT_ONLY:
                continue
            
            logger.info(
                f"🤖 AUTO-ACTION: {action.value} for {discrepancy.symbol} "
                f"(${discrepancy.details.get('diff_usd', 0):.2f})"
            )
            
            # TODO: Implement actual actions
            # - ADOPT: Add to internal tracker
            # - LIQUIDATE: Place sell order on exchange
            # - ADJUST: Update internal tracker to match exchange
    
    def get_discrepancies(
        self,
        hours: int = 24,
        discrepancy_type: Optional[str] = None
    ) -> List[Discrepancy]:
        """
        Get recent discrepancies.
        
        Args:
            hours: Look back this many hours
            discrepancy_type: Filter by type (optional)
        
        Returns:
            List of discrepancies
        """
        with self._lock:
            cutoff = datetime.now() - timedelta(hours=hours)
            
            filtered = [
                d for d in self._discrepancies
                if datetime.fromisoformat(d.timestamp) >= cutoff
            ]
            
            if discrepancy_type:
                filtered = [
                    d for d in filtered
                    if d.discrepancy_type == discrepancy_type
                ]
            
            return filtered
    
    def get_unresolved_discrepancies(self) -> List[Discrepancy]:
        """
        Get discrepancies that still need attention.
        
        Returns:
            List of unresolved discrepancies
        """
        # For now, return all recent discrepancies
        # In production, would track resolution status
        return self.get_discrepancies(hours=24)
    
    def get_orphaned_assets(self) -> List[Discrepancy]:
        """Get list of orphaned assets on exchange"""
        return [
            d for d in self.get_unresolved_discrepancies()
            if d.discrepancy_type == DiscrepancyType.ORPHANED_ASSET.value
        ]
    
    def get_phantom_positions(self) -> List[Discrepancy]:
        """Get list of phantom positions (tracked but not on exchange)"""
        return [
            d for d in self.get_unresolved_discrepancies()
            if d.discrepancy_type == DiscrepancyType.PHANTOM_POSITION.value
        ]
    
    def get_reconciliation_summary(self) -> Dict:
        """
        Get summary of reconciliation status.
        
        Returns:
            dict: Summary statistics
        """
        with self._lock:
            recent = self.get_discrepancies(hours=24)
            
            summary = {
                'last_reconciliation': (
                    self._last_reconciliation.isoformat()
                    if self._last_reconciliation else None
                ),
                'total_discrepancies_24h': len(recent),
                'unresolved_discrepancies': len(self.get_unresolved_discrepancies()),
                'orphaned_assets': len(self.get_orphaned_assets()),
                'phantom_positions': len(self.get_phantom_positions()),
                'by_type': {},
                'total_value_usd': 0.0
            }
            
            # Count by type
            for dtype in DiscrepancyType:
                count = len([d for d in recent if d.discrepancy_type == dtype.value])
                if count > 0:
                    summary['by_type'][dtype.value] = count
            
            # Total value
            summary['total_value_usd'] = sum(
                d.details.get('diff_usd', 0) for d in recent
            )
            
            return summary
    
    def register_airdrop(self, symbol: str):
        """Register a known airdrop symbol to watch for"""
        self._known_airdrops.add(symbol)
        logger.info(f"📋 Registered airdrop watch: {symbol}")
    
    def clear_old_discrepancies(self, days: int = 7):
        """Clear discrepancies older than specified days"""
        with self._lock:
            cutoff = datetime.now() - timedelta(days=days)
            original_count = len(self._discrepancies)
            
            self._discrepancies = [
                d for d in self._discrepancies
                if datetime.fromisoformat(d.timestamp) >= cutoff
            ]
            
            removed = original_count - len(self._discrepancies)
            if removed > 0:
                logger.info(f"🗑️ Cleared {removed} old discrepancies")


# Global singleton instance
_watchdog: Optional[ReconciliationWatchdog] = None
_lock = threading.Lock()


def get_reconciliation_watchdog(
    enable_auto_actions: bool = False
) -> ReconciliationWatchdog:
    """
    Get or create the global reconciliation watchdog.
    
    Args:
        enable_auto_actions: Enable auto actions (only used on first call)
    
    Returns:
        ReconciliationWatchdog: Global instance
    """
    global _watchdog
    
    with _lock:
        if _watchdog is None:
            _watchdog = ReconciliationWatchdog(
                enable_auto_actions=enable_auto_actions
            )
        return _watchdog


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Reconciliation Watchdog Test ===\n")
    
    # Initialize watchdog
    watchdog = get_reconciliation_watchdog(enable_auto_actions=False)
    
    # Simulate exchange balances
    exchange_balances = {
        'BTC': 0.01,
        'ETH': 0.5,
        'DOGE': 100.0,  # Orphaned asset
        'BCH': 0.1,     # Airdrop
    }
    
    # Simulate internal tracking
    internal_positions = {
        'BTC': 0.01,
        'ETH': 0.45,    # Size mismatch
        'SOL': 2.0,     # Phantom position
    }
    
    # Prices
    prices = {
        'BTC': 50000.0,
        'ETH': 3000.0,
        'DOGE': 0.15,
        'BCH': 300.0,
        'SOL': 100.0,
    }
    
    # Reconcile
    print("--- Running Reconciliation ---")
    discrepancies = watchdog.reconcile_balances(
        exchange_balances,
        internal_positions,
        prices,
        broker="test_exchange"
    )
    
    print(f"\nFound {len(discrepancies)} discrepancies:\n")
    for d in discrepancies:
        print(f"  {d}")
    
    # Get summary
    print("\n--- Reconciliation Summary ---")
    summary = watchdog.get_reconciliation_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    print("\n=== Test Complete ===\n")
