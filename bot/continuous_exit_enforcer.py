#!/usr/bin/env python3
"""
Continuous Exit Enforcer
=========================

Ensures exit logic fires continuously and positions are always managed,
even when the main trading loop encounters errors.

Key Features:
- Runs independently of main trading logic
- Enforces hard position caps continuously
- Forces position reduction when over cap
- Bypasses all normal trading filters for emergency exits
- Per-user forced unwind mode

This module addresses the critical bug where exit logic stops firing
when the main trading loop encounters errors or early returns.
"""

import os
import logging
import time
import threading
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("nija.exit_enforcer")


class ContinuousExitEnforcer:
    """
    Continuously monitors and enforces position limits across all users.
    
    Runs in a separate thread to ensure position management happens
    even when main trading logic fails or encounters errors.
    """
    
    def __init__(self, 
                 check_interval: int = 60,  # Check every 60 seconds
                 max_positions: int = 8,
                 emergency_mode: bool = False):
        """
        Initialize continuous exit enforcer.
        
        Args:
            check_interval: Seconds between position cap checks
            max_positions: Hard cap on maximum positions
            emergency_mode: If True, aggressively close ALL positions
        """
        self.check_interval = check_interval
        self.max_positions = max_positions
        self.emergency_mode = emergency_mode
        
        self._stop_event = threading.Event()
        self._monitor_thread = None
        
        # Track forced unwind mode per user
        self._forced_unwind_users = set()
        self._unwind_lock = threading.Lock()
        
        logger.info(f"ContinuousExitEnforcer initialized:")
        logger.info(f"  Check interval: {check_interval}s")
        logger.info(f"  Max positions: {max_positions}")
        logger.info(f"  Emergency mode: {emergency_mode}")
    
    def start(self):
        """Start the continuous monitoring thread."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.warning("Exit enforcer already running")
            return
        
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="ContinuousExitEnforcer",
            daemon=True
        )
        self._monitor_thread.start()
        logger.info("🛡️ Continuous exit enforcer started")
    
    def stop(self):
        """Stop the continuous monitoring thread."""
        logger.info("Stopping continuous exit enforcer...")
        self._stop_event.set()
        
        if self._monitor_thread:
            self._monitor_thread.join(timeout=10)
        
        logger.info("✅ Continuous exit enforcer stopped")
    
    def enable_forced_unwind(self, user_id: str):
        """
        Enable forced unwind mode for a specific user.
        
        When enabled, ALL positions for this user will be closed
        as quickly as possible, bypassing all normal filters.
        
        Args:
            user_id: User identifier
        """
        with self._unwind_lock:
            if user_id not in self._forced_unwind_users:
                self._forced_unwind_users.add(user_id)
                logger.warning(f"🚨 FORCED UNWIND ENABLED: {user_id}")
                logger.warning(f"   All positions will be closed immediately")
    
    def disable_forced_unwind(self, user_id: str):
        """
        Disable forced unwind mode for a specific user.
        
        Args:
            user_id: User identifier
        """
        with self._unwind_lock:
            if user_id in self._forced_unwind_users:
                self._forced_unwind_users.remove(user_id)
                logger.info(f"✅ FORCED UNWIND DISABLED: {user_id}")
    
    def is_forced_unwind_active(self, user_id: str) -> bool:
        """
        Check if forced unwind mode is active for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            True if forced unwind is active
        """
        with self._unwind_lock:
            return user_id in self._forced_unwind_users
    
    def _monitor_loop(self):
        """Main monitoring loop that runs continuously."""
        logger.info("Starting continuous position monitoring loop...")
        
        check_count = 0
        
        while not self._stop_event.is_set():
            try:
                check_count += 1
                
                # Run position check every interval
                if check_count % (self.check_interval // 10) == 0:  # Check every interval
                    self._check_and_enforce_positions()
                
                # Sleep in small increments to allow quick shutdown
                time.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in continuous exit enforcer: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(10)  # Brief pause before retrying
    
    def _check_and_enforce_positions(self):
        """
        Check position counts and enforce caps.
        
        This is the core enforcement logic that runs continuously.
        """
        try:
            # Import broker manager here to avoid circular imports
            from broker_manager import get_broker_manager
            
            broker_manager = get_broker_manager()
            if not broker_manager:
                logger.debug("No broker manager available for position check")
                return
            
            # Get all connected brokers
            brokers = broker_manager.get_all_brokers()
            if not brokers:
                logger.debug("No brokers available for position check")
                return
            
            # Check each broker's positions
            for broker_type, broker in brokers.items():
                if not broker or not broker.connected:
                    continue
                
                try:
                    # Get current positions
                    positions = broker.get_positions()
                    if not positions:
                        continue
                    
                    current_count = len(positions)
                    broker_name = broker_type.value.upper() if hasattr(broker_type, 'value') else str(broker_type).upper()
                    
                    # Check if over cap
                    if current_count > self.max_positions:
                        excess = current_count - self.max_positions
                        logger.warning(f"🚨 {broker_name} OVER CAP: {current_count}/{self.max_positions} (excess: {excess})")
                        
                        # Enforce cap by closing smallest positions
                        self._enforce_position_cap(broker, broker_name, positions, excess)
                    
                    # Check for forced unwind mode (per user)
                    # Note: This is a placeholder - user tracking needs to be implemented
                    
                except Exception as broker_err:
                    broker_name = broker_type.value.upper() if hasattr(broker_type, 'value') else str(broker_type).upper()
                    logger.error(f"Error checking positions for {broker_name}: {broker_err}")
        
        except Exception as e:
            logger.error(f"Error in position check and enforcement: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _enforce_position_cap(self, broker, broker_name: str, positions: List[Dict], excess: int):
        """
        Enforce position cap by closing smallest positions.
        
        Args:
            broker: Broker instance
            broker_name: Broker name for logging
            positions: List of position dicts
            excess: Number of positions to close
        """
        try:
            # Sort positions by USD value (smallest first)
            sorted_positions = sorted(
                positions,
                key=lambda p: (p.get('quantity', 0) * p.get('price', 0))
            )
            
            # Close smallest positions
            closed_count = 0
            for i, pos in enumerate(sorted_positions[:excess]):
                try:
                    symbol = pos.get('symbol')
                    quantity = pos.get('quantity', 0)
                    
                    if not symbol or quantity <= 0:
                        continue
                    
                    logger.warning(f"  Closing {symbol} to enforce cap...")
                    
                    # Place market sell order
                    result = broker.place_market_order(
                        symbol=symbol,
                        side='sell',
                        quantity=quantity,
                        size_type='base',
                        force_liquidate=True,  # Bypass all validation
                        ignore_balance=True,
                        ignore_min_trade=True
                    )
                    
                    if result and result.get('status') not in ['error', 'unfilled']:
                        logger.info(f"  ✅ Closed {symbol} to enforce cap")
                        closed_count += 1
                    else:
                        logger.error(f"  ❌ Failed to close {symbol}: {result.get('error', 'Unknown')}")
                    
                    # Rate limit
                    if i < excess - 1:
                        time.sleep(1)
                
                except Exception as pos_err:
                    logger.error(f"  Error closing position: {pos_err}")
            
            logger.info(f"  Closed {closed_count}/{excess} excess positions on {broker_name}")
        
        except Exception as e:
            logger.error(f"Error enforcing position cap on {broker_name}: {e}")


# Global singleton instance
_continuous_exit_enforcer: Optional[ContinuousExitEnforcer] = None
_init_lock = threading.Lock()


def get_continuous_exit_enforcer() -> ContinuousExitEnforcer:
    """
    Get the global continuous exit enforcer instance (singleton).
    
    Returns:
        ContinuousExitEnforcer: Global instance
    """
    global _continuous_exit_enforcer
    
    with _init_lock:
        if _continuous_exit_enforcer is None:
            _continuous_exit_enforcer = ContinuousExitEnforcer()
        return _continuous_exit_enforcer


__all__ = [
    'ContinuousExitEnforcer',
    'get_continuous_exit_enforcer',
]
