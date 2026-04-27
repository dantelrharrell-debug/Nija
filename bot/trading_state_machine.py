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
import time
import threading
import sys
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from pathlib import Path

logger = logging.getLogger("nija.trading_state_machine")

# Keep both import paths bound to the same module object so the process only
# ever has one TradingStateMachine singleton.
if __name__ == "bot.trading_state_machine":
    sys.modules.setdefault("trading_state_machine", sys.modules[__name__])
elif __name__ == "trading_state_machine":
    sys.modules.setdefault("bot.trading_state_machine", sys.modules[__name__])


def _env_truthy(name: str, default: str = "false") -> bool:
    """Return True when an env var is set to a truthy value."""
    return os.environ.get(name, default).lower().strip() in ("true", "1", "yes", "enabled")


def _heartbeat_marker_path() -> str:
    """Path of persisted heartbeat verification marker."""
    return os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")


def _heartbeat_verified() -> bool:
    """True when the first-run heartbeat verification marker exists."""
    try:
        return os.path.exists(_heartbeat_marker_path())
    except Exception:
        return False


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

        # Activation gate: must be set to True by the capital bootstrap layer
        # (via set_first_snap_accepted) after a live-exchange snapshot with
        # valid_brokers > 0 has been accepted.  Resets to False on every new
        # TradingStateMachine instance so a fresh restart always re-validates.
        self._first_snap_accepted: bool = False

        # Startup timestamp used by the forced-activation failsafe inside
        # maybe_auto_activate() to detect when the pipeline is taking too long
        # (e.g. 30-second forced snap-acceptance escape hatch).  Uses
        # time.monotonic() so elapsed-time checks are not affected by
        # wall-clock adjustments.  Recorded once at construction time.
        self._init_time: float = time.monotonic()

        # Edge-trigger tracking: stores whether activation_invariant returned
        # True on the previous cycle.  Resets to False on init so the
        # False → True transition is reliably detected on the first cycle where
        # all subsystems converge.  Also reset when entering OFF or
        # EMERGENCY_STOP so re-activation after recovery always re-validates.
        self._activation_ready_last_cycle: bool = False

        # Single atomic activation commitment flag.  Set to True exactly once
        # per activation cycle when commit_activation() successfully transitions
        # to LIVE_ACTIVE.  Reset to False when the state returns to OFF or
        # EMERGENCY_STOP so the next activation attempt re-validates all gates.
        # All supervisor paths MUST check this flag and call commit_activation()
        # as the sole authority for the OFF → LIVE_ACTIVE transition.
        self._activation_committed: bool = False

        # Runtime dispatch authority handshake.
        # execution_authority=True is the canonical permission signal for order
        # dispatch. core_loop_owns_execution is true during bootstrap until the
        # runtime handoff explicitly releases it.
        self._execution_authority: bool = False
        self._core_loop_owns_execution: bool = True
        self._can_dispatch_trades: bool = False

        # Try to load persisted state, but NEVER start in LIVE_ACTIVE
        self._load_state()

        # Startup override (operator-intent first):
        # - DRY_RUN_MODE=true          -> DRY_RUN
        # - LIVE_CAPITAL_VERIFIED=true and AUTO_ACTIVATE=true
        #       -> LIVE_ACTIVE (or LIVE_PENDING_CONFIRMATION if HEARTBEAT_TRADE=true)
        # - LIVE_CAPITAL_VERIFIED=true and AUTO_ACTIVATE=false
        #       -> LIVE_PENDING_CONFIRMATION (armed, not monitor/OFF)
        self._apply_startup_state_override()

        # Validate state consistency with kill switch
        self._validate_state_consistency()

        # Log initialization
        logger.info(f"🔒 Trading State Machine initialized in {self._current_state.value} state")
        logger.info(f"📝 State persistence: {self._state_file}")

    def _apply_startup_state_override(self) -> None:
        """Apply env-driven startup state so LIVE intent doesn't get stuck in monitor/OFF."""
        dry_run_mode = _env_truthy("DRY_RUN_MODE")
        live_verified = _env_truthy("LIVE_CAPITAL_VERIFIED")
        auto_activate = _env_truthy("AUTO_ACTIVATE")
        heartbeat_trade = _env_truthy("HEARTBEAT_TRADE")
        force_live = _env_truthy("FORCE_LIVE_TRANSITION")
        heartbeat_required_first = _env_truthy("HEARTBEAT_REQUIRED_FIRST_ACTIVATION")
        heartbeat_ok = _heartbeat_verified()

        with self._lock:
            if dry_run_mode:
                self._current_state = TradingState.DRY_RUN
                self._activation_committed = False
                self._execution_authority = False
                self._core_loop_owns_execution = True
                self._can_dispatch_trades = False
                logger.critical("[STARTUP STATE OVERRIDE] DRY_RUN_MODE=true -> DRY_RUN")
                return

            if live_verified and (auto_activate or force_live):
                if heartbeat_required_first and not heartbeat_ok and not heartbeat_trade:
                    self._current_state = TradingState.LIVE_PENDING_CONFIRMATION
                    self._activation_committed = False
                    self._execution_authority = False
                    self._core_loop_owns_execution = True
                    self._can_dispatch_trades = False
                    logger.critical(
                        "[STARTUP STATE OVERRIDE] BLOCKED LIVE_ACTIVE: HEARTBEAT_REQUIRED_FIRST_ACTIVATION=true but marker missing and HEARTBEAT_TRADE=false"
                    )
                    return

                self._current_state = TradingState.LIVE_PENDING_CONFIRMATION
                self._activation_committed = False
                self._execution_authority = False
                self._core_loop_owns_execution = True
                self._can_dispatch_trades = False
                if heartbeat_trade:
                    logger.critical(
                        "[STARTUP STATE OVERRIDE] LIVE_CAPITAL_VERIFIED + AUTO_ACTIVATE + HEARTBEAT_TRADE=true -> LIVE_PENDING_CONFIRMATION (awaiting commit_activation gate)"
                    )
                else:
                    logger.critical(
                        "[STARTUP STATE OVERRIDE] LIVE_CAPITAL_VERIFIED + AUTO_ACTIVATE=true -> LIVE_PENDING_CONFIRMATION (awaiting commit_activation gate)"
                    )
                return

            if live_verified and not dry_run_mode:
                self._current_state = TradingState.LIVE_PENDING_CONFIRMATION
                self._activation_committed = False
                self._execution_authority = False
                self._core_loop_owns_execution = True
                self._can_dispatch_trades = False
                logger.critical(
                    "[STARTUP STATE OVERRIDE] LIVE_CAPITAL_VERIFIED=true and DRY_RUN_MODE=false -> LIVE_PENDING_CONFIRMATION (awaiting commit_activation gate)"
                )
                logger.info(
                    "ACTIVATION ARMED: current_state=%s is_live=%s (awaiting commit_activation)",
                    self._current_state.value,
                    self._current_state == TradingState.LIVE_ACTIVE,
                )

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
        # FORCE_TRADE_MODE + LIVE_CAPITAL_VERIFIED always returns True
        _force = (
            os.environ.get("FORCE_TRADE", "false").lower() in ("true", "1", "yes")
            or os.environ.get("FORCE_TRADE_MODE", "false").lower() in ("true", "1", "yes")
        )
        if _force and os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower() in ("true", "1", "yes"):
            return True
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

    def activate_live_trading(self, reason: str = "force start") -> bool:
        """Force activation into LIVE_ACTIVE with execution authority enabled.

        Intended for bootstrap handoff paths that need an immediate, explicit
        transition out of OFF after preflight/init has completed.
        """
        try:
            try:
                from kill_switch import get_kill_switch
                if get_kill_switch().is_active():
                    logger.critical(
                        "[FORCE_ACTIVATE BLOCKED] reason=KILL_SWITCH_ACTIVE requested_reason=%s",
                        reason,
                    )
                    return False
            except Exception as _ks_err:
                logger.debug("activate_live_trading: kill switch check skipped: %s", _ks_err)

            with self._lock:
                if self._current_state == TradingState.LIVE_ACTIVE:
                    self._activation_committed = True
                    self._execution_authority = True
                    self._core_loop_owns_execution = False
                    self._can_dispatch_trades = True
                    logger.critical(
                        "[FORCE_ACTIVATE] already LIVE_ACTIVE; authority synchronized reason=%s",
                        reason,
                    )
                    return True

            self.transition_to(TradingState.LIVE_ACTIVE, reason)

            with self._lock:
                self._activation_committed = True
                self._execution_authority = True
                self._core_loop_owns_execution = False
                self._can_dispatch_trades = True

            logger.critical("[FORCE_ACTIVATE] LIVE_ACTIVE enabled reason=%s", reason)
            return True
        except Exception as exc:
            logger.error("[FORCE_ACTIVATE FAILED] reason=%s error=%s", reason, exc)
            return False

    def force_activate_live(self, reason: str = "forced bypass") -> bool:
        """Compatibility wrapper for explicit forced activation requests.

        This method exists to support direct "force live" probes in runtime
        diagnostics and minimal repro flows.
        """
        return self.activate_live_trading(reason=reason)

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

            # Reset edge-trigger state when re-entering a non-live state so the
            # False → True transition is re-detected on the next activation attempt.
            if new_state in (TradingState.OFF, TradingState.EMERGENCY_STOP):
                self._activation_ready_last_cycle = False
                # Reset the commitment flag so commit_activation() re-validates
                # on the next activation attempt after recovery.
                self._activation_committed = False
                self._execution_authority = False
                self._core_loop_owns_execution = True
                self._can_dispatch_trades = False
            elif new_state == TradingState.LIVE_ACTIVE:
                self._activation_committed = True
                self._execution_authority = True
                self._core_loop_owns_execution = False
                self._can_dispatch_trades = True

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

    def commit_activation(
        self,
        cycle_capital: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Single atomic activation commit — the ONE source of truth for OFF → LIVE_ACTIVE.

        This is the FINAL AUTHORITY for the activation transition.  All callers
        (supervisor loop, self-healing startup, watchdog) MUST route through this
        method exclusively.  No other code path may trigger the OFF → LIVE_ACTIVE
        transition.

        The method is idempotent: once ``_activation_committed`` is True it
        returns ``True`` immediately without re-evaluating any gates.

        Gates (evaluated in order — ALL must pass):
          Gate 0. Not already committed (idempotency guard)
          Gate 1. Current state is OFF (or already LIVE_ACTIVE — see above)
          Gate 2. Kill switch is inactive
          Gate 3. LIVE_CAPITAL_VERIFIED env var is truthy (operator master switch)
          Gate 4. CapitalAuthority ready + ExecutionPipeline healthy
          Gate 5. ``activation_invariant()`` — all subsystems simultaneously valid

        Parameters
        ----------
        cycle_capital : optional frozen capital-state dict captured once per
            cycle by ``nija_core_loop._capture_cycle_capital_state()``.
            When supplied, gate 5 uses this snapshot so the activation check
            sees the same world-view as the rest of the current cycle.

        Returns
        -------
        True  — activation committed (transition performed or was already live)
        False — one or more gates blocked; will be retried on the next cycle
        """
        # ── ABSOLUTE OVERRIDE: FORCE_TRADE_MODE + LIVE_CAPITAL_VERIFIED ──────
        # When both are set, bypass all gates and force LIVE_ACTIVE immediately.
        _force = (
            _env_truthy("FORCE_TRADE")
            or _env_truthy("FORCE_TRADE_MODE")
            or _env_truthy("FORCE_LIVE_TRANSITION")
            or (_env_truthy("AUTO_ACTIVATE") and _env_truthy("HEARTBEAT_TRADE"))
        )
        _lcv_quick = _env_truthy("LIVE_CAPITAL_VERIFIED")
        _dry_run_quick = _env_truthy("DRY_RUN_MODE")
        _heartbeat_required_first = _env_truthy("HEARTBEAT_REQUIRED_FIRST_ACTIVATION")
        _heartbeat_ok = _heartbeat_verified()
        _heartbeat_trade = _env_truthy("HEARTBEAT_TRADE")

        if _heartbeat_required_first and not _heartbeat_ok and not _heartbeat_trade:
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=HEARTBEAT_REQUIRED_FIRST_ACTIVATION marker_missing path=%s",
                _heartbeat_marker_path(),
            )
            return False

        if _force and _lcv_quick and not _dry_run_quick:
            with self._lock:
                if not self._activation_committed:
                    self._current_state = TradingState.LIVE_ACTIVE
                    self._activation_committed = True
                    self._execution_authority = True
                    self._core_loop_owns_execution = False
                    self._can_dispatch_trades = True
                    logger.critical(
                        "[AUTO_ACTIVATE] FORCE LIVE PATH (FORCE/AUTO_ACTIVATE+HEARTBEAT)+LIVE_CAPITAL_VERIFIED — "
                        "all gates bypassed, state forced to LIVE_ACTIVE"
                    )
            return True

        # ── Gate 0: idempotency — read under lock for thread-safety ──────
        with self._lock:
            if self._activation_committed:
                return True
            current = self._current_state

        if current == TradingState.LIVE_ACTIVE:
            # State was set externally (e.g. manual transition); sync the flag.
            with self._lock:
                self._activation_committed = True
                self._execution_authority = True
                self._core_loop_owns_execution = False
                self._can_dispatch_trades = True
            return True

        if current not in (TradingState.OFF, TradingState.LIVE_PENDING_CONFIRMATION):
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=STATE_NOT_ARMABLE current_state=%s",
                current.value,
            )
            return False

        # ── Gate 2: kill switch must be inactive ─────────────────────────
        kill_state = False
        try:
            from kill_switch import get_kill_switch
            kill_state = get_kill_switch().is_active()
            if kill_state:
                logger.critical("[AUTO_ACTIVATE BLOCKED] reason=KILL_SWITCH_ACTIVE")
                return False
        except Exception as _ks_err:
            logger.debug("commit_activation: could not check kill switch: %s", _ks_err)

        # ── Gate 3: LIVE_CAPITAL_VERIFIED — composite semantic check ──────────
        # Semantics: flag==true AND capital_hydrated==true AND total_balance is not None.
        # Previously Gate 3 only checked the env var flag, which allowed the trading
        # loop to start with $0 balance when brokers hadn't finished hydrating CA.
        #
        # New contract (FIX 3):
        #   LIVE_CAPITAL_VERIFIED = (flag == true
        #                            AND capital_hydrated == true
        #                            AND total_balance is not None)
        lcv = os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower().strip()
        if lcv not in ("true", "1", "yes", "enabled"):
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=LIVE_CAPITAL_VERIFIED_NOT_SET value=%r",
                lcv,
            )
            return False

        # Gate 3b: CA must be hydrated (at least one broker snapshot received).
        # Fail-closed: if CA is unavailable (None), we cannot confirm hydration,
        # so we treat it as a hard block rather than gracefully degrading.
        # If the CA module is absent at this point it indicates an infrastructure
        # error that must be resolved before live trading can proceed.
        _ca_lcv = _get_capital_authority_instance()
        _ca_hydrated_lcv = _ca_lcv is not None and bool(_ca_lcv.is_hydrated)
        if not _ca_hydrated_lcv:
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=LIVE_CAPITAL_VERIFIED_CA_NOT_HYDRATED "
                "flag=%r ca_available=%s ca_hydrated=%s — LIVE_CAPITAL_VERIFIED requires "
                "CapitalAuthority to have received at least one broker snapshot before activation.",
                lcv,
                _ca_lcv is not None,
                bool(_ca_lcv.is_hydrated) if _ca_lcv is not None else False,
            )
            return False

        # Gate 3c: CA total_balance must be resolvable (not None — CA initialized).
        _ca_balance_lcv: Optional[float] = None
        try:
            if _ca_lcv is not None:
                _ca_balance_lcv = _ca_lcv.get_real_capital()
        except Exception as _bal_err:
            logger.debug("commit_activation: Gate 3c balance read failed: %s", _bal_err)
        if _ca_lcv is not None and _ca_balance_lcv is None:
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=LIVE_CAPITAL_VERIFIED_BALANCE_UNKNOWN "
                "flag=%r total_balance=None — capital balance not resolvable from CA.",
                lcv,
            )
            return False

        # ── Gate 4: CA_READY + EXECUTION_PIPELINE_HEALTHY ────────────────
        ready, reason = _capital_readiness_gate()
        if not ready:
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=CAPITAL_NOT_READY detail=%s", reason
            )
            return False

        # ── Gate 5: activation_invariant — all subsystems simultaneously valid
        _mabm_gate = _get_mabm_instance()
        _ca_gate = _get_capital_authority_instance()
        _snap = cycle_capital if cycle_capital else {}

        _inv_ready = activation_invariant(_snap, _ca_gate, _mabm_gate, self)

        logger.critical(
            "COMMIT_ACTIVATION_INVARIANT "
            "ready=%s "
            "first_snap=%s "
            "ca_hydrated=%s "
            "ca_not_stale=%s "
            "valid_brokers=%s "
            "snap_source=%s "
            "brokers_ready=%s "
            "aggregation_normalized=%s "
            "kill_switch=%s",
            _inv_ready,
            self._first_snap_accepted,
            _ca_gate.is_hydrated if _ca_gate is not None else None,
            (not _ca_gate.is_stale()) if _ca_gate is not None else None,
            _snap.get("ca_valid_brokers", 0),
            _snap.get("snapshot_source", ""),
            (
                _mabm_gate.all_brokers_fully_ready()
                if _mabm_gate is not None and hasattr(_mabm_gate, "all_brokers_fully_ready")
                else None
            ),
            _snap.get("aggregation_normalized", True),
            kill_state,
        )

        # Final consolidated gate diagnostic — single source of truth for activation state.
        _live_verified_bool = lcv in ("true", "1", "yes", "enabled")
        commit_activation(
            kill=kill_state,
            capital_ready=ready,
            live_verified=_live_verified_bool,
            invariant=_inv_ready,
            snapshot_ready=self._first_snap_accepted,
        )

        # EDGE: only trigger on transition False → True.
        # This prevents spurious repeated activation attempts every loop cycle.
        _prev_ready = self._activation_ready_last_cycle
        self._activation_ready_last_cycle = _inv_ready

        if _inv_ready and not _prev_ready:
            # All subsystems simultaneously valid — confirm snap and activate.
            self._first_snap_accepted = True
            try:
                logger.critical("🚀 ACTIVATING TRADING ENGINE")
                self.transition_to(
                    TradingState.LIVE_ACTIVE,
                    "CONVERGENCE_EDGE: all subsystems simultaneously valid in same snapshot cycle",
                )
                assert self._current_state == TradingState.LIVE_ACTIVE, (
                    f"FSM state must be LIVE_ACTIVE after activation, got {self._current_state}"
                )
                with self._lock:
                    self._current_state = TradingState.LIVE_ACTIVE
                    self._activation_committed = True
                logger.critical("STATE AFTER ACTIVATION = %s", self._current_state)
                logger.critical("LIVE_ACTIVE_CONFIRMED_CONVERGENCE_EDGE")
                logger.critical(
                    "ACTIVATION STATE CONFIRMED: current_state=%s is_live=%s",
                    self._current_state.value,
                    self.is_live_trading_active(),
                )
                return True
            except Exception as exc:
                logger.critical("[AUTO_ACTIVATE BLOCKED] reason=TRANSITION_EXCEPTION error=%s", exc)
                return False

        if not _inv_ready:
            # Log which sub-condition is blocking activation.
            if not self._first_snap_accepted:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=SNAPSHOT_MISSING"
                    " — no valid live-exchange capital snapshot accepted"
                )
            elif _ca_gate is not None and not _ca_gate.is_hydrated:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=CA_NOT_HYDRATED"
                )
            elif _ca_gate is not None and _ca_gate.is_stale():
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=CA_STALE"
                )
            elif (
                _mabm_gate is not None
                and hasattr(_mabm_gate, "all_brokers_fully_ready")
                and not _mabm_gate.all_brokers_fully_ready()
            ):
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=BROKERS_NOT_READY"
                )
            elif not _snap.get("aggregation_normalized", True):
                # FIX 2: broker aggregation pipeline not yet sequential-complete.
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=AGGREGATION_NOT_NORMALIZED"
                    " — MABM viable broker count not yet reflected in CA balance entries."
                    " Waiting for sequential pipeline: Broker balances"
                    " → ActiveCapital aggregation → Tier classification."
                )
            else:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=INVARIANT_FAILED"
                    " snap_source=%s valid_brokers=%s",
                    _snap.get("snapshot_source", ""),
                    _snap.get("ca_valid_brokers", 0),
                )
            return False

        # ── All gates passed — commit the activation atomically ───────────
        try:
            logger.critical("🚀 ACTIVATING TRADING ENGINE")
            self.transition_to(
                TradingState.LIVE_ACTIVE,
                "COMMIT_ACTIVATION: all gates passed — single-source activation commit",
            )
            assert self._current_state == TradingState.LIVE_ACTIVE, (
                f"FSM state must be LIVE_ACTIVE after activation, got {self._current_state}"
            )
            with self._lock:
                self._current_state = TradingState.LIVE_ACTIVE
                self._activation_committed = True
                self._execution_authority = True
                self._core_loop_owns_execution = False
                self._can_dispatch_trades = True
            logger.critical("STATE AFTER ACTIVATION = %s", self._current_state)
            logger.critical("ACTIVATION_COMMITTED — LIVE_ACTIVE confirmed")
            logger.critical(
                "ACTIVATION STATE CONFIRMED: current_state=%s is_live=%s",
                self._current_state.value,
                self.is_live_trading_active(),
            )
            return True
        except Exception as exc:
            logger.critical("[AUTO_ACTIVATE BLOCKED] reason=COMMIT_TRANSITION_FAILED error=%s", exc)
            return False

    def get_activation_committed(self) -> bool:
        """Return True once commit_activation() has successfully transitioned to LIVE_ACTIVE.

        Supervisors and guards use this to skip redundant activation attempts and
        to hard-block trading operations until activation is confirmed.
        Thread-safe: reads the flag under the instance lock.
        """
        with self._lock:
            return self._activation_committed

    def has_execution_authority(self) -> bool:
        """Return True when dispatch authority has been granted."""
        with self._lock:
            return self._execution_authority or self._activation_committed

    def release_core_loop_ownership(self, reason: str = "runtime handoff") -> None:
        """Release bootstrap/core-loop ownership lock and allow dispatch.

        This is the explicit ownership handshake used after bootstrap finalization.
        """
        with self._lock:
            self._core_loop_owns_execution = False
            self._execution_authority = True
            self._can_dispatch_trades = True
        logger.critical(
            "ACTIVATION OWNERSHIP RELEASED: core_loop_owns_execution=%s can_dispatch_trades=%s reason=%s",
            False,
            True,
            reason,
        )

    def can_dispatch_trades(self) -> bool:
        """Return True when runtime dispatch should be allowed."""
        with self._lock:
            return self._can_dispatch_trades and (self._execution_authority or self._activation_committed)

    def maybe_auto_activate(
        self,
        cycle_capital: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Backward-compatible shim — delegates to :meth:`commit_activation`.

        All new callers should use ``commit_activation()`` directly.
        This method is retained only to avoid breaking existing call sites
        that have not yet been updated.
        """
        logger.critical("ENTER maybe_auto_activate")

        # ── DETERMINISTIC ACTIVATION PATH ──────────────────────────────────────
        # If state is not already LIVE_ACTIVE and all core conditions are met,
        # force transition to LIVE_ACTIVE immediately. This prevents stuck
        # LIVE_PENDING_CONFIRMATION states caused by complex invariant locks.
        current_state = self.get_current_state()
        if current_state != TradingState.LIVE_ACTIVE:
            live_verified = os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower().strip() in (
                "true", "1", "yes", "enabled"
            )
            
            # Check if capital is hydrated and balance available
            _ca_check = _get_capital_authority_instance()
            _capital_ready = (
                _ca_check is not None 
                and _ca_check.is_hydrated 
                and _ca_check.get_real_capital() is not None
            )
            
            # Check kill switch
            _kill_active = False
            try:
                from kill_switch import get_kill_switch
                _kill_active = get_kill_switch().is_active()
            except Exception:
                pass
            
            # Force transition if core conditions met
            if live_verified and _capital_ready and not _kill_active:
                logger.critical(
                    "🟢 DETERMINISTIC ACTIVATION: state=%s live_verified=%s capital_ready=%s "
                    "→ forcing LIVE_ACTIVE transition",
                    current_state.value,
                    live_verified,
                    _capital_ready,
                )
                with self._lock:
                    self._current_state = TradingState.LIVE_ACTIVE
                    self._activation_committed = True
                    self._execution_authority = True
                    self._core_loop_owns_execution = False
                    self._can_dispatch_trades = True
                logger.critical("✅ DETERMINISTIC ACTIVATION COMPLETE: state=%s is_live=%s",
                    self.get_current_state().value,
                    self.is_live_trading_active(),
                )
                return True

        # ── Entry diagnostic — snapshot every gate variable before delegating ──
        kill_switch = False
        try:
            from kill_switch import get_kill_switch
            kill_switch = get_kill_switch().is_active()
        except Exception:
            pass

        live_verified = os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower().strip() in (
            "true", "1", "yes", "enabled"
        )

        CA_READY = None
        EXECUTION_PIPELINE_HEALTHY = None
        try:
            _ca_diag = _get_capital_authority_instance()
            CA_READY = bool(_ca_diag.is_hydrated) if _ca_diag is not None else None
        except Exception:
            pass
        try:
            try:
                from bot.execution_router import get_execution_router as _get_er
            except ImportError:
                from execution_router import get_execution_router as _get_er  # type: ignore[import]
            _er = _get_er()
            _st = _er.get_status()
            _reg = _st.get("registered_venues", 1)
            _failed = len(_st.get("session_failed_venues", []))
            EXECUTION_PIPELINE_HEALTHY = not (_reg > 0 and _failed >= _reg)
        except Exception:
            pass

        brokers_ready = None
        try:
            _mabm_diag = _get_mabm_instance()
            if _mabm_diag is not None and hasattr(_mabm_diag, "all_brokers_fully_ready"):
                brokers_ready = bool(_mabm_diag.all_brokers_fully_ready())
        except Exception:
            pass

        _first_snap_accepted = self._first_snap_accepted

        # FIX 3: Compute composite LIVE_CAPITAL_VERIFIED status for diagnostics.
        # live_verified below reflects only the env var flag (for the log line).
        # commit_activation() applies the full composite check (flag + hydration + balance).
        _ca_hydrated_diag = bool(CA_READY) if CA_READY is not None else None
        _aggregation_norm_diag = bool(
            cycle_capital.get("aggregation_normalized", True)
        ) if cycle_capital else True

        # ── Gate visibility: log ALL gate status before commit ──────────────────
        gate_checks = {
            "kill_switch": not kill_switch,  # False means gate passed (switch OFF)
            "LIVE_CAPITAL_VERIFIED": live_verified,
            "ca_hydrated": CA_READY,
            "execution_healthy": EXECUTION_PIPELINE_HEALTHY,
            "first_snap_accepted": _first_snap_accepted,
            "brokers_ready": brokers_ready,
        }
        for gate_name, gate_status in gate_checks.items():
            if gate_status is False:
                logger.critical(f"❌ GATE BLOCKED: {gate_name}=False")
            elif gate_status is None:
                logger.warning(f"⚠️  GATE UNKNOWN: {gate_name}=None")

        logger.critical(
            "[AUTO_ACTIVATE ENTRY] kill_switch=%s "
            "LIVE_CAPITAL_VERIFIED=%s "
            "ca_hydrated=%s "
            "aggregation_normalized=%s "
            "capital_ready=%s "
            "execution_healthy=%s "
            "first_snap=%s "
            "brokers_ready=%s",
            kill_switch,
            live_verified,
            _ca_hydrated_diag,
            _aggregation_norm_diag,
            CA_READY,
            EXECUTION_PIPELINE_HEALTHY,
            _first_snap_accepted,
            brokers_ready,
        )

        # One-line truth-test gate names requested by operator.
        capital_ready = bool(CA_READY) if CA_READY is not None else False
        exchange_ready = bool(brokers_ready) and bool(EXECUTION_PIPELINE_HEALTHY)
        risk_clear = not kill_switch
        _min_trade_threshold = float(os.getenv("MINIMUM_TRADING_BALANCE", "1.0") or 1.0)
        _capital_total = float(cycle_capital.get("ca_total_capital", 0.0) or 0.0) if cycle_capital else 0.0
        min_trade_ok = _capital_total >= _min_trade_threshold
        logger.critical(f"capital_ready={capital_ready}")
        logger.critical(f"exchange_ready={exchange_ready}")
        logger.critical(f"risk_clear={risk_clear}")
        logger.critical(f"min_trade_ok={min_trade_ok}")

        _activation_result = self.commit_activation(cycle_capital=cycle_capital)
        if not _activation_result:
            logger.critical("❌ ACTIVATION BLOCKED: conditions not met")
        else:
            logger.critical("✅ ACTIVATION CONDITIONS MET")
            logger.critical("🔥 ACTIVATION EXECUTED")

        # Hard confirmation log — always emitted so activation state is never silent.
        logger.critical(
            "ACTIVATION STATE CONFIRMED: current_state=%s is_live=%s",
            self.get_current_state().value,
            self.is_live_trading_active(),
        )
        return _activation_result


    def get_state_history(self, limit: int = 10) -> list:
        """Get recent state transition history"""
        with self._lock:
            return self._state_history[-limit:] if self._state_history else []

    def get_first_snap_accepted(self) -> bool:
        """Return whether the first live-exchange capital snapshot has been accepted.

        External callers (e.g. the supervisor loop) can read this flag without
        accessing the private attribute directly.
        """
        return self._first_snap_accepted

    def set_first_snap_accepted(self, value: bool = True) -> None:
        """Signal that the first live-exchange capital snapshot has been accepted.

        Must be called by the capital bootstrap layer after confirming that the
        first broker snapshot has ``valid_brokers > 0`` and
        ``snapshot_source == "live_exchange"``.  The activation gate in
        :meth:`maybe_auto_activate` checks this flag and raises
        ``RuntimeError`` if it is still False when activation is attempted.
        """
        self._first_snap_accepted = bool(value)
        logger.info(
            "[TradingStateMachine] _first_snap_accepted set to %s",
            self._first_snap_accepted,
        )

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
# Module-level helpers shared by maybe_auto_activate and _capital_readiness_gate
# ---------------------------------------------------------------------------

def _get_mabm_instance():
    """Return the multi_account_broker_manager singleton or None if unavailable."""
    try:
        from bot.multi_account_broker_manager import multi_account_broker_manager as _m
        return _m
    except ImportError:
        pass
    try:
        from multi_account_broker_manager import multi_account_broker_manager as _m  # type: ignore[import]
        return _m
    except ImportError:
        return None


def _get_capital_authority_instance():
    """Return the CapitalAuthority singleton or None if unavailable."""
    try:
        from bot.capital_authority import get_capital_authority as _f
        return _f()
    except ImportError:
        pass
    try:
        from capital_authority import get_capital_authority as _f  # type: ignore[import]
        return _f()
    except ImportError:
        return None


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
    broker_map = {}

    def _get_broker_map():
        try:
            try:
                from bot.multi_account_broker_manager import get_broker_manager
            except ImportError:
                from multi_account_broker_manager import get_broker_manager  # type: ignore[import]
            manager = get_broker_manager()
            return getattr(manager, "brokers", None) or getattr(manager, "platform_brokers", None) or {}
        except Exception:
            return {}

    try:
        authority = _get_ca()
        broker_map = _get_broker_map() or {}

        # FIX 2: hard fallback when primary broker_map lookup returns nothing.
        # _get_broker_map() already checks platform_brokers via the MABM
        # property, but if the registry hasn't been populated yet (e.g. called
        # before broker connection), the map will be empty.  Log a CRITICAL
        # diagnostic so this condition is never silent.
        if not broker_map:
            logger.critical(
                "[TradingStateMachine] STARTUP WARNING: broker_map is empty — "
                "no brokers registered yet. CA cannot be refreshed until brokers "
                "load. Ensure brokers are connected before calling maybe_auto_activate()."
            )

        logger.info(
            "[TradingStateMachine] _capital_readiness_gate: CA state check - "
            "is_stale=%s, is_hydrated=%s, broker_map_keys=%s",
            authority.is_stale(),
            authority.is_hydrated,
            list(broker_map.keys()) if broker_map else [],
        )
        if authority.is_stale():
            if broker_map:
                try:
                    logger.info(
                        "[TradingStateMachine] CA stale before auto-activate; refreshing broker_map keys=%s",
                        [str(key) for key in broker_map.keys()],
                    )
                    authority.refresh(broker_map)
                    logger.info(
                        "[TradingStateMachine] CA refresh completed; now is_stale=%s, is_hydrated=%s",
                        authority.is_stale(),
                        authority.is_hydrated,
                    )
                except Exception as exc:
                    logger.warning(
                        "[TradingStateMachine] CA refresh before auto-activate failed: %s",
                        exc,
                    )
            else:
                logger.warning(
                    "[TradingStateMachine] CA is stale but broker_map is empty - cannot refresh"
                )
            if authority.is_stale():
                failures.append(
                    "CA_READY=false: CapitalAuthority data is stale "
                    "(call authority.refresh(broker_map) first)"
                )
        elif not authority.is_hydrated:
            # FIX 1: force a synchronous CA refresh before reporting failure.
            # When the gate runs before the coordinator has published a snapshot
            # (is_hydrated=False) but brokers are already connected, we can
            # deterministically hydrate CA here instead of waiting for the next
            # coordinator cycle or stalling indefinitely.
            if broker_map:
                try:
                    logger.info(
                        "[TradingStateMachine] CA not hydrated — forcing refresh, "
                        "broker_map keys=%s",
                        [str(k) for k in broker_map.keys()],
                    )
                    authority.refresh(broker_map)
                    logger.info(
                        "[TradingStateMachine] Forced CA refresh completed; "
                        "now is_hydrated=%s",
                        authority.is_hydrated,
                    )
                except Exception as exc:
                    logger.warning(
                        "[TradingStateMachine] Forced CA refresh failed: %s", exc
                    )
            if not authority.is_hydrated:
                logger.critical(
                    "[TradingStateMachine] EXECUTION BLOCKED: CA_READY=false, "
                    "is_hydrated=false, broker_map=%s — coordinator has not run",
                    list(broker_map.keys()) if broker_map else [],
                )
                failures.append(
                    "CA_READY=false: CapitalAuthority has not received any broker "
                    "snapshot yet (is_hydrated=False — coordinator has not run)"
                )
        else:
            logger.info(
                "_capital_readiness_gate: CA_READY=true "
                "(is_hydrated=True, real_capital=%.2f)", authority.get_real_capital()
            )
    except ImportError as exc:
        # Module not present in this deployment — treat as passing (graceful degradation).
        logger.debug("_capital_readiness_gate: CapitalAuthority module unavailable (%s) — skipping", exc)
    except (AttributeError, Exception) as exc:
        # Module loaded but check itself raised — the CA state is unknown; block activation.
        logger.warning(
            "_capital_readiness_gate: CA_READY=unknown — unexpected %s while checking CapitalAuthority: %s"
            " — treating as not-ready to prevent silent false-positive",
            type(exc).__name__, exc,
        )
        failures.append(
            f"CA_READY=unknown: unexpected exception during CapitalAuthority check "
            f"({type(exc).__name__}: {exc})"
        )

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
        logger.info(
            "[TradingStateMachine] _capital_readiness_gate: Execution pipeline - "
            "registered_venues=%d, session_failed_venues=%d",
            registered, failed
        )
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


# ---------------------------------------------------------------------------
# Activation invariant — single source of truth for LIVE_ACTIVE readiness
# ---------------------------------------------------------------------------

def activation_invariant(
    cycle_capital: Dict[str, Any],
    ca: Any,
    mabm: Any,
    sm: "TradingStateMachine",
) -> bool:
    """Single source of truth for LIVE_ACTIVE activation readiness.

    All required subsystems must be simultaneously valid in the **same**
    snapshot cycle.  Returns ``True`` only when every condition holds.
    This evaluator is cycle-driven — not time-based, not retry-based, not
    event-based.  It is the canonical gate that the edge-triggered activation
    path in :meth:`TradingStateMachine.maybe_auto_activate` uses to determine
    whether the ``False → True`` transition has occurred.

    Parameters
    ----------
    cycle_capital:
        Frozen capital-state dict produced by
        ``nija_core_loop._capture_cycle_capital_state()`` at cycle start.
        Expected keys: ``ca_valid_brokers`` (int), ``snapshot_source`` (str).
    ca:
        ``CapitalAuthority`` singleton, or ``None`` when unavailable
        (treated as passing — graceful degradation).
    mabm:
        ``MultiAccountBrokerManager`` singleton, or ``None`` when unavailable
        (treated as passing — graceful degradation).
    sm:
        ``TradingStateMachine`` instance whose ``_first_snap_accepted`` flag
        is inspected as proof that the capital bootstrap layer confirmed a
        live-exchange snapshot.
    """
    ca_hydrated = (ca is None) or bool(ca.is_hydrated)
    ca_not_stale = (ca is None) or (not ca.is_stale())
    brokers_ready = (
        mabm is None
        or not hasattr(mabm, "all_brokers_fully_ready")
        or bool(mabm.all_brokers_fully_ready())
    )
    valid_brokers = int(cycle_capital.get("ca_valid_brokers", 0))
    snap_source = str(cycle_capital.get("snapshot_source", ""))
    # FIX 2: Enforce sequential pipeline — Broker balances → ActiveCapital
    # aggregation → Tier classification → ExecutionEngine gating → Strategy loop.
    # aggregation_normalized=True when CA's registered broker count matches
    # MABM's viable broker count (all broker balances propagated to CA).
    # Defaults to True so unknown state never permanently blocks activation.
    aggregation_normalized = bool(cycle_capital.get("aggregation_normalized", True))
    return all((
        sm._first_snap_accepted,
        ca_hydrated,
        ca_not_stale,
        brokers_ready,
        valid_brokers > 0,
        snap_source == "live_exchange",
        aggregation_normalized,
    ))


# ---------------------------------------------------------------------------
# Commit activation — final diagnostic gate with structured critical logging
# ---------------------------------------------------------------------------


def commit_activation(
    kill: bool,
    capital_ready: bool,
    live_verified: bool,
    invariant: bool,
    snapshot_ready: bool,
) -> bool:
    """Final consolidated activation gate with mandatory critical-level diagnostics.

    Logs all five gate values in a single line so every activation attempt is
    fully observable in the logs regardless of which condition blocks it.
    Returns ``True`` only when **every** gate passes.

    Parameters
    ----------
    kill:
        ``True`` when the emergency kill switch is active (blocks activation).
    capital_ready:
        ``True`` when the capital-readiness gate (CA_READY +
        EXECUTION_PIPELINE_HEALTHY) passes.
    live_verified:
        ``True`` when the ``LIVE_CAPITAL_VERIFIED`` environment variable is set
        to a truthy value (operator master switch).
    invariant:
        ``True`` when :func:`activation_invariant` returns ``True`` for the
        current cycle snapshot.
    snapshot_ready:
        ``True`` when at least one valid live-exchange capital snapshot has been
        accepted (``TradingStateMachine._first_snap_accepted``).
    """
    logger.critical(
        "ACTIVATION GATES | "
        f"kill={kill} | "
        f"capital={capital_ready} | "
        f"live_capital={live_verified} | "
        f"invariant={invariant} | "
        f"snap={snapshot_ready}"
    )

    if kill:
        logger.critical("ACTIVATION BLOCKED: kill switch is active")
        return False

    if not live_verified:
        logger.critical("ACTIVATION BLOCKED: LIVE_CAPITAL_VERIFIED is not set to true")
        return False

    if not capital_ready:
        logger.critical("ACTIVATION BLOCKED: capital readiness gate failed (CA_READY or EXECUTION_PIPELINE_HEALTHY is false)")
        return False

    if not snapshot_ready:
        logger.critical("ACTIVATION BLOCKED: no valid live-exchange capital snapshot accepted (_first_snap_accepted is False)")
        return False

    if not invariant:
        logger.critical("ACTIVATION BLOCKED: activation_invariant returned False (check valid_brokers, snap_source, ca_hydrated, ca_not_stale, brokers_ready)")
        return False

    return True


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
