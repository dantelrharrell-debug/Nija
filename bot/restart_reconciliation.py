"""
NIJA Restart Reconciliation - Restart Integrity Check

CRITICAL SAFETY MODULE - Ensures safe restart after crashes or shutdowns.

On restart, this module:
    ✅ Detects open positions on exchange
    ✅ Syncs balances with exchange
    ✅ Verifies last known state
    ✅ Prevents duplicate orders
    ✅ Reconciles position tracking
    ✅ Detects orphaned orders

This prevents:
    ❌ Duplicate orders after restart
    ❌ Position tracking drift
    ❌ Lost position awareness
    ❌ Balance mismatches

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger("nija.restart_reconciliation")


@dataclass
class PositionSnapshot:
    """Snapshot of a trading position"""
    symbol: str
    side: str  # 'long' or 'short'
    quantity: float
    entry_price: float
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    order_id: Optional[str] = None
    timestamp: str = ""
    

@dataclass
class BalanceSnapshot:
    """Snapshot of account balance"""
    total_balance: float
    available_balance: float
    reserved_balance: float
    currency: str
    timestamp: str
    

@dataclass
class SystemState:
    """Complete system state snapshot"""
    timestamp: str
    trading_state: str
    positions: List[PositionSnapshot]
    balances: Dict[str, BalanceSnapshot]
    pending_orders: List[Dict[str, Any]]
    last_trade_id: Optional[str] = None
    last_signal_id: Optional[str] = None
    

class RestartReconciliationManager:
    """
    Manages restart integrity and state reconciliation.
    
    CRITICAL: Prevents duplicate orders and lost positions on restart.
    """
    
    STATE_FILE = ".nija_system_state.json"
    
    def __init__(self, state_file: Optional[str] = None):
        """
        Initialize restart reconciliation manager.
        
        Args:
            state_file: Path to state file (default: .nija_system_state.json)
        """
        self._state_file = state_file or os.path.join(
            os.path.dirname(__file__),
            "..",
            self.STATE_FILE
        )
        
        self._last_known_state: Optional[SystemState] = None
        self._restart_detected = False
        self._reconciliation_complete = False
        
        # Check if this is a restart
        self._check_for_restart()
        
        logger.info("🔄 Restart Reconciliation Manager initialized")
        
    def _check_for_restart(self):
        """Check if this is a restart (state file exists)"""
        if os.path.exists(self._state_file):
            self._restart_detected = True
            logger.warning("⚠️  RESTART DETECTED - Loading previous state")
            self._load_last_state()
        else:
            logger.info("✅ Fresh start - no previous state found")
            
    def _load_last_state(self):
        """Load last known system state"""
        try:
            with open(self._state_file, 'r') as f:
                data = json.load(f)
                
                # Reconstruct positions
                positions = [
                    PositionSnapshot(**pos) for pos in data.get('positions', [])
                ]
                
                # Reconstruct balances
                balances = {
                    currency: BalanceSnapshot(**bal)
                    for currency, bal in data.get('balances', {}).items()
                }
                
                # Reconstruct state
                self._last_known_state = SystemState(
                    timestamp=data.get('timestamp', ''),
                    trading_state=data.get('trading_state', 'OFF'),
                    positions=positions,
                    balances=balances,
                    pending_orders=data.get('pending_orders', []),
                    last_trade_id=data.get('last_trade_id'),
                    last_signal_id=data.get('last_signal_id')
                )
                
                logger.info(f"📂 Loaded previous state from {self._last_known_state.timestamp}")
                logger.info(f"   Trading state: {self._last_known_state.trading_state}")
                logger.info(f"   Open positions: {len(self._last_known_state.positions)}")
                logger.info(f"   Pending orders: {len(self._last_known_state.pending_orders)}")
                
        except Exception as e:
            logger.error(f"❌ Error loading previous state: {e}")
            self._last_known_state = None
            
    def save_current_state(
        self,
        trading_state: str,
        positions: List[PositionSnapshot],
        balances: Dict[str, BalanceSnapshot],
        pending_orders: Optional[List[Dict[str, Any]]] = None,
        last_trade_id: Optional[str] = None,
        last_signal_id: Optional[str] = None
    ):
        """
        Save current system state for restart recovery.
        
        Args:
            trading_state: Current trading state
            positions: List of open positions
            balances: Account balances
            pending_orders: List of pending orders
            last_trade_id: ID of last executed trade
            last_signal_id: ID of last processed signal
        """
        try:
            state = SystemState(
                timestamp=datetime.utcnow().isoformat(),
                trading_state=trading_state,
                positions=positions,
                balances=balances,
                pending_orders=pending_orders or [],
                last_trade_id=last_trade_id,
                last_signal_id=last_signal_id
            )
            
            # Convert to dict
            state_dict = {
                'timestamp': state.timestamp,
                'trading_state': state.trading_state,
                'positions': [asdict(pos) for pos in state.positions],
                'balances': {
                    currency: asdict(bal) for currency, bal in state.balances.items()
                },
                'pending_orders': state.pending_orders,
                'last_trade_id': state.last_trade_id,
                'last_signal_id': state.last_signal_id
            }
            
            # Write atomically
            temp_file = f"{self._state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(state_dict, f, indent=2)
            os.replace(temp_file, self._state_file)
            
            logger.debug(f"💾 System state saved: {len(positions)} positions, {len(pending_orders or [])} orders")
            
        except Exception as e:
            logger.error(f"❌ Error saving system state: {e}")
            
    def reconcile_with_exchange(
        self,
        exchange_positions: List[PositionSnapshot],
        exchange_balances: Dict[str, BalanceSnapshot],
        exchange_open_orders: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Reconcile last known state with actual exchange state.
        
        Args:
            exchange_positions: Actual positions from exchange
            exchange_balances: Actual balances from exchange
            exchange_open_orders: Actual open orders from exchange
            
        Returns:
            Reconciliation report
        """
        logger.info("=" * 80)
        logger.info("🔄 STARTING RESTART RECONCILIATION")
        logger.info("=" * 80)
        
        report = {
            'timestamp': datetime.utcnow().isoformat(),
            'restart_detected': self._restart_detected,
            'had_previous_state': self._last_known_state is not None,
            'discrepancies': [],
            'actions_taken': [],
            'warnings': [],
            'status': 'UNKNOWN'
        }
        
        if not self._restart_detected or not self._last_known_state:
            logger.info("✅ No restart or no previous state - clean start")
            report['status'] = 'CLEAN_START'
            self._reconciliation_complete = True
            return report
            
        # Compare positions
        logger.info("\n--- Reconciling Positions ---")
        position_discrepancies = self._compare_positions(
            self._last_known_state.positions,
            exchange_positions
        )
        report['discrepancies'].extend(position_discrepancies)
        
        # Compare balances
        logger.info("\n--- Reconciling Balances ---")
        balance_discrepancies = self._compare_balances(
            self._last_known_state.balances,
            exchange_balances
        )
        report['discrepancies'].extend(balance_discrepancies)
        
        # Check for orphaned orders
        logger.info("\n--- Checking for Orphaned Orders ---")
        orphaned_orders = self._find_orphaned_orders(
            self._last_known_state.pending_orders,
            exchange_open_orders
        )
        if orphaned_orders:
            report['warnings'].append(f"Found {len(orphaned_orders)} orphaned orders")
            
        # Determine status
        if not report['discrepancies']:
            logger.info("✅ RECONCILIATION COMPLETE - No discrepancies found")
            report['status'] = 'CLEAN'
        else:
            logger.warning("⚠️  RECONCILIATION COMPLETE - Discrepancies found")
            report['status'] = 'DISCREPANCIES_FOUND'
            
        logger.info("=" * 80)
        
        self._reconciliation_complete = True
        return report
        
    def _compare_positions(
        self,
        last_known: List[PositionSnapshot],
        exchange: List[PositionSnapshot]
    ) -> List[Dict[str, Any]]:
        """Compare last known positions with exchange positions"""
        discrepancies = []
        
        # Create lookup maps
        last_known_map = {pos.symbol: pos for pos in last_known}
        exchange_map = {pos.symbol: pos for pos in exchange}
        
        # Check for positions that should exist but don't
        for symbol, last_pos in last_known_map.items():
            if symbol not in exchange_map:
                discrepancy = {
                    'type': 'POSITION_MISSING',
                    'symbol': symbol,
                    'expected': asdict(last_pos),
                    'actual': None,
                    'severity': 'HIGH'
                }
                discrepancies.append(discrepancy)
                logger.error(f"❌ Position missing: {symbol}")
                logger.error(f"   Expected: {last_pos.quantity} @ {last_pos.entry_price}")
                
        # Check for unexpected positions
        for symbol, exchange_pos in exchange_map.items():
            if symbol not in last_known_map:
                discrepancy = {
                    'type': 'UNEXPECTED_POSITION',
                    'symbol': symbol,
                    'expected': None,
                    'actual': asdict(exchange_pos),
                    'severity': 'MEDIUM'
                }
                discrepancies.append(discrepancy)
                logger.warning(f"⚠️  Unexpected position: {symbol}")
                logger.warning(f"   Found: {exchange_pos.quantity} @ {exchange_pos.entry_price}")
                
        # Check for quantity mismatches
        for symbol in set(last_known_map.keys()) & set(exchange_map.keys()):
            last_pos = last_known_map[symbol]
            exchange_pos = exchange_map[symbol]
            
            if abs(last_pos.quantity - exchange_pos.quantity) > 0.0001:
                discrepancy = {
                    'type': 'QUANTITY_MISMATCH',
                    'symbol': symbol,
                    'expected_quantity': last_pos.quantity,
                    'actual_quantity': exchange_pos.quantity,
                    'severity': 'HIGH'
                }
                discrepancies.append(discrepancy)
                logger.error(f"❌ Quantity mismatch: {symbol}")
                logger.error(f"   Expected: {last_pos.quantity}")
                logger.error(f"   Actual: {exchange_pos.quantity}")
                
        return discrepancies
        
    def _compare_balances(
        self,
        last_known: Dict[str, BalanceSnapshot],
        exchange: Dict[str, BalanceSnapshot]
    ) -> List[Dict[str, Any]]:
        """Compare last known balances with exchange balances"""
        discrepancies = []
        
        for currency in set(last_known.keys()) | set(exchange.keys()):
            last_bal = last_known.get(currency)
            exchange_bal = exchange.get(currency)
            
            if not last_bal or not exchange_bal:
                continue  # Skip if currency not in both
                
            # Allow for small differences due to fees, funding, etc.
            tolerance = 0.01  # 1% tolerance
            diff_pct = abs(last_bal.total_balance - exchange_bal.total_balance) / last_bal.total_balance
            
            if diff_pct > tolerance:
                discrepancy = {
                    'type': 'BALANCE_MISMATCH',
                    'currency': currency,
                    'expected_balance': last_bal.total_balance,
                    'actual_balance': exchange_bal.total_balance,
                    'difference_pct': diff_pct * 100,
                    'severity': 'MEDIUM' if diff_pct < 0.05 else 'HIGH'
                }
                discrepancies.append(discrepancy)
                logger.warning(f"⚠️  Balance mismatch: {currency}")
                logger.warning(f"   Expected: {last_bal.total_balance}")
                logger.warning(f"   Actual: {exchange_bal.total_balance}")
                logger.warning(f"   Difference: {diff_pct*100:.2f}%")
                
        return discrepancies
        
    def _find_orphaned_orders(
        self,
        last_known_orders: List[Dict[str, Any]],
        exchange_orders: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Find orders that were pending but are no longer on exchange"""
        orphaned = []
        
        # Create set of exchange order IDs
        exchange_order_ids = {order.get('id') for order in exchange_orders if order.get('id')}
        
        for order in last_known_orders:
            order_id = order.get('id')
            if order_id and order_id not in exchange_order_ids:
                orphaned.append(order)
                logger.warning(f"⚠️  Orphaned order: {order_id}")
                logger.warning(f"   Order details: {order}")
                
        return orphaned
        
    def prevent_duplicate_order(self, signal_id: str) -> bool:
        """
        Check if a signal has already been processed.
        
        Args:
            signal_id: Unique signal identifier
            
        Returns:
            True if signal should be processed, False if it's a duplicate
        """
        if not self._last_known_state:
            return True  # No previous state, allow
            
        if signal_id == self._last_known_state.last_signal_id:
            logger.warning(f"⚠️  DUPLICATE SIGNAL DETECTED: {signal_id}")
            logger.warning("   This signal was already processed before restart")
            logger.warning("   Skipping to prevent duplicate order")
            return False
            
        return True
        
    def is_reconciliation_complete(self) -> bool:
        """Check if reconciliation is complete"""
        return self._reconciliation_complete
        
    def assert_reconciliation_complete(self):
        """Assert that reconciliation is complete before trading"""
        if not self._reconciliation_complete:
            raise RuntimeError(
                "Cannot start trading: Restart reconciliation not complete. "
                "System must verify positions and balances before trading."
            )
            
    def get_last_known_state(self) -> Optional[SystemState]:
        """Get last known system state"""
        return self._last_known_state
        
    def clear_state_file(self):
        """Clear state file (use with caution)"""
        try:
            if os.path.exists(self._state_file):
                os.remove(self._state_file)
                logger.info("🗑️  State file cleared")
        except Exception as e:
            logger.error(f"❌ Error clearing state file: {e}")


# Global singleton instance
_restart_reconciliation_manager: Optional[RestartReconciliationManager] = None


def get_restart_reconciliation_manager() -> RestartReconciliationManager:
    """Get the global restart reconciliation manager instance (singleton)"""
    global _restart_reconciliation_manager
    
    if _restart_reconciliation_manager is None:
        _restart_reconciliation_manager = RestartReconciliationManager()
        
    return _restart_reconciliation_manager


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Restart Reconciliation Manager Test ===\n")
    
    manager = get_restart_reconciliation_manager()
    
    # Simulate saving state
    print("--- Saving current state ---")
    positions = [
        PositionSnapshot(
            symbol="BTC-USD",
            side="long",
            quantity=0.5,
            entry_price=45000.0,
            timestamp=datetime.utcnow().isoformat()
        )
    ]
    
    balances = {
        'USD': BalanceSnapshot(
            total_balance=10000.0,
            available_balance=5000.0,
            reserved_balance=5000.0,
            currency='USD',
            timestamp=datetime.utcnow().isoformat()
        )
    }
    
    manager.save_current_state(
        trading_state='LIVE_ACTIVE',
        positions=positions,
        balances=balances,
        pending_orders=[],
        last_signal_id='signal_123'
    )
    
    print("\n--- Testing duplicate signal prevention ---")
    is_new = manager.prevent_duplicate_order('signal_123')
    print(f"Signal 'signal_123' is new: {is_new}")
    
    is_new = manager.prevent_duplicate_order('signal_456')
    print(f"Signal 'signal_456' is new: {is_new}")
    
    print("\n--- Simulating reconciliation ---")
    # Simulate exchange state (same as saved)
    report = manager.reconcile_with_exchange(
        exchange_positions=positions,
        exchange_balances=balances,
        exchange_open_orders=[]
    )
    
    print(f"\nReconciliation status: {report['status']}")
    print(f"Discrepancies found: {len(report['discrepancies'])}")
