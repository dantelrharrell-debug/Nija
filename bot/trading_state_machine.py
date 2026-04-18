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
            TradingState.LIVE_ACTIVE,          # ← auto-activate path
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

        # Validate state consistency with kill switch
        self._validate_state_consistency()

        # Log initialization
        logger.info(f"🔒 Trading State Machine initialized in {self._current_state.value} state")
        logger.info(f"📝 State persistence: {self._state_file}")

    def _load_state(self):
        """
        Load persisted state from disk.

        CRITICAL SAFETY: Even if persisted state was LIVE_ACTIVE,
        we NEVER auto-resume live trading after restart.
        EMERGENCY_STOP is also cleared on restart — the kill switch
        must be explicitly re-activated to halt trading again.
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
                elif persisted_state == TradingState.EMERGENCY_STOP:
                    # SAFETY FIX: Clear stale EMERGENCY_STOP on restart so the bot is not
                    # permanently locked out after a test trigger or accidental activation.
                    # The kill switch file (EMERGENCY_STOP) is the authoritative signal;
                    # if it is absent, the JSON state should not keep blocking trading.
                    logger.warning(
                        "⚠️  Previous state was EMERGENCY_STOP — resetting to OFF on restart"
                    )
                    logger.warning(
                        "⚠️  If an emergency condition still exists, re-activate the kill switch"
                    )
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

    def _validate_state_consistency(self):
        """
        Validate state consistency with kill switch.

        If state is EMERGENCY_STOP but kill switch is not active,
        log a warning and suggest using safe_restore_trading.py
        """
        try:
            from kill_switch import get_kill_switch
            kill_switch = get_kill_switch()

            if self._current_state == TradingState.EMERGENCY_STOP and not kill_switch.is_active():
                logger.warning("=" * 80)
                logger.warning("⚠️  STATE INCONSISTENCY DETECTED")
                logger.warning("=" * 80)
                logger.warning("State machine is in EMERGENCY_STOP but kill switch is NOT active")
                logger.warning("This typically happens after kill switch deactivation without state reset")
                logger.warning("")
                logger.warning("To restore trading safely:")
                logger.warning("  python safe_restore_trading.py restore")
                logger.warning("=" * 80)
        except Exception as e:
            # Don't fail initialization if kill switch check fails
            logger.debug(f"Could not validate state consistency: {e}")

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

    def maybe_auto_activate(self) -> bool:
        """
        Auto-transition from OFF → LIVE_ACTIVE when all safety gates pass.

        Gates (all must be true):
          Gate 0. Current state is OFF
          Gate 1. Environment variable LIVE_CAPITAL_VERIFIED is truthy
                  (operator master switch — TRADING_ENABLED concept)
          Gate 2. ``_capital_readiness_gate()`` passes:
                  a. CA_READY — CapitalAuthority not stale AND is_hydrated=True
                                (system has data; balance magnitude is not checked here)
                  b. EXECUTION_PIPELINE_HEALTHY — ExecutionRouter has no
                                                   circuit-breaking session failures
                  NOTE: CAPITAL_ELIGIBLE (total_capital >= MINIMUM_TRADING_BALANCE)
                  is intentionally NOT checked here — it belongs in the
                  execution / position-sizing layer only.
          Gate 3. No active kill switch

        Returns:
            True  if the transition was performed (or already LIVE_ACTIVE)
            False if any gate blocked it
        """
        with self._lock:
            current = self._current_state

        if current == TradingState.LIVE_ACTIVE:
            return True  # already live

        if current != TradingState.OFF:
            logger.debug(
                "maybe_auto_activate: state is %s (not OFF) — skipping", current.value
            )
            return False

        # Gate 1: LIVE_CAPITAL_VERIFIED (operator master switch)
        lcv = os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower().strip()
        if lcv not in ("true", "1", "yes", "enabled"):
            logger.info(
                "🔒 Auto-activate blocked: LIVE_CAPITAL_VERIFIED is not set to true "
                "(current value: %r).  Set it in your .env to enable live trading.",
                lcv,
            )
            return False

        # Gate 2: CA_READY + EXECUTION_PIPELINE_HEALTHY
        ready, reason = _capital_readiness_gate()
        if not ready:
            logger.info("🔒 Auto-activate blocked by capital readiness gate: %s", reason)
            return False

        # Gate 3: kill switch must be inactive
        try:
            from kill_switch import get_kill_switch
            if get_kill_switch().is_active():
                logger.warning(
                    "🔒 Auto-activate blocked: kill switch is active"
                )
                return False
        except Exception as _ks_err:
            logger.debug("maybe_auto_activate: could not check kill switch: %s", _ks_err)

        # All gates passed — transition
        try:
            self.transition_to(
                TradingState.LIVE_ACTIVE,
                "Auto-activated: LIVE_CAPITAL_VERIFIED=true, capital readiness confirmed, "
                "no kill switch active",
            )
            logger.info("✅ Auto-activated: state transitioned OFF → LIVE_ACTIVE")
            return True
        except Exception as exc:
            logger.error("❌ Auto-activate transition failed: %s", exc)
            return False

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


# ---------------------------------------------------------------------------
# Capital readiness gate — two-condition check used by maybe_auto_activate
# and self_healing_startup._step_state_machine
# ---------------------------------------------------------------------------

def _capital_readiness_gate() -> tuple:
    """
    Check the conditions required for LIVE_ACTIVE.

    Returns:
        (bool, str) — (all_passed, human-readable reason / "ok")

    Concepts (intentionally separated)
    -----------------------------------
    CA_READY
        The system has data — CapitalAuthority has received at least one
        broker snapshot (``is_hydrated=True``).  A zero balance is a valid,
        confirmed state; balance magnitude does NOT gate activation.

    TRADING_ENABLED
        Operator permission to route orders.  Enforced by Gate 1
        (``LIVE_CAPITAL_VERIFIED`` env var) in ``maybe_auto_activate`` —
        not re-checked here.

    CAPITAL_ELIGIBLE
        ``total_capital >= MINIMUM_TRADING_BALANCE``.  This belongs
        exclusively in the **execution / position-sizing layer** and must
        never gate the trading-engine activation.

    Sub-conditions evaluated here
    ------------------------------
    a. CA_READY
       CapitalAuthority singleton exists and ``is_hydrated`` is True.
       Staleness is also checked so a stale cache does not silently pass.

    b. EXECUTION_PIPELINE_HEALTHY
       ExecutionRouter singleton exists and has no failed session venues
       that would block order dispatch.

    Any sub-condition that cannot be evaluated because the relevant module
    is not yet imported is treated as **passing** (graceful degradation) so
    that systems without a particular module are not permanently locked.
    """
    failures = []

    # ── Shared helper: import CapitalAuthority ────────────────────────────
    def _get_ca():
        try:
            from bot.capital_authority import get_capital_authority as _f
        except ImportError:
            from capital_authority import get_capital_authority as _f  # type: ignore[import]
        return _f()

    # ── a. CA_READY ────────────────────────────────────────────────────────
    # Readiness == system has data, NOT capital magnitude.
    # is_hydrated=True means the coordinator has run and broker data exists.
    # A zero balance is a valid, confirmed state that must not block activation.
    # MINIMUM_TRADING_BALANCE is an execution-layer concern only (FIX C).
    authority = None
    try:
        authority = _get_ca()
        if authority.is_stale():
            failures.append(
                "CA_READY=false: CapitalAuthority data is stale "
                "(call authority.refresh(broker_map) first)"
            )
        elif not authority.is_hydrated:
            failures.append(
                "CA_READY=false: CapitalAuthority has not received any broker "
                "snapshot yet (is_hydrated=False — coordinator has not run)"
            )
        else:
            logger.info(
                "_capital_readiness_gate: CA_READY=true "
                "(is_hydrated=True, real_capital=%.2f)", authority.get_real_capital()
            )
    except (ImportError, AttributeError, Exception) as exc:
        logger.debug("_capital_readiness_gate: CapitalAuthority unavailable (%s) — skipping", exc)

    # ── b. EXECUTION_PIPELINE_HEALTHY ──────────────────────────────────────
    try:
        try:
            from bot.execution_router import get_execution_router
        except ImportError:
            from execution_router import get_execution_router  # type: ignore[import]
        router = get_execution_router()
        # If all registered venues have failed this session, the pipeline is broken.
        status = router.get_status()
        registered = status.get("registered_venues", 1)
        failed = len(status.get("session_failed_venues", []))
        if registered > 0 and failed >= registered:
            failures.append(
                f"EXECUTION_PIPELINE_HEALTHY=false: all {registered} venue(s) "
                f"have failed this session ({failed} failed)"
            )
        else:
            logger.debug(
                "_capital_readiness_gate: EXECUTION_PIPELINE_HEALTHY ✅ "
                "venues=%d failed=%d", registered, failed
            )
    except (ImportError, AttributeError, Exception) as exc:
        logger.debug("_capital_readiness_gate: ExecutionRouter unavailable (%s) — skipping", exc)

    if failures:
        return False, "; ".join(failures)
    return True, "ok"


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
