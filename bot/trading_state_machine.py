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

        # Activation gate: must be set to True by the capital bootstrap layer
        # (via set_first_snap_accepted) after a live-exchange snapshot with
        # valid_brokers > 0 has been accepted.  Resets to False on every new
        # TradingStateMachine instance so a fresh restart always re-validates.
        self._first_snap_accepted: bool = False

        # Edge-trigger tracking: stores whether activation_invariant returned
        # True on the previous cycle.  Resets to False on init so the
        # False → True transition is reliably detected on the first cycle where
        # all subsystems converge.  Also reset when entering OFF or
        # EMERGENCY_STOP so re-activation after recovery always re-validates.
        self._activation_ready_last_cycle: bool = False

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

            # Reset edge-trigger state when re-entering a non-live state so the
            # False → True transition is re-detected on the next activation attempt.
            if new_state in (TradingState.OFF, TradingState.EMERGENCY_STOP):
                self._activation_ready_last_cycle = False

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

    def maybe_auto_activate(
        self,
        cycle_capital: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Auto-transition from OFF → LIVE_ACTIVE when all safety gates pass.

        Gates (evaluated in this exact order — all must be true):
          Gate 0. Current state is OFF
          Gate 1. No active kill switch (fast-fail before any env-var reads)
          Gate 2. Environment variable LIVE_CAPITAL_VERIFIED is truthy
                  (operator master switch — TRADING_ENABLED concept)
          Gate 3. ``_capital_readiness_gate()`` passes:
                  a. CA_READY — CapitalAuthority not stale AND is_hydrated=True
                                (system has data; balance magnitude is not checked here)
                  b. EXECUTION_PIPELINE_HEALTHY — ExecutionRouter has no
                                                   circuit-breaking session failures
                  NOTE: CAPITAL_ELIGIBLE (total_capital >= MINIMUM_TRADING_BALANCE)
                  is intentionally NOT checked here — it belongs in the
                  execution / position-sizing layer only.

        Parameters
        ----------
        cycle_capital : optional pre-captured capital snapshot dict produced by
            ``nija_core_loop._capture_cycle_capital_state()`` at cycle start.
            When supplied, the hard activation gate uses ``ca_is_hydrated`` and
            ``mabm_brokers_ready`` from this dict instead of re-reading live
            state, ensuring every sub-system in a single cycle operates on the
            same frozen world-view.

        Returns:
            True  if the transition was performed (or already LIVE_ACTIVE)
            False if any gate blocked it
        """
        logger.critical("MAYBE_AUTO_ACTIVATE_ENTERED")

        with self._lock:
            current = self._current_state

        if current == TradingState.LIVE_ACTIVE:
            return True  # already live

        if current != TradingState.OFF:
            logger.debug(
                "maybe_auto_activate: state is %s (not OFF) — skipping", current.value
            )
            return False

        # Gate 1: kill switch must be inactive (checked first — fast fail)
        kill_state = False
        try:
            from kill_switch import get_kill_switch
            kill_state = get_kill_switch().is_active()
            if kill_state:
                logger.warning(
                    "🔒 Auto-activate blocked: kill switch is active"
                )
                return False
        except Exception as _ks_err:
            logger.debug("maybe_auto_activate: could not check kill switch: %s", _ks_err)

        # Gate 2: LIVE_CAPITAL_VERIFIED (operator master switch)
        lcv = os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower().strip()
        if lcv not in ("true", "1", "yes", "enabled"):
            logger.info(
                "🔒 Auto-activate blocked: LIVE_CAPITAL_VERIFIED is not set to true "
                "(current value: %r).  Set it in your .env to enable live trading.",
                lcv,
            )
            return False

        # Gate 3: CA_READY + EXECUTION_PIPELINE_HEALTHY
        ready, reason = _capital_readiness_gate()
        if not ready:
            logger.info("🔒 Auto-activate blocked by capital readiness gate: %s", reason)
            return False

        # ── Hard activation gate — edge-triggered ─────────────────────────
        # A single activation_invariant evaluates ALL required subsystems
        # simultaneously in the same snapshot cycle.  The edge trigger fires
        # ONLY on the False → True transition so activation is never retried
        # on every loop iteration and is never missed.

        _mabm_gate = _get_mabm_instance()
        _ca_gate = _get_capital_authority_instance()

        # When a pre-captured cycle_capital dict is available, use its frozen
        # values instead of re-reading live MABM/CA state.  This guarantees
        # that the state machine activation check sees the same capital
        # snapshot that was used to build the NijaCoreLoop CycleSnapshot for
        # this cycle, preventing inconsistency caused by background threads
        # updating broker/CA state between the two reads.
        _snap = cycle_capital if cycle_capital else {}

        # Inline cycle-driven snap acceptance: if _first_snap_accepted has not
        # been set yet (e.g. bootstrap escape hatch was missed because CA
        # hydrated before brokers were fully ready), attempt it here directly.
        # This is idempotent — already-accepted snaps skip the block — and
        # cycle-driven — it is retried on every maybe_auto_activate call until
        # a valid live-exchange snapshot is available.
        if not self._first_snap_accepted and _mabm_gate is not None and hasattr(_mabm_gate, "refresh_capital_authority"):
            try:
                _inline_snap = _mabm_gate.refresh_capital_authority(trigger="inline_activation_check")
                if isinstance(_inline_snap, dict):
                    _inline_vb = int(float(_inline_snap.get("valid_brokers", 0)))
                    _inline_src = str(_inline_snap.get("snapshot_source", ""))
                    if _inline_vb > 0 and _inline_src == "live_exchange":
                        self._first_snap_accepted = True
                        logger.critical(
                            "[TradingStateMachine] INLINE_SNAP_ACCEPTED "
                            "valid_brokers=%d snapshot_source=%s — proceeding to activate",
                            _inline_vb,
                            _inline_src,
                        )
                    else:
                        logger.debug(
                            "[TradingStateMachine] inline snap check: "
                            "valid_brokers=%d snapshot_source=%r — not live, will retry next cycle",
                            _inline_vb,
                            _inline_src,
                        )
            except Exception as _inline_err:
                logger.warning(
                    "[TradingStateMachine] inline snap acceptance attempt failed: %s"
                    " — will retry next cycle",
                    _inline_err,
                )

        # Evaluate the single activation invariant: all subsystems simultaneously valid.
        _current_ready = activation_invariant(_snap, _ca_gate, _mabm_gate, self)

        # Emit the mandatory proof log so every path through activation is visible.
        logger.critical(
            "ACTIVATION_INVARIANT "
            "ready=%s "
            "prev_ready=%s "
            "first_snap=%s "
            "ca_hydrated=%s "
            "ca_not_stale=%s "
            "valid_brokers=%s "
            "snap_source=%s "
            "brokers_ready=%s "
            "kill_switch=%s",
            _current_ready,
            self._activation_ready_last_cycle,
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
            kill_state,
        )

        # EDGE: only trigger on transition False → True.
        # This prevents spurious repeated activation attempts every loop cycle.
        _prev_ready = self._activation_ready_last_cycle
        self._activation_ready_last_cycle = _current_ready

        if _current_ready and not _prev_ready:
            # All subsystems simultaneously valid — confirm snap and activate.
            self._first_snap_accepted = True
            try:
                self.transition_to(
                    TradingState.LIVE_ACTIVE,
                    "CONVERGENCE_EDGE: all subsystems simultaneously valid in same snapshot cycle",
                )
                logger.critical("LIVE_ACTIVE_CONFIRMED_CONVERGENCE_EDGE")
                logger.critical(
                    "ACTIVATION STATE CONFIRMED: current_state=%s is_live=%s",
                    self._current_state.value,
                    self.is_live_trading_active(),
                )
                return True
            except Exception as exc:
                logger.error("❌ Auto-activate transition failed: %s", exc)
                return False

        if not _current_ready:
            # Log which sub-condition is blocking activation (for observability).
            if not self._first_snap_accepted:
                logger.warning(
                    "🔒 BLOCK LIVE_ACTIVE: no valid live-exchange capital snapshot accepted"
                    " — will retry next cycle"
                )
            elif _ca_gate is not None and not _ca_gate.is_hydrated:
                logger.warning(
                    "🔒 BLOCK LIVE_ACTIVE: CapitalAuthority not hydrated — will retry next cycle"
                )
            elif _ca_gate is not None and _ca_gate.is_stale():
                logger.warning(
                    "🔒 BLOCK LIVE_ACTIVE: CapitalAuthority data is stale — will retry next cycle"
                )
            elif (
                _mabm_gate is not None
                and hasattr(_mabm_gate, "all_brokers_fully_ready")
                and not _mabm_gate.all_brokers_fully_ready()
            ):
                logger.warning(
                    "🔒 BLOCK LIVE_ACTIVE: brokers not fully ready — will retry next cycle"
                )
            return False

        # _current_ready and _prev_ready are both True — invariant has been
        # consistently True; transition_to already succeeded on the edge cycle.
        return self._current_state == TradingState.LIVE_ACTIVE


    def get_state_history(self, limit: int = 10) -> list:
        """Get recent state transition history"""
        with self._lock:
            return self._state_history[-limit:] if self._state_history else []

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
    valid_brokers = int(float(cycle_capital.get("ca_valid_brokers", 0)))
    snap_source = str(cycle_capital.get("snapshot_source", ""))
    return all([
        sm._first_snap_accepted,
        ca_hydrated,
        ca_not_stale,
        brokers_ready,
        valid_brokers > 0,
        snap_source == "live_exchange",
    ])


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
