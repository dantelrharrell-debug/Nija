"""
NIJA Profit Protection System - Layer 2 Enhancement
===================================================

Implements intelligent exit management to lock in profits before reversal.

Key Features:
1. Graduated profit extraction (take chips off the table)
2. Break-even barrier (move stop to protect capital)
3. Time-based exit trigger (cut slow bleeders)

Philosophy: Many trades go +0.5R then reverse to losers.
Solution: Lock profits early, protect break-even, exit stagnant trades.
"""

import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

logger = logging.getLogger("nija.profit_protection")


class ProfitProtectionSystem:
    """
    Manages positions to lock in profits and prevent reversals.
    
    Three protection layers:
    1. Partial exits at profit milestones
    2. Break-even stop movement
    3. Time-based stagnation exit
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize profit protection system.
        
        Args:
            config: Optional configuration
        """
        self.config = config or {}
        
        # Partial exit thresholds (profit_pct: exit_pct)
        # Default: Take 40% at +1R, 30% more at +2R
        self.exit_schedule = self.config.get('exit_schedule', {
            0.01: 0.40,  # Exit 40% at +1% profit (~1R for most trades)
            0.02: 0.30,  # Exit 30% more at +2% profit (~2R)
        })
        
        # Break-even trigger (move stop to entry + fees at this profit level)
        self.breakeven_trigger_pct = self.config.get('breakeven_trigger', 0.005)  # 0.5% profit
        
        # Fee buffer (add to break-even to cover fees)
        self.fee_buffer_pct = self.config.get('fee_buffer', 0.0015)  # 0.15% (covers typical fees)
        
        # Time-based exit (if no movement within X minutes, exit)
        self.stagnation_minutes = self.config.get('stagnation_minutes', 30)
        self.stagnation_min_movement_pct = self.config.get('stagnation_min_movement', 0.003)  # 0.3% minimum movement
        
        # Track position state
        self.position_states = {}  # symbol -> state dict
        
        logger.info("✅ Profit Protection System initialized")
        logger.info(f"   Partial exits: {len(self.exit_schedule)} levels")
        logger.info(f"   Break-even trigger: +{self.breakeven_trigger_pct*100:.2f}%")
        logger.info(f"   Stagnation timeout: {self.stagnation_minutes} min")
    
    def register_position(self, symbol: str, entry_price: float, entry_time: datetime, initial_size: float):
        """Track a new position for profit protection"""
        self.position_states[symbol] = {
            'entry_price': entry_price,
            'entry_time': entry_time,
            'initial_size': initial_size,
            'current_size': initial_size,
            'exits_taken': [],  # Track which exit levels have been hit
            'breakeven_set': False,
            'high_water_mark': entry_price  # Track best price achieved
        }
        logger.debug(f"Position registered: {symbol} @ ${entry_price:.4f}")
    
    def unregister_position(self, symbol: str):
        """Remove position from tracking"""
        if symbol in self.position_states:
            del self.position_states[symbol]
            logger.debug(f"Position unregistered: {symbol}")
    
    def check_partial_exit(
        self,
        symbol: str,
        current_price: float,
        direction: str
    ) -> Optional[Tuple[float, str]]:
        """
        Check if position should take partial profit.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            direction: 'long' or 'short'
        
        Returns:
            Tuple of (exit_percentage, reason) or None
        """
        if symbol not in self.position_states:
            return None
        
        state = self.position_states[symbol]
        entry = state['entry_price']
        
        # Calculate profit percentage
        if direction == 'long':
            profit_pct = (current_price - entry) / entry
        else:
            profit_pct = (entry - current_price) / entry
        
        # Check each exit level
        for threshold_pct, exit_pct in sorted(self.exit_schedule.items()):
            if profit_pct >= threshold_pct:
                # Check if we've already exited at this level
                if threshold_pct not in state['exits_taken']:
                    state['exits_taken'].append(threshold_pct)
                    reason = f"Partial exit {exit_pct*100:.0f}% at +{profit_pct*100:.2f}% profit"
                    logger.info(f"   💰 {symbol}: {reason}")
                    return (exit_pct, reason)
        
        return None
    
    def check_breakeven_move(
        self,
        symbol: str,
        current_price: float,
        current_stop: float,
        direction: str
    ) -> Optional[Tuple[float, str]]:
        """
        Check if stop should be moved to break-even.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            current_stop: Current stop loss price
            direction: 'long' or 'short'
        
        Returns:
            Tuple of (new_stop_price, reason) or None
        """
        if symbol not in self.position_states:
            return None
        
        state = self.position_states[symbol]
        
        # Skip if already set
        if state['breakeven_set']:
            return None
        
        entry = state['entry_price']
        
        # Calculate profit percentage
        if direction == 'long':
            profit_pct = (current_price - entry) / entry
        else:
            profit_pct = (entry - current_price) / entry
        
        # Check if profit exceeds trigger
        if profit_pct >= self.breakeven_trigger_pct:
            # Calculate break-even stop (entry + fees)
            if direction == 'long':
                new_stop = entry * (1 + self.fee_buffer_pct)
            else:
                new_stop = entry * (1 - self.fee_buffer_pct)
            
            # Only move if new stop is better than current
            if direction == 'long' and new_stop > current_stop:
                state['breakeven_set'] = True
                reason = f"Break-even stop @ ${new_stop:.4f} (entry + fees)"
                logger.info(f"   🛡️ {symbol}: {reason}")
                return (new_stop, reason)
            elif direction == 'short' and new_stop < current_stop:
                state['breakeven_set'] = True
                reason = f"Break-even stop @ ${new_stop:.4f} (entry + fees)"
                logger.info(f"   🛡️ {symbol}: {reason}")
                return (new_stop, reason)
        
        return None
    
    def check_stagnation_exit(
        self,
        symbol: str,
        current_price: float,
        current_time: datetime,
        direction: str
    ) -> Optional[str]:
        """
        Check if position should exit due to stagnation.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            current_time: Current timestamp
            direction: 'long' or 'short'
        
        Returns:
            Exit reason string or None
        """
        if symbol not in self.position_states:
            return None
        
        state = self.position_states[symbol]
        entry_time = state['entry_time']
        entry_price = state['entry_price']
        
        # Calculate time held
        time_held = (current_time - entry_time).total_seconds() / 60  # minutes
        
        if time_held < self.stagnation_minutes:
            return None  # Not held long enough
        
        # Calculate movement since entry
        if direction == 'long':
            movement_pct = (current_price - entry_price) / entry_price
        else:
            movement_pct = (entry_price - current_price) / entry_price
        
        # Check if movement is below threshold
        if movement_pct < self.stagnation_min_movement_pct:
            reason = f"Stagnant position: {movement_pct*100:.2f}% movement in {time_held:.0f}min"
            logger.info(f"   ⏱️ {symbol}: {reason}")
            return reason
        
        return None
    
    def get_position_summary(self, symbol: str) -> Optional[Dict]:
        """Get current position protection state"""
        if symbol not in self.position_states:
            return None
        
        state = self.position_states[symbol]
        return {
            'entry_price': state['entry_price'],
            'entry_time': state['entry_time'],
            'current_size': state['current_size'],
            'exits_count': len(state['exits_taken']),
            'breakeven_set': state['breakeven_set']
        }
