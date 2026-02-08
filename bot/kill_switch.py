"""
NIJA Global Kill-Switch - HARD STOP

CRITICAL SAFETY MODULE - Immediate halt of ALL trading operations.

This is NOT a "pause" or "soft stop".
This is an IMMEDIATE, HARD STOP that:
    - Kills all entry signals
    - Kills all exit signals
    - Kills all retries
    - Kills all background loops
    - Kills all webhook processing
    - Kills all timers
    
Must work:
    - Mid-trade
    - From UI
    - From CLI
    - From ENV variable
    - From file system
    
All activations are logged with timestamp and reason.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import os
import json
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger("nija.kill_switch")


class KillSwitch:
    """
    Global Kill-Switch - Immediate halt of all trading operations.
    
    This is the NUCLEAR OPTION for stopping trading.
    When activated, NOTHING continues.
    """
    
    # File-based kill switch (checked on every critical operation)
    KILL_SWITCH_FILE = "EMERGENCY_STOP"
    
    # State file to persist kill switch activations
    KILL_SWITCH_STATE_FILE = ".nija_kill_switch_state.json"
    
    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize kill switch.
        
        Args:
            base_path: Base directory for kill switch files (default: project root)
        """
        self._lock = threading.Lock()
        
        # Determine base path
        if base_path is None:
            # Default to project root (parent of bot directory)
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._base_path = base_path
        
        # File paths
        self._kill_file = os.path.join(self._base_path, self.KILL_SWITCH_FILE)
        self._state_file = os.path.join(self._base_path, self.KILL_SWITCH_STATE_FILE)
        
        # In-memory state
        self._is_active = False
        self._activation_history = []
        
        # Load persisted state
        self._load_state()
        
        # Check for file-based activation
        self._check_file_activation()
        
        logger.info(f"🔴 Kill Switch initialized (Active: {self._is_active})")
        
    def _load_state(self):
        """Load persisted kill switch state"""
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r') as f:
                    data = json.load(f)
                    self._activation_history = data.get('history', [])
                    
                    # Check if there's an active kill switch from previous session
                    if data.get('is_active', False):
                        logger.warning("⚠️  Kill switch was active in previous session")
                        # Keep it active for safety
                        self._is_active = True
        except Exception as e:
            logger.error(f"❌ Error loading kill switch state: {e}")
            
    def _persist_state(self):
        """Persist kill switch state to disk"""
        try:
            data = {
                'is_active': self._is_active,
                'history': self._activation_history,
                'last_updated': datetime.utcnow().isoformat()
            }
            
            temp_file = f"{self._state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self._state_file)
            
        except Exception as e:
            logger.error(f"❌ Error persisting kill switch state: {e}")
            
    def _check_file_activation(self):
        """Check if kill switch file exists"""
        if os.path.exists(self._kill_file):
            logger.warning(f"🚨 Kill switch file detected: {self._kill_file}")
            if not self._is_active:
                self._activate_internal("Kill switch file detected", "FILE_SYSTEM")
                
    def _create_kill_file(self, reason: str):
        """Create kill switch file on disk"""
        try:
            with open(self._kill_file, 'w') as f:
                f.write(f"""
╔════════════════════════════════════════════════════════════════╗
║                    🚨 EMERGENCY STOP ACTIVE 🚨                  ║
╚════════════════════════════════════════════════════════════════╝

ALL TRADING OPERATIONS HAVE BEEN HALTED

Reason: {reason}
Activated: {datetime.utcnow().isoformat()}

To resume trading:
1. Delete this file: rm {self.KILL_SWITCH_FILE}
2. Investigate and resolve the issue
3. Manually restart the bot
4. Carefully monitor initial trades

⚠️  DO NOT resume trading without understanding why the kill switch was activated.

""")
            logger.info(f"📝 Created kill switch file: {self._kill_file}")
        except Exception as e:
            logger.error(f"❌ Error creating kill switch file: {e}")
            
    def _remove_kill_file(self):
        """Remove kill switch file from disk"""
        try:
            if os.path.exists(self._kill_file):
                os.remove(self._kill_file)
                logger.info(f"🗑️  Removed kill switch file: {self._kill_file}")
        except Exception as e:
            logger.error(f"❌ Error removing kill switch file: {e}")
            
    def _activate_internal(self, reason: str, source: str):
        """Internal activation logic"""
        activation_record = {
            'reason': reason,
            'source': source,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        self._is_active = True
        self._activation_history.append(activation_record)
        
        # Persist state
        self._persist_state()
        
        # Create file marker
        self._create_kill_file(reason)
        
        # Log prominently
        logger.critical("=" * 80)
        logger.critical("🚨 KILL SWITCH ACTIVATED 🚨")
        logger.critical("=" * 80)
        logger.critical(f"Reason: {reason}")
        logger.critical(f"Source: {source}")
        logger.critical(f"Timestamp: {activation_record['timestamp']}")
        logger.critical("=" * 80)
        logger.critical("ALL TRADING OPERATIONS HALTED")
        logger.critical("=" * 80)
        
    def activate(self, reason: str, source: str = "MANUAL"):
        """
        Activate the kill switch - IMMEDIATE HALT.
        
        Args:
            reason: Human-readable reason for activation
            source: Source of activation (MANUAL, UI, CLI, ENV, FILE_SYSTEM, AUTO)
        """
        with self._lock:
            if self._is_active:
                logger.warning(f"⚠️  Kill switch already active, reason: {reason}")
                return
                
            self._activate_internal(reason, source)
            
            # Also transition state machine to EMERGENCY_STOP
            try:
                from bot.trading_state_machine import get_state_machine, TradingState
                state_machine = get_state_machine()
                state_machine.transition_to(
                    TradingState.EMERGENCY_STOP,
                    f"Kill switch activated: {reason}"
                )
            except Exception as e:
                logger.error(f"❌ Error transitioning state machine: {e}")
                
    def deactivate(self, reason: str = "Manual deactivation"):
        """
        Deactivate the kill switch.
        
        CAUTION: This should only be done after:
        1. Understanding why it was activated
        2. Resolving the underlying issue
        3. Verifying system integrity
        
        Args:
            reason: Reason for deactivation
        """
        with self._lock:
            if not self._is_active:
                logger.info("Kill switch already inactive")
                return
                
            deactivation_record = {
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat()
            }
            self._activation_history.append(deactivation_record)
            
            self._is_active = False
            
            # Remove file marker
            self._remove_kill_file()
            
            # Persist state
            self._persist_state()
            
            logger.warning("=" * 80)
            logger.warning("🟢 KILL SWITCH DEACTIVATED 🟢")
            logger.warning("=" * 80)
            logger.warning(f"Reason: {reason}")
            logger.warning(f"Timestamp: {deactivation_record['timestamp']}")
            logger.warning("=" * 80)
            logger.warning("⚠️  System can resume trading, but manual verification recommended")
            logger.warning("=" * 80)
            
    def is_active(self) -> bool:
        """
        Check if kill switch is active.
        
        CRITICAL: This should be checked before EVERY trading operation.
        """
        with self._lock:
            # Always check file system as well (might be manually created)
            self._check_file_activation()
            return self._is_active
            
    def assert_not_active(self, operation: str = "operation"):
        """
        Assert that kill switch is not active.
        
        Raises RuntimeError if active.
        Use this to guard critical operations.
        
        Args:
            operation: Description of operation being guarded
        """
        if self.is_active():
            error_msg = f"Cannot perform {operation}: KILL SWITCH IS ACTIVE"
            logger.error(f"🚨 {error_msg}")
            raise RuntimeError(error_msg)
            
    def get_status(self) -> Dict[str, Any]:
        """Get current kill switch status"""
        with self._lock:
            return {
                'is_active': self._is_active,
                'kill_file_exists': os.path.exists(self._kill_file),
                'kill_file_path': self._kill_file,
                'recent_history': self._activation_history[-5:] if self._activation_history else []
            }
            
    def get_activation_count(self) -> int:
        """Get total number of times kill switch has been activated"""
        with self._lock:
            return len([h for h in self._activation_history if 'source' in h])


# ============================================================================
# AUTO-TRIGGER SYSTEM - Added February 8, 2026
# ============================================================================

class KillSwitchAutoTrigger:
    """
    Automatic kill switch triggers based on risk thresholds.
    
    Monitors:
    - Max daily loss %
    - Consecutive losing trades
    - API instability (consecutive errors)
    - Unexpected balance delta
    """
    
    def __init__(
        self,
        max_daily_loss_pct: float = 10.0,
        max_consecutive_losses: int = 5,
        max_consecutive_api_errors: int = 10,
        max_balance_delta_pct: float = 50.0,
        enable_auto_trigger: bool = True
    ):
        """
        Initialize auto-trigger system.
        
        Args:
            max_daily_loss_pct: Max % loss before kill switch (default 10%)
            max_consecutive_losses: Max consecutive losses (default 5)
            max_consecutive_api_errors: Max API errors (default 10)
            max_balance_delta_pct: Max unexpected balance change % (default 50%)
            enable_auto_trigger: Enable automatic triggers
        """
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_consecutive_api_errors = max_consecutive_api_errors
        self.max_balance_delta_pct = max_balance_delta_pct
        self.enable_auto_trigger = enable_auto_trigger
        
        # Track metrics
        self._daily_starting_balance: Optional[float] = None
        self._daily_start_time: Optional[datetime] = None
        self._consecutive_losses = 0
        self._consecutive_api_errors = 0
        self._last_known_balance: Optional[float] = None
        
        self._lock = threading.Lock()
        
        logger.info(
            f"✅ Kill Switch Auto-Trigger initialized: "
            f"max_daily_loss={self.max_daily_loss_pct}%, "
            f"max_consecutive_losses={self.max_consecutive_losses}, "
            f"enabled={self.enable_auto_trigger}"
        )
    
    def _should_reset_daily_metrics(self) -> bool:
        """Check if daily metrics should reset"""
        if self._daily_start_time is None:
            return True
        
        # Reset if new day
        now = datetime.utcnow()
        return now.date() > self._daily_start_time.date()
    
    def check_daily_loss(self, current_balance: float) -> Optional[str]:
        """
        Check if daily loss exceeds threshold.
        
        Args:
            current_balance: Current account balance
        
        Returns:
            Optional[str]: Trigger reason if threshold exceeded
        """
        with self._lock:
            # Initialize or reset if new day
            if self._should_reset_daily_metrics():
                self._daily_starting_balance = current_balance
                self._daily_start_time = datetime.utcnow()
                logger.debug(f"📊 Daily metrics reset: starting balance ${current_balance:.2f}")
                return None
            
            # Calculate daily P&L
            if self._daily_starting_balance is None:
                return None
            
            daily_pnl = current_balance - self._daily_starting_balance
            daily_pnl_pct = (daily_pnl / self._daily_starting_balance) * 100
            
            # Check if loss exceeds threshold
            if daily_pnl_pct <= -self.max_daily_loss_pct:
                reason = (
                    f"Daily loss limit exceeded: {daily_pnl_pct:.2f}% "
                    f"(max: -{self.max_daily_loss_pct:.0f}%) - "
                    f"Lost ${abs(daily_pnl):.2f} of ${self._daily_starting_balance:.2f}"
                )
                logger.critical(f"🚨 {reason}")
                return reason
            
            return None
    
    def record_trade_result(self, is_winner: bool) -> Optional[str]:
        """
        Record trade result and check consecutive losses.
        
        Args:
            is_winner: True if trade was profitable, False if loss
        
        Returns:
            Optional[str]: Trigger reason if threshold exceeded
        """
        with self._lock:
            if is_winner:
                self._consecutive_losses = 0
                return None
            
            # Increment consecutive losses
            self._consecutive_losses += 1
            
            logger.warning(
                f"📉 Consecutive losses: {self._consecutive_losses} "
                f"(max: {self.max_consecutive_losses})"
            )
            
            # Check threshold
            if self._consecutive_losses >= self.max_consecutive_losses:
                reason = (
                    f"Consecutive loss limit exceeded: "
                    f"{self._consecutive_losses} losses in a row "
                    f"(max: {self.max_consecutive_losses})"
                )
                logger.critical(f"🚨 {reason}")
                return reason
            
            return None
    
    def record_api_error(self) -> Optional[str]:
        """
        Record API error and check threshold.
        
        Returns:
            Optional[str]: Trigger reason if threshold exceeded
        """
        with self._lock:
            self._consecutive_api_errors += 1
            
            logger.warning(
                f"⚠️ Consecutive API errors: {self._consecutive_api_errors} "
                f"(max: {self.max_consecutive_api_errors})"
            )
            
            # Check threshold
            if self._consecutive_api_errors >= self.max_consecutive_api_errors:
                reason = (
                    f"API instability detected: "
                    f"{self._consecutive_api_errors} consecutive errors "
                    f"(max: {self.max_consecutive_api_errors})"
                )
                logger.critical(f"🚨 {reason}")
                return reason
            
            return None
    
    def record_api_success(self):
        """Record successful API call (resets error counter)"""
        with self._lock:
            if self._consecutive_api_errors > 0:
                logger.debug(f"✅ API success - resetting error counter from {self._consecutive_api_errors}")
                self._consecutive_api_errors = 0
    
    def check_balance_delta(self, current_balance: float) -> Optional[str]:
        """
        Check for unexpected balance changes.
        
        Args:
            current_balance: Current account balance
        
        Returns:
            Optional[str]: Trigger reason if unexpected delta detected
        """
        with self._lock:
            # Initialize if first check
            if self._last_known_balance is None:
                self._last_known_balance = current_balance
                return None
            
            # Calculate change
            delta = current_balance - self._last_known_balance
            delta_pct = (delta / self._last_known_balance) * 100 if self._last_known_balance > 0 else 0
            
            # Check for large unexpected change (both directions)
            if abs(delta_pct) > self.max_balance_delta_pct:
                reason = (
                    f"Unexpected balance delta: {delta_pct:+.2f}% "
                    f"(${self._last_known_balance:.2f} → ${current_balance:.2f}). "
                    f"Possible hack, API error, or unauthorized access."
                )
                logger.critical(f"🚨 {reason}")
                return reason
            
            # Update last known balance
            self._last_known_balance = current_balance
            return None
    
    def check_all_triggers(
        self,
        current_balance: float,
        last_trade_result: Optional[bool] = None
    ) -> Optional[str]:
        """
        Check all auto-trigger conditions.
        
        Args:
            current_balance: Current account balance
            last_trade_result: True if last trade won, False if lost, None to skip
        
        Returns:
            Optional[str]: First trigger reason found, or None
        """
        if not self.enable_auto_trigger:
            return None
        
        # Check daily loss
        reason = self.check_daily_loss(current_balance)
        if reason:
            return reason
        
        # Check balance delta
        reason = self.check_balance_delta(current_balance)
        if reason:
            return reason
        
        # Check consecutive losses
        if last_trade_result is not None:
            reason = self.record_trade_result(last_trade_result)
            if reason:
                return reason
        
        return None
    
    def auto_trigger_if_needed(
        self,
        current_balance: float,
        last_trade_result: Optional[bool] = None
    ) -> bool:
        """
        Check conditions and auto-trigger kill switch if needed.
        
        Args:
            current_balance: Current account balance
            last_trade_result: True if last trade won, False if lost, None to skip
        
        Returns:
            bool: True if kill switch was triggered
        """
        reason = self.check_all_triggers(current_balance, last_trade_result)
        
        if reason:
            kill_switch = get_kill_switch()
            kill_switch.activate(reason, "AUTO_TRIGGER")
            return True
        
        return False
    
    def reset_metrics(self):
        """Reset all tracking metrics"""
        with self._lock:
            self._daily_starting_balance = None
            self._daily_start_time = None
            self._consecutive_losses = 0
            self._consecutive_api_errors = 0
            self._last_known_balance = None
            logger.info("🔄 Auto-trigger metrics reset")


# Global auto-trigger instance
_auto_trigger: Optional[KillSwitchAutoTrigger] = None


def get_auto_trigger(
    max_daily_loss_pct: float = 10.0,
    max_consecutive_losses: int = 5,
    enable_auto_trigger: bool = True
) -> KillSwitchAutoTrigger:
    """Get or create the global auto-trigger instance"""
    global _auto_trigger
    
    with _instance_lock:
        if _auto_trigger is None:
            _auto_trigger = KillSwitchAutoTrigger(
                max_daily_loss_pct=max_daily_loss_pct,
                max_consecutive_losses=max_consecutive_losses,
                enable_auto_trigger=enable_auto_trigger
            )
        return _auto_trigger
            

# Global singleton instance
_kill_switch: Optional[KillSwitch] = None
_instance_lock = threading.Lock()


def get_kill_switch() -> KillSwitch:
    """Get the global kill switch instance (singleton)"""
    global _kill_switch
    
    if _kill_switch is None:
        with _instance_lock:
            if _kill_switch is None:
                _kill_switch = KillSwitch()
                
    return _kill_switch


def check_kill_switch():
    """
    Convenience function to check kill switch.
    Raises RuntimeError if active.
    
    Usage:
        check_kill_switch()  # Raises if active
        execute_trade()
    """
    get_kill_switch().assert_not_active()


def require_kill_switch_inactive(func):
    """
    Decorator to ensure kill switch is not active.
    
    Usage:
        @require_kill_switch_inactive
        def place_order():
            ...
    """
    def wrapper(*args, **kwargs):
        check_kill_switch()
        return func(*args, **kwargs)
    return wrapper


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test kill switch
    ks = get_kill_switch()
    
    print("\n=== Kill Switch Test ===")
    print(f"Initial state - Active: {ks.is_active()}")
    
    # Test activation
    print("\n--- Testing activation ---")
    ks.activate("Test activation", "TEST")
    print(f"After activation - Active: {ks.is_active()}")
    
    # Test assertion
    print("\n--- Testing assertion ---")
    try:
        ks.assert_not_active("test operation")
    except RuntimeError as e:
        print(f"Caught expected error: {e}")
        
    # Test status
    print("\n--- Kill switch status ---")
    status = ks.get_status()
    for key, value in status.items():
        print(f"  {key}: {value}")
        
    # Test deactivation
    print("\n--- Testing deactivation ---")
    ks.deactivate("Test complete")
    print(f"After deactivation - Active: {ks.is_active()}")
    
    # Now operation should work
    print("\n--- Testing operation after deactivation ---")
    try:
        ks.assert_not_active("test operation")
        print("✅ Operation allowed")
    except RuntimeError as e:
        print(f"❌ Unexpected error: {e}")
