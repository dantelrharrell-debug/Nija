"""
NIJA Trading State Machine - Single Source of Truth for Trading State

CRITICAL SAFETY MODULE - Absolute control over trading state transitions.

This is the SINGLE SOURCE OF TRUTH for all trading state in NIJA.
NO trading operations should bypass this state machine.

States:
    OFF - Default safe state, no trading allowed
    DRY_RUN - Simulation mode, no real orders
    LIVE_PENDING_CONFIRMATION - User initiated live mode but hasn't confirmed risk
    LIVE_ACTIVE - Live trading active with real capital
    EMERGENCY_STOP - Immediate halt of all operations

Rules:
    ❌ No broker calls unless LIVE_ACTIVE
    ❌ No background threads unless explicitly allowed
    ❌ Restart ALWAYS defaults to OFF
    ✅ State persisted to disk + logged
    ✅ All state changes are audited

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import os
import json
import logging
import threading
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from pathlib import Path

logger = logging.getLogger("nija.trading_state_machine")


class TradingState(Enum):
    """Trading state enumeration - SINGLE SOURCE OF TRUTH"""
    OFF = "OFF"
    DRY_RUN = "DRY_RUN"
    LIVE_PENDING_CONFIRMATION = "LIVE_PENDING_CONFIRMATION"
    LIVE_ACTIVE = "LIVE_ACTIVE"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted"""
    pass


class TradingStateMachine:
    """
    NIJA Trading State Machine - Absolute control over trading state.
    
    This class enforces the ZERO-FAIL ZONE:
    - Restart always defaults to OFF
    - No broker operations unless LIVE_ACTIVE
    - All state changes are persisted and logged
    - Invalid transitions are blocked
    """
    
    # Valid state transitions (from_state -> [allowed_to_states])
    VALID_TRANSITIONS = {
        TradingState.OFF: [
            TradingState.DRY_RUN,
            TradingState.LIVE_PENDING_CONFIRMATION,
            TradingState.EMERGENCY_STOP
        ],
        TradingState.DRY_RUN: [
            TradingState.OFF,
            TradingState.LIVE_PENDING_CONFIRMATION,
            TradingState.EMERGENCY_STOP
        ],
        TradingState.LIVE_PENDING_CONFIRMATION: [
            TradingState.OFF,
            TradingState.LIVE_ACTIVE,
            TradingState.EMERGENCY_STOP
        ],
        TradingState.LIVE_ACTIVE: [
            TradingState.OFF,
            TradingState.DRY_RUN,
            TradingState.EMERGENCY_STOP
        ],
        TradingState.EMERGENCY_STOP: [
            TradingState.OFF  # Can only go to OFF from emergency stop
        ]
    }
    
    def __init__(self, state_file: Optional[str] = None):
        """
        Initialize trading state machine.
        
        Args:
            state_file: Path to state persistence file (default: .nija_trading_state.json)
        """
        self._lock = threading.Lock()
        self._state_file = state_file or os.path.join(
            os.path.dirname(__file__), 
            "..", 
            ".nija_trading_state.json"
        )
        self._state_callbacks: Dict[TradingState, list] = {state: [] for state in TradingState}
        
        # CRITICAL: Always start in OFF state on initialization
        # This ensures restart always defaults to OFF
        self._current_state = TradingState.OFF
        self._state_history = []
        
        # Try to load persisted state, but NEVER start in LIVE_ACTIVE
        self._load_state()
        
        # Log initialization
        logger.info(f"🔒 Trading State Machine initialized in {self._current_state.value} state")
        logger.info(f"📝 State persistence: {self._state_file}")
        
    def _load_state(self):
        """
        Load persisted state from disk.
        
        CRITICAL SAFETY: Even if persisted state was LIVE_ACTIVE,
        we NEVER auto-resume live trading after restart.
        """
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r') as f:
                    data = json.load(f)
                    
                persisted_state = TradingState(data.get('current_state', 'OFF'))
                self._state_history = data.get('history', [])
                
                # SAFETY: Never auto-resume LIVE_ACTIVE
                if persisted_state == TradingState.LIVE_ACTIVE:
                    logger.warning(
                        "⚠️  Previous state was LIVE_ACTIVE but restart always defaults to OFF"
                    )
                    logger.warning("⚠️  User must manually re-enable live trading")
                    self._current_state = TradingState.OFF
                elif persisted_state == TradingState.LIVE_PENDING_CONFIRMATION:
                    # Also reset pending confirmation
                    logger.info("Previous state was LIVE_PENDING_CONFIRMATION, resetting to OFF")
                    self._current_state = TradingState.OFF
                else:
                    self._current_state = persisted_state
                    
                logger.info(f"📂 Loaded state from disk: {self._current_state.value}")
            else:
                logger.info("📂 No persisted state found, starting in OFF state")
        except Exception as e:
            logger.error(f"❌ Error loading state, defaulting to OFF: {e}")
            self._current_state = TradingState.OFF
            
    def _persist_state(self):
        """Persist current state to disk"""
        try:
            data = {
                'current_state': self._current_state.value,
                'history': self._state_history,
                'last_updated': datetime.utcnow().isoformat()
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            
            # Write atomically
            temp_file = f"{self._state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self._state_file)
            
            logger.debug(f"💾 State persisted: {self._current_state.value}")
        except Exception as e:
            logger.error(f"❌ Error persisting state: {e}")
            
    def get_current_state(self) -> TradingState:
        """Get current trading state (thread-safe)"""
        with self._lock:
            return self._current_state
            
    def is_trading_allowed(self) -> bool:
        """Check if trading (any kind) is allowed in current state"""
        state = self.get_current_state()
        return state in [TradingState.DRY_RUN, TradingState.LIVE_ACTIVE]
        
    def is_live_trading_active(self) -> bool:
        """Check if LIVE trading with real capital is active"""
        return self.get_current_state() == TradingState.LIVE_ACTIVE
        
    def is_dry_run_mode(self) -> bool:
        """Check if in dry run (simulation) mode"""
        return self.get_current_state() == TradingState.DRY_RUN
        
    def is_emergency_stopped(self) -> bool:
        """Check if in emergency stop state"""
        return self.get_current_state() == TradingState.EMERGENCY_STOP
        
    def can_make_broker_calls(self) -> bool:
        """
        Check if broker API calls are allowed.
        
        CRITICAL: Only returns True when LIVE_ACTIVE.
        This prevents accidental real trades in other states.
        """
        return self.get_current_state() == TradingState.LIVE_ACTIVE
        
    def transition_to(self, new_state: TradingState, reason: str = "") -> bool:
        """
        Attempt to transition to a new state.
        
        Args:
            new_state: Target state
            reason: Human-readable reason for transition
            
        Returns:
            True if transition successful, False otherwise
            
        Raises:
            StateTransitionError: If transition is not allowed
        """
        with self._lock:
            current = self._current_state
            
            # Check if transition is valid
            if new_state not in self.VALID_TRANSITIONS.get(current, []):
                error_msg = (
                    f"Invalid state transition: {current.value} -> {new_state.value}. "
                    f"Allowed transitions from {current.value}: "
                    f"{[s.value for s in self.VALID_TRANSITIONS.get(current, [])]}"
                )
                logger.error(f"❌ {error_msg}")
                raise StateTransitionError(error_msg)
                
            # Record transition
            transition_record = {
                'from': current.value,
                'to': new_state.value,
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat()
            }
            self._state_history.append(transition_record)
            
            # Update state
            old_state = self._current_state
            self._current_state = new_state
            
            # Persist
            self._persist_state()
            
            # Log transition
            logger.info(
                f"🔄 State transition: {old_state.value} -> {new_state.value} "
                f"(Reason: {reason or 'No reason provided'})"
            )
            
            # Trigger callbacks
            self._trigger_callbacks(new_state)
            
            return True
            
    def register_callback(self, state: TradingState, callback: Callable):
        """
        Register a callback to be called when entering a specific state.
        
        Args:
            state: State to trigger callback
            callback: Function to call (takes no arguments)
        """
        with self._lock:
            self._state_callbacks[state].append(callback)
            logger.debug(f"📌 Registered callback for {state.value} state")
            
    def _trigger_callbacks(self, state: TradingState):
        """Trigger all callbacks registered for a state"""
        callbacks = self._state_callbacks.get(state, [])
        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"❌ Error executing state callback: {e}")
                
    def get_state_history(self, limit: int = 10) -> list:
        """Get recent state transition history"""
        with self._lock:
            return self._state_history[-limit:] if self._state_history else []
            
    def get_state_summary(self) -> Dict[str, Any]:
        """Get comprehensive state summary for debugging/monitoring"""
        with self._lock:
            return {
                'current_state': self._current_state.value,
                'is_trading_allowed': self.is_trading_allowed(),
                'is_live_trading_active': self.is_live_trading_active(),
                'is_dry_run_mode': self.is_dry_run_mode(),
                'is_emergency_stopped': self.is_emergency_stopped(),
                'can_make_broker_calls': self.can_make_broker_calls(),
                'recent_history': self.get_state_history(5)
            }
            

# Global singleton instance
_state_machine: Optional[TradingStateMachine] = None
_instance_lock = threading.Lock()


def get_state_machine() -> TradingStateMachine:
    """Get the global trading state machine instance (singleton)"""
    global _state_machine
    
    if _state_machine is None:
        with _instance_lock:
            if _state_machine is None:
                _state_machine = TradingStateMachine()
                
    return _state_machine


def require_state(required_state: TradingState):
    """
    Decorator to enforce that a function can only run in a specific state.
    
    Usage:
        @require_state(TradingState.LIVE_ACTIVE)
        def place_real_order():
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            state_machine = get_state_machine()
            current = state_machine.get_current_state()
            
            if current != required_state:
                raise StateTransitionError(
                    f"Function {func.__name__} requires state {required_state.value} "
                    f"but current state is {current.value}"
                )
                
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_live_trading():
    """
    Decorator to enforce that a function can only run when live trading is active.
    
    Usage:
        @require_live_trading()
        def submit_real_order():
            ...
    """
    return require_state(TradingState.LIVE_ACTIVE)


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test state machine
    sm = get_state_machine()
    
    print("\n=== Trading State Machine Test ===")
    print(f"Initial state: {sm.get_current_state().value}")
    print(f"Can make broker calls: {sm.can_make_broker_calls()}")
    
    # Test valid transitions
    print("\n--- Testing valid transitions ---")
    sm.transition_to(TradingState.DRY_RUN, "Testing dry run mode")
    print(f"Current state: {sm.get_current_state().value}")
    
    sm.transition_to(TradingState.LIVE_PENDING_CONFIRMATION, "User wants to go live")
    print(f"Current state: {sm.get_current_state().value}")
    
    sm.transition_to(TradingState.LIVE_ACTIVE, "User confirmed risk")
    print(f"Current state: {sm.get_current_state().value}")
    print(f"Can make broker calls: {sm.can_make_broker_calls()}")
    
    # Test emergency stop
    print("\n--- Testing emergency stop ---")
    sm.transition_to(TradingState.EMERGENCY_STOP, "Emergency button pressed")
    print(f"Current state: {sm.get_current_state().value}")
    print(f"Can make broker calls: {sm.can_make_broker_calls()}")
    
    # Test invalid transition
    print("\n--- Testing invalid transition ---")
    try:
        sm.transition_to(TradingState.LIVE_ACTIVE, "Try to go live from emergency stop")
    except StateTransitionError as e:
        print(f"Caught expected error: {e}")
        
    # Show history
    print("\n--- State history ---")
    for entry in sm.get_state_history():
        print(f"  {entry['from']} -> {entry['to']}: {entry['reason']}")
        
    print("\n--- State summary ---")
    summary = sm.get_state_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
