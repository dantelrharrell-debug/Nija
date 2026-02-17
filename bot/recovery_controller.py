"""
NIJA Recovery Controller - Capital-First Safety System
======================================================

This is the AUTHORITATIVE control layer that sits above:
- Trading strategy
- Broker calls
- Execution threads
- Risk management

It has the power to HALT everything when capital safety is uncertain.

Key Responsibilities:
1. Maintain system state via Finite State Machine (FSM)
2. Enforce capital-safety matrix before every trading action
3. Own global trading_enabled and safe_mode flags
4. Manage state transitions with proper validation
5. Override all other systems when safety is compromised

This controller is the single source of truth for whether trading is allowed.
All trading decisions must consult this controller first.

Author: NIJA Trading Systems
Version: 1.0.0
Date: February 2026
"""

import os
import json
import logging
import threading
from datetime import datetime
from typing import Dict, Optional, Tuple, List
from enum import Enum
from pathlib import Path

logger = logging.getLogger("nija.recovery_controller")


class FailureState(Enum):
    """
    System failure states in order of severity.
    
    State transitions must follow valid paths to prevent undefined behavior.
    """
    NORMAL = "normal"                    # System operating normally, all features enabled
    DEGRADED = "degraded"                # Minor issues detected, reduced trading activity
    RECOVERY = "recovery"                # Recovering from failure, limited operations
    SAFE_MODE = "safe_mode"             # Capital protection mode, exits only, no entries
    EMERGENCY_HALT = "emergency_halt"    # Complete trading halt, no operations allowed


class CapitalSafetyLevel(Enum):
    """Capital safety assessment levels"""
    SAFE = "safe"                        # Capital is safe, normal operations
    CAUTION = "caution"                  # Approaching risk limits, reduce activity
    WARNING = "warning"                  # Risk limits breached, defensive mode
    DANGER = "danger"                    # Significant risk, exit positions
    CRITICAL = "critical"                # Emergency, halt all trading


class RecoveryController:
    """
    Capital-First Recovery Controller with FSM and Safety Matrix.
    
    This controller has AUTHORITY to override all other systems.
    It enforces capital safety through:
    1. Finite State Machine for deterministic behavior
    2. Capital-safety matrix for risk assessment
    3. Global trading enable/disable control
    4. Safe mode enforcement
    
    All trading operations must consult this controller before execution.
    """
    
    # State file for persistence
    STATE_FILE = ".nija_recovery_state.json"
    
    # Valid state transitions (source -> allowed_destinations)
    VALID_TRANSITIONS = {
        FailureState.NORMAL: [
            FailureState.DEGRADED,
            FailureState.SAFE_MODE,
            FailureState.EMERGENCY_HALT
        ],
        FailureState.DEGRADED: [
            FailureState.NORMAL,
            FailureState.RECOVERY,
            FailureState.SAFE_MODE,
            FailureState.EMERGENCY_HALT
        ],
        FailureState.RECOVERY: [
            FailureState.NORMAL,
            FailureState.DEGRADED,
            FailureState.SAFE_MODE,
            FailureState.EMERGENCY_HALT
        ],
        FailureState.SAFE_MODE: [
            FailureState.RECOVERY,
            FailureState.EMERGENCY_HALT
        ],
        FailureState.EMERGENCY_HALT: [
            FailureState.RECOVERY  # Only path out is through manual recovery
        ]
    }
    
    # Capital-Safety Matrix: Defines safety thresholds
    # Format: (balance_pct_remaining, position_count, drawdown_pct) -> CapitalSafetyLevel
    CAPITAL_SAFETY_MATRIX = {
        # Balance % remaining, Max positions, Max drawdown % -> Safety Level
        (90, 100, 10): CapitalSafetyLevel.SAFE,      # Strong capital, low drawdown
        (80, 50, 15): CapitalSafetyLevel.SAFE,       # Good capital, moderate positions
        (70, 30, 20): CapitalSafetyLevel.CAUTION,    # Approaching limits
        (60, 20, 25): CapitalSafetyLevel.WARNING,    # Risk limits breached
        (50, 10, 30): CapitalSafetyLevel.DANGER,     # Significant risk
        (0, 0, 40): CapitalSafetyLevel.CRITICAL,     # Emergency
    }
    
    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize Recovery Controller.
        
        Args:
            base_path: Base directory for state files (default: project root)
        """
        self._lock = threading.RLock()  # Reentrant lock for nested calls
        
        # Determine base path
        if base_path is None:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._base_path = base_path
        self._state_file = os.path.join(self._base_path, self.STATE_FILE)
        
        # Core state variables - AUTHORITATIVE
        self._current_state = FailureState.NORMAL
        self._trading_enabled = False  # DISABLED by default for safety
        self._safe_mode = False
        self._capital_safety_level = CapitalSafetyLevel.SAFE
        
        # State metadata
        self._state_entry_time = datetime.now()
        self._last_transition_time = None
        self._state_change_history = []
        self._failure_count = 0
        self._last_capital_check = None
        
        # Capital tracking
        self._initial_capital = None
        self._current_capital = None
        self._peak_capital = None
        self._current_drawdown_pct = 0.0
        self._position_count = 0
        
        # Load persisted state
        self._load_state()
        
        logger.info("=" * 70)
        logger.info("🛡️  RECOVERY CONTROLLER INITIALIZED")
        logger.info("=" * 70)
        logger.info(f"   Current State:        {self._current_state.value}")
        logger.info(f"   Trading Enabled:      {self._trading_enabled}")
        logger.info(f"   Safe Mode:            {self._safe_mode}")
        logger.info(f"   Capital Safety:       {self._capital_safety_level.value}")
        logger.info("=" * 70)
    
    def _load_state(self):
        """Load persisted recovery state"""
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r') as f:
                    data = json.load(f)
                    
                    # Restore state
                    state_name = data.get('current_state', 'normal')
                    try:
                        self._current_state = FailureState(state_name)
                    except ValueError:
                        logger.warning(f"Invalid state '{state_name}', defaulting to NORMAL")
                        self._current_state = FailureState.NORMAL
                    
                    self._trading_enabled = data.get('trading_enabled', False)
                    self._safe_mode = data.get('safe_mode', False)
                    self._failure_count = data.get('failure_count', 0)
                    self._state_change_history = data.get('history', [])
                    
                    # Restore capital tracking
                    self._initial_capital = data.get('initial_capital')
                    self._current_capital = data.get('current_capital')
                    self._peak_capital = data.get('peak_capital')
                    self._current_drawdown_pct = data.get('current_drawdown_pct', 0.0)
                    self._position_count = data.get('position_count', 0)
                    
                    logger.info(f"📂 Recovery state loaded from {self._state_file}")
                    
                    # If we're in a critical state, ensure trading is disabled
                    if self._current_state in [FailureState.SAFE_MODE, FailureState.EMERGENCY_HALT]:
                        self._trading_enabled = False
                        logger.warning(f"⚠️  Trading disabled due to state: {self._current_state.value}")
        except Exception as e:
            logger.error(f"❌ Error loading recovery state: {e}")
            # Safe defaults on error
            self._current_state = FailureState.NORMAL
            self._trading_enabled = False
            self._safe_mode = False
    
    def _save_state(self):
        """Persist recovery state"""
        try:
            with self._lock:
                data = {
                    'current_state': self._current_state.value,
                    'trading_enabled': self._trading_enabled,
                    'safe_mode': self._safe_mode,
                    'capital_safety_level': self._capital_safety_level.value,
                    'failure_count': self._failure_count,
                    'history': self._state_change_history[-50:],  # Keep last 50 events
                    'last_update': datetime.now().isoformat(),
                    # Capital tracking
                    'initial_capital': self._initial_capital,
                    'current_capital': self._current_capital,
                    'peak_capital': self._peak_capital,
                    'current_drawdown_pct': self._current_drawdown_pct,
                    'position_count': self._position_count
                }
                
                with open(self._state_file, 'w') as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Error saving recovery state: {e}")
    
    def _log_state_change(self, reason: str, additional_data: Optional[Dict] = None):
        """Log state change with timestamp and reason"""
        event = {
            'timestamp': datetime.now().isoformat(),
            'state': self._current_state.value,
            'trading_enabled': self._trading_enabled,
            'safe_mode': self._safe_mode,
            'capital_safety': self._capital_safety_level.value,
            'reason': reason
        }
        
        if additional_data:
            event.update(additional_data)
        
        self._state_change_history.append(event)
        logger.info(f"📝 State Change: {reason}")
    
    def transition_to(self, new_state: FailureState, reason: str) -> bool:
        """
        Transition to a new state with validation.
        
        Args:
            new_state: Target state
            reason: Reason for transition
            
        Returns:
            bool: True if transition successful, False if invalid
        """
        with self._lock:
            # Check if transition is valid
            if new_state not in self.VALID_TRANSITIONS[self._current_state]:
                logger.error(
                    f"❌ INVALID STATE TRANSITION: {self._current_state.value} -> {new_state.value}"
                )
                logger.error(f"   Reason: {reason}")
                logger.error(f"   Valid transitions from {self._current_state.value}: "
                           f"{[s.value for s in self.VALID_TRANSITIONS[self._current_state]]}")
                return False
            
            old_state = self._current_state
            self._current_state = new_state
            self._last_transition_time = datetime.now()
            self._state_entry_time = datetime.now()
            
            # Update flags based on state
            if new_state == FailureState.EMERGENCY_HALT:
                self._trading_enabled = False
                self._safe_mode = True
            elif new_state == FailureState.SAFE_MODE:
                self._trading_enabled = False  # No new entries
                self._safe_mode = True
            elif new_state == FailureState.RECOVERY:
                self._trading_enabled = False  # Limited operations during recovery
                self._safe_mode = True
            elif new_state == FailureState.DEGRADED:
                # Keep current trading_enabled, but raise caution
                self._safe_mode = False
            elif new_state == FailureState.NORMAL:
                # Trading must be explicitly enabled, not automatic
                self._safe_mode = False
            
            logger.warning("=" * 70)
            logger.warning(f"🔄 STATE TRANSITION: {old_state.value} → {new_state.value}")
            logger.warning("=" * 70)
            logger.warning(f"   Reason:           {reason}")
            logger.warning(f"   Trading Enabled:  {self._trading_enabled}")
            logger.warning(f"   Safe Mode:        {self._safe_mode}")
            logger.warning("=" * 70)
            
            self._log_state_change(
                f"Transition from {old_state.value} to {new_state.value}: {reason}"
            )
            self._save_state()
            
            return True
    
    def assess_capital_safety(
        self,
        current_balance: float,
        initial_balance: Optional[float] = None,
        position_count: int = 0,
        open_pnl: float = 0.0
    ) -> CapitalSafetyLevel:
        """
        Assess capital safety using the capital-safety matrix.
        
        Args:
            current_balance: Current account balance
            initial_balance: Initial capital (tracked if not provided)
            position_count: Number of open positions
            open_pnl: Unrealized P&L
            
        Returns:
            CapitalSafetyLevel: Current safety assessment
        """
        with self._lock:
            # Initialize capital tracking if needed
            if self._initial_capital is None and initial_balance:
                self._initial_capital = initial_balance
                self._peak_capital = initial_balance
                logger.info(f"📊 Capital tracking initialized: ${initial_balance:.2f}")
            
            # Update capital tracking
            self._current_capital = current_balance
            self._position_count = position_count
            
            # Update peak capital
            if self._peak_capital is None or current_balance > self._peak_capital:
                self._peak_capital = current_balance
            
            # Calculate metrics
            if self._initial_capital and self._initial_capital > 0:
                balance_pct = (current_balance / self._initial_capital) * 100
            else:
                balance_pct = 100.0
            
            # Calculate drawdown from peak
            if self._peak_capital and self._peak_capital > 0:
                self._current_drawdown_pct = (
                    (self._peak_capital - current_balance) / self._peak_capital
                ) * 100
            else:
                self._current_drawdown_pct = 0.0
            
            # Find matching safety level in matrix
            safety_level = CapitalSafetyLevel.SAFE
            
            for (min_balance_pct, max_positions, max_drawdown), level in sorted(
                self.CAPITAL_SAFETY_MATRIX.items(),
                key=lambda x: x[0][0],  # Sort by balance percentage
                reverse=True
            ):
                if (balance_pct >= min_balance_pct and
                    position_count <= max_positions and
                    self._current_drawdown_pct <= max_drawdown):
                    safety_level = level
                    break
            
            # Override with more severe level if any single metric is critical
            if balance_pct < 50:
                safety_level = CapitalSafetyLevel.DANGER
            if balance_pct < 30:
                safety_level = CapitalSafetyLevel.CRITICAL
            if self._current_drawdown_pct > 40:
                safety_level = CapitalSafetyLevel.CRITICAL
            
            # Update internal state
            old_level = self._capital_safety_level
            self._capital_safety_level = safety_level
            self._last_capital_check = datetime.now()
            
            # Log if safety level changed
            if old_level != safety_level:
                logger.warning("=" * 70)
                logger.warning(f"⚠️  CAPITAL SAFETY LEVEL CHANGED: {old_level.value} → {safety_level.value}")
                logger.warning("=" * 70)
                logger.warning(f"   Current Balance:  ${current_balance:.2f} ({balance_pct:.1f}% of initial)")
                logger.warning(f"   Peak Capital:     ${self._peak_capital:.2f}")
                logger.warning(f"   Drawdown:         {self._current_drawdown_pct:.2f}%")
                logger.warning(f"   Position Count:   {position_count}")
                logger.warning("=" * 70)
                
                self._log_state_change(
                    f"Capital safety changed to {safety_level.value}",
                    {
                        'balance': current_balance,
                        'balance_pct': balance_pct,
                        'drawdown_pct': self._current_drawdown_pct,
                        'position_count': position_count
                    }
                )
                
                # Trigger state transitions based on safety level
                if safety_level == CapitalSafetyLevel.CRITICAL:
                    self.transition_to(
                        FailureState.EMERGENCY_HALT,
                        "Critical capital safety level reached"
                    )
                elif safety_level == CapitalSafetyLevel.DANGER:
                    self.transition_to(
                        FailureState.SAFE_MODE,
                        "Dangerous capital safety level reached"
                    )
                elif safety_level == CapitalSafetyLevel.WARNING:
                    if self._current_state == FailureState.NORMAL:
                        self.transition_to(
                            FailureState.DEGRADED,
                            "Warning capital safety level reached"
                        )
            
            self._save_state()
            return safety_level
    
    def can_trade(self, operation: str = "entry") -> Tuple[bool, str]:
        """
        Check if trading is allowed - AUTHORITATIVE CHECK.
        
        This is the single source of truth for trading permission.
        All trading operations MUST call this before proceeding.
        
        Args:
            operation: Type of operation ("entry", "exit", "modify")
            
        Returns:
            Tuple[bool, str]: (allowed, reason)
        """
        with self._lock:
            # Emergency halt - NOTHING is allowed
            if self._current_state == FailureState.EMERGENCY_HALT:
                return False, "EMERGENCY HALT - All trading operations disabled"
            
            # Safe mode - exits only
            if self._current_state == FailureState.SAFE_MODE:
                if operation == "exit":
                    return True, "Exit allowed in safe mode"
                return False, f"SAFE MODE - {operation} operations blocked, exits only"
            
            # Recovery mode - limited operations
            if self._current_state == FailureState.RECOVERY:
                if operation == "exit":
                    return True, "Exit allowed in recovery mode"
                return False, f"RECOVERY MODE - {operation} operations blocked"
            
            # Check global trading flag
            if not self._trading_enabled:
                return False, "Trading globally disabled"
            
            # Check capital safety for entries
            if operation == "entry":
                if self._capital_safety_level in [
                    CapitalSafetyLevel.DANGER,
                    CapitalSafetyLevel.CRITICAL
                ]:
                    return False, f"Capital safety level {self._capital_safety_level.value} - entries blocked"
                
                if self._capital_safety_level == CapitalSafetyLevel.WARNING:
                    return False, "Capital safety warning - entries reduced"
            
            # Degraded state - allow with caution
            if self._current_state == FailureState.DEGRADED:
                if operation == "entry" and self._capital_safety_level == CapitalSafetyLevel.CAUTION:
                    return True, "Entry allowed (degraded state, caution advised)"
            
            # Normal state - all operations allowed
            if self._current_state == FailureState.NORMAL:
                return True, "Trading allowed (normal state)"
            
            # Default deny
            return False, f"Trading blocked in state {self._current_state.value}"
    
    def enable_trading(self, reason: str = "Manual enable"):
        """
        Enable trading globally.
        
        Args:
            reason: Reason for enabling trading
        """
        with self._lock:
            if self._current_state in [FailureState.EMERGENCY_HALT, FailureState.SAFE_MODE]:
                logger.error(
                    f"❌ Cannot enable trading in state {self._current_state.value}"
                )
                logger.error("   Must recover to NORMAL or DEGRADED state first")
                return False
            
            old_value = self._trading_enabled
            self._trading_enabled = True
            
            if not old_value:
                logger.info("=" * 70)
                logger.info("✅ TRADING ENABLED")
                logger.info("=" * 70)
                logger.info(f"   Reason: {reason}")
                logger.info(f"   State:  {self._current_state.value}")
                logger.info("=" * 70)
                
                self._log_state_change(f"Trading enabled: {reason}")
                self._save_state()
            
            return True
    
    def disable_trading(self, reason: str = "Manual disable"):
        """
        Disable trading globally.
        
        Args:
            reason: Reason for disabling trading
        """
        with self._lock:
            old_value = self._trading_enabled
            self._trading_enabled = False
            
            if old_value:
                logger.warning("=" * 70)
                logger.warning("🛑 TRADING DISABLED")
                logger.warning("=" * 70)
                logger.warning(f"   Reason: {reason}")
                logger.warning(f"   State:  {self._current_state.value}")
                logger.warning("=" * 70)
                
                self._log_state_change(f"Trading disabled: {reason}")
                self._save_state()
            
            return True
    
    def record_failure(self, failure_type: str, details: str):
        """
        Record a system failure and adjust state accordingly.
        
        Args:
            failure_type: Type of failure (e.g., "broker_error", "execution_failure")
            details: Detailed description
        """
        with self._lock:
            self._failure_count += 1
            
            logger.error("=" * 70)
            logger.error(f"❌ FAILURE RECORDED: {failure_type}")
            logger.error("=" * 70)
            logger.error(f"   Details:        {details}")
            logger.error(f"   Failure Count:  {self._failure_count}")
            logger.error("=" * 70)
            
            self._log_state_change(
                f"Failure recorded: {failure_type}",
                {'details': details, 'failure_count': self._failure_count}
            )
            
            # Adjust state based on failure count
            if self._failure_count >= 10:
                self.transition_to(
                    FailureState.EMERGENCY_HALT,
                    f"Critical failure count reached: {self._failure_count}"
                )
            elif self._failure_count >= 5:
                self.transition_to(
                    FailureState.SAFE_MODE,
                    f"High failure count: {self._failure_count}"
                )
            elif self._failure_count >= 2:
                if self._current_state == FailureState.NORMAL:
                    self.transition_to(
                        FailureState.DEGRADED,
                        f"Multiple failures detected: {self._failure_count}"
                    )
            
            self._save_state()
    
    def reset_failures(self):
        """Reset failure count (manual recovery)"""
        with self._lock:
            old_count = self._failure_count
            self._failure_count = 0
            
            logger.info(f"🔄 Failure count reset: {old_count} → 0")
            self._log_state_change("Failure count manually reset")
            self._save_state()
    
    def get_status(self) -> Dict:
        """
        Get comprehensive recovery controller status.
        
        Returns:
            Dict: Complete status information
        """
        with self._lock:
            return {
                'state': self._current_state.value,
                'trading_enabled': self._trading_enabled,
                'safe_mode': self._safe_mode,
                'capital_safety_level': self._capital_safety_level.value,
                'failure_count': self._failure_count,
                'state_entry_time': self._state_entry_time.isoformat() if self._state_entry_time else None,
                'last_transition': self._last_transition_time.isoformat() if self._last_transition_time else None,
                'last_capital_check': self._last_capital_check.isoformat() if self._last_capital_check else None,
                'capital': {
                    'initial': self._initial_capital,
                    'current': self._current_capital,
                    'peak': self._peak_capital,
                    'drawdown_pct': self._current_drawdown_pct,
                    'position_count': self._position_count
                },
                'valid_transitions': [s.value for s in self.VALID_TRANSITIONS[self._current_state]]
            }
    
    @property
    def is_trading_enabled(self) -> bool:
        """Check if trading is globally enabled"""
        return self._trading_enabled
    
    @property
    def is_safe_mode(self) -> bool:
        """Check if safe mode is active"""
        return self._safe_mode
    
    @property
    def current_state(self) -> FailureState:
        """Get current failure state"""
        return self._current_state
    
    @property
    def capital_safety_level(self) -> CapitalSafetyLevel:
        """Get current capital safety level"""
        return self._capital_safety_level


# Global singleton instance
_recovery_controller = None
_controller_lock = threading.Lock()


def get_recovery_controller(base_path: Optional[str] = None) -> RecoveryController:
    """
    Get the global RecoveryController singleton.
    
    Args:
        base_path: Base directory for state files (default: project root)
        
    Returns:
        RecoveryController: Global instance
    """
    global _recovery_controller
    
    with _controller_lock:
        if _recovery_controller is None:
            _recovery_controller = RecoveryController(base_path=base_path)
            logger.info("🛡️  Global Recovery Controller created")
        
        return _recovery_controller


def reset_recovery_controller():
    """Reset the global controller (for testing)"""
    global _recovery_controller
    
    with _controller_lock:
        _recovery_controller = None
        logger.warning("⚠️  Global Recovery Controller reset")
