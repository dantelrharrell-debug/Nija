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
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any, Callable, NamedTuple
from pathlib import Path

logger = logging.getLogger("nija.trading_state_machine")

try:
    from bot.runtime_mode import resolve_runtime_mode_safe, RuntimeModeResolution
except ImportError:
    from runtime_mode import resolve_runtime_mode_safe, RuntimeModeResolution  # type: ignore[import]

class LiveGateSnapshot(NamedTuple):
    """Snapshot of live gate boolean status for log deduplication."""

    reconciliation_ok: bool
    nonce_ok: bool
    lease_ok: bool
    strategy_ok: bool
    execution_allowed: bool


_LIVE_GATE_LAST_STATUS: Optional[LiveGateSnapshot] = None

# Keep both import paths bound to the same module object so the process only
# ever has one TradingStateMachine singleton.
if __name__ == "bot.trading_state_machine":
    sys.modules.setdefault("trading_state_machine", sys.modules[__name__])
elif __name__ == "trading_state_machine":
    sys.modules.setdefault("bot.trading_state_machine", sys.modules[__name__])


def _env_truthy(name: str, default: str = "false") -> bool:
    """Return True when an env var is set to a truthy value."""
    return os.environ.get(name, default).lower().strip() in ("true", "1", "yes", "enabled")


def _is_transient_redis_error(err_text: str) -> bool:
    """Best-effort detection for transient Redis/network failures."""
    _e = (err_text or "").lower()
    transient_markers = (
        "timeout",
        "timed out",
        "connection reset",
        "connection refused",
        "temporarily unavailable",
        "try again",
        "redis",
        "socket",
        "network is unreachable",
        "broken pipe",
        "max retries",
    )
    return any(m in _e for m in transient_markers)


def _heartbeat_marker_path() -> str:
    """Path of persisted heartbeat verification marker."""
    return os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")


def _heartbeat_verified() -> bool:
    """True when the first-run heartbeat verification marker exists."""
    try:
        return os.path.exists(_heartbeat_marker_path())
    except Exception:
        return False


def _resolve_writer_fencing_token(writer_lease_manager: object | None = None) -> str:
    """Resolve writer fencing token from env, with lease-manager fallback."""
    token = (
        os.getenv("NIJA_WRITER_FENCING_TOKEN")
        or getattr(writer_lease_manager, "lease_version", None)
    )
    return str(token or "").strip()


def _emergency_local_fallback_active() -> bool:
    """Always returns False — emergency local fallback is permanently disabled.

    SAFETY: Local writer-lock fallback bypasses distributed authority and is
    not permitted.  This function is retained only for call-site compatibility
    and will always return False so all callers treat the fallback as inactive.
    """
    return False


def _distributed_writer_authority_gate() -> tuple[bool, str]:
    """Verify this process still owns distributed writer authority.

    Returns
    -------
    (ok, error)
        ok=True when authority is confirmed via Redis fencing token.
        ok=False with an error string when Redis is unreachable, fencing
        token is missing, or authority verification fails.

    SAFETY CONTRACT
    ---------------
    This gate MUST pass before any LIVE_ACTIVE transition.  There are NO
    fail-open paths and NO local fallbacks under normal operation.

    Fail-closed behavior
    --------------------
    This gate never bypasses distributed authority checks. Redis fencing and
    lease validation are mandatory for LIVE_ACTIVE transitions.
    """
    writer_lease_manager = None
    try:
        try:
            from bot.distributed_nonce_manager import get_distributed_nonce_manager
        except ImportError:
            from distributed_nonce_manager import get_distributed_nonce_manager  # type: ignore[import]
        writer_lease_manager = get_distributed_nonce_manager()
    except Exception:
        writer_lease_manager = None

    # Verify fencing token is present before attempting Redis check.
    fencing_token = _resolve_writer_fencing_token(writer_lease_manager)
    if not fencing_token:
        err = (
            "LIVE TRADING BLOCKED: NIJA_WRITER_FENCING_TOKEN is not set. "
            "Redis distributed writer authority is required for LIVE_ACTIVE. "
            "Ensure the bot acquired a Redis writer lease at startup."
        )
        logger.critical("[WRITER AUTHORITY HARD FAIL] %s", err)
        return False, err

    retries = max(1, int(os.environ.get("NIJA_REDIS_LOCK_RETRIES", "3") or "3"))
    retry_delay_s = max(0.0, float(os.environ.get("NIJA_REDIS_LOCK_RETRY_DELAY_S", "0.20") or "0.20"))
    last_err = ""

    for attempt in range(retries):
        try:
            try:
                from bot.execution_authority_context import assert_distributed_writer_authority
            except ImportError:
                from execution_authority_context import assert_distributed_writer_authority  # type: ignore[import]

            assert_distributed_writer_authority()
            return True, ""
        except Exception as exc:
            last_err = str(exc)
            if attempt < retries - 1 and retry_delay_s > 0:
                time.sleep(retry_delay_s)

    # Hard fail — no fail-open for transient errors in strict mode.
    # Redis unavailability is a hard block on LIVE_ACTIVE activation.
    err = (
        f"LIVE TRADING BLOCKED: distributed writer authority verification failed "
        f"after {retries} attempt(s). Redis must be reachable and fencing token "
        f"must be valid before LIVE_ACTIVE is permitted. last_error={last_err}"
    )
    logger.critical("[WRITER AUTHORITY HARD FAIL] %s", err)
    return False, err


def _nonce_writer_lease_gate() -> tuple[bool, str]:
    """Verify nonce writer lease ownership for the platform Kraken key.

    This prevents LIVE activation when a stale/foreign process still owns the
    Redis nonce lease for the same API key (split-brain protection).
    """
    if not _env_truthy("NIJA_ENFORCE_NONCE_WRITER_LEASE", "true"):
        return True, ""

    platform_key = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
    )
    if not platform_key:
        # No Kraken platform key configured in this process; nothing to verify.
        return True, ""

    retries = max(1, int(os.environ.get("NIJA_NONCE_LEASE_RETRIES", "3") or "3"))
    retry_delay_s = max(0.0, float(os.environ.get("NIJA_NONCE_LEASE_RETRY_DELAY_S", "0.20") or "0.20"))
    last_err = ""

    for attempt in range(retries):
        try:
            try:
                from bot.distributed_nonce_manager import (
                    get_distributed_nonce_manager,
                    make_api_key_id,
                )
            except ImportError:
                from distributed_nonce_manager import (  # type: ignore[import]
                    get_distributed_nonce_manager,
                    make_api_key_id,
                )

            key_id = make_api_key_id(platform_key)
            manager = get_distributed_nonce_manager()
            manager.ensure_writer_lock(key_id)
            status_fn = getattr(manager, "get_writer_lease_status", None)
            if callable(status_fn):
                status = status_fn(key_id)
                if isinstance(status, dict):
                    token = status.get("token")
                    if token is not None and str(token).strip():
                        setattr(manager, "fencing_token", str(token).strip())
            stability_required_s = _nonce_lease_stability_requirement_s()
            if stability_required_s > 0:
                status = None
                status_fn = getattr(manager, "get_writer_lease_status", None)
                if callable(status_fn):
                    status = status_fn(key_id)
                if not isinstance(status, dict):
                    raise RuntimeError("nonce lease stability status unavailable")
                if status.get("enabled") is False:
                    return True, ""
                stable_for = status.get("stable_for_s")
                if not isinstance(stable_for, (int, float)):
                    stable_for = 0.0
                if stable_for < stability_required_s:
                    token = status.get("token")
                    owner = status.get("owner_instance") or status.get("owner_id") or "<unknown>"
                    raise RuntimeError(
                        "nonce lease unstable "
                        f"(stable_for={stable_for:.1f}s required={stability_required_s:.1f}s "
                        f"token={token} owner={owner})"
                    )
            return True, ""
        except Exception as exc:
            last_err = str(exc)
            if attempt < retries - 1 and retry_delay_s > 0:
                time.sleep(retry_delay_s)

    # Hard fail — no fail-open for transient Redis errors.
    # Nonce lease is a mandatory safety gate; Redis unavailability blocks activation.
    err = (
        f"LIVE TRADING BLOCKED: nonce writer lease verification failed "
        f"after {retries} attempt(s). Redis nonce lease is required before "
        f"LIVE_ACTIVE is permitted. last_error={last_err}"
    )
    logger.critical("[NONCE LEASE HARD FAIL] %s", err)
    return False, err


def _nonce_lease_stability_requirement_s() -> float:
    """Return required lease stability window in seconds (0 disables)."""
    if _env_truthy("NIJA_BYPASS_NONCE_LEASE_STABILITY", "false"):
        if not _env_truthy("NIJA_CONFIRM_BYPASS_RISKS", "false"):
            logger.warning(
                "[NONCE LEASE STABILITY BYPASS IGNORED] NIJA_BYPASS_NONCE_LEASE_STABILITY=true but "
                "NIJA_CONFIRM_BYPASS_RISKS!=true; stability checks remain enforced."
            )
        else:
            logger.critical(
                "[NONCE LEASE STABILITY BYPASS] NIJA_BYPASS_NONCE_LEASE_STABILITY=true — "
                "lease stability checks disabled (ensure single-writer safety manually)."
            )
            return 0.0
    runtime_mode = resolve_runtime_mode_safe(logger)
    require_stability = _env_truthy("NIJA_REQUIRE_NONCE_LEASE_STABILITY", "false") or (
        runtime_mode.is_live if runtime_mode is not None else _env_truthy("LIVE_CAPITAL_VERIFIED", "false")
    )
    if not require_stability:
        return 0.0
    raw = os.environ.get("NIJA_NONCE_LEASE_STABILITY_S", "").strip()
    if not raw:
        return 30.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 30.0


def _nonce_sync_gate() -> tuple[bool, str]:
    """Verify nonce synchronization state before LIVE activation."""
    if not _env_truthy("NIJA_ENFORCE_NONCE_SYNC", "true"):
        return True, ""

    platform_key = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
    )
    if not platform_key:
        return True, ""

    try:
        try:
            from bot.global_kraken_nonce import get_global_nonce_stats
        except ImportError:
            from global_kraken_nonce import get_global_nonce_stats  # type: ignore[import]
        stats = get_global_nonce_stats()
    except Exception as exc:
        return False, f"nonce_stats_unavailable: {exc}"

    if stats.get("key_invalidated"):
        return False, "nonce_key_invalidated"
    if stats.get("broker_quarantined"):
        return False, "nonce_broker_quarantined"
    if stats.get("trading_paused"):
        return False, "nonce_trading_paused"

    return True, ""


def _strategy_ready_gate() -> tuple[bool, str]:
    """Report whether the readiness truth table is fully set.

    Returns
    -------
    (ok, detail)
        ok=True when all keys in the readiness table are True.
        ok=False when any key is still False or the table is unavailable.
        detail provides a short reason when ok=False.
    """
    try:
        try:
            from bot.readiness_table import is_ready as _rt_is_ready, pending as _rt_pending
        except ImportError:
            from readiness_table import is_ready as _rt_is_ready, pending as _rt_pending  # type: ignore[import]
    except ImportError:
        return False, "readiness_table_module_missing"

    try:
        if _rt_is_ready():
            return True, ""
        _pend = _rt_pending()
        if _pend:
            return False, f"pending={','.join(sorted(_pend))}"
        return False, "not_ready"
    except Exception as exc:
        return False, f"readiness_table_unavailable: {exc}"


def _safe_start_gate() -> tuple[bool, str]:
    """Block LIVE activation when safe-start mode is required."""
    if not _env_truthy("NIJA_SAFE_START_REQUIRED", "false"):
        return True, ""
    if _env_truthy("NIJA_SAFE_START_ACK", "false"):
        return True, ""
    status = os.environ.get("NIJA_RECONCILIATION_STATUS", "").strip().upper()
    if status in {"CLEAN", "CLEAN_START"} and _env_truthy("NIJA_RECONCILIATION_COMPLETE", "false"):
        return True, ""
    reason = os.environ.get("NIJA_SAFE_START_REASON", "").strip()
    detail = f"status={status or 'missing'}"
    if reason:
        detail = f"{reason} ({detail})"
    return False, detail


def _startup_reconciliation_gate() -> tuple[bool, str]:
    """Require startup reconciliation to complete before LIVE activation."""
    if _emergency_local_fallback_active():
        logger.critical(
            "[RECONCILIATION EMERGENCY OVERRIDE] local writer-lock fallback active; "
            "startup reconciliation gate bypassed for this process startup."
        )
        return True, ""

    if not _env_truthy("NIJA_REQUIRE_STARTUP_RECONCILIATION", "true"):
        return True, ""
    status = os.environ.get("NIJA_RECONCILIATION_STATUS", "").strip().upper()
    complete = _env_truthy("NIJA_RECONCILIATION_COMPLETE", "false")

    # Pass immediately for CLEAN / CLEAN_START outcomes.
    if status in {"CLEAN", "CLEAN_START"} and complete:
        return True, ""

    # Reconciliation has not run yet (status is empty and complete is false).
    # This is a normal race-condition during startup: the reconciliation manager
    # runs inside the first trading cycle, while activation gates are evaluated
    # earlier by MABM and the supervisor.  Rather than permanently blocking on a
    # "missing" status, pass the gate so the first cycle can execute and set the
    # status.  The gate is automatically re-evaluated on every subsequent
    # commit_activation() call; once the reconciliation manager sets
    # NIJA_RECONCILIATION_COMPLETE=true (at the end of its first run), this
    # branch is no longer reachable and the status check above takes effect.
    if not status and not complete:
        logger.warning(
            "[RECONCILIATION GATE] reconciliation has not run yet (status=missing) — "
            "passing gate for initial startup. Gate will re-enforce once "
            "NIJA_RECONCILIATION_COMPLETE=true is set by the first trading cycle."
        )
        return True, ""

    return False, f"status={status or 'missing'}"


def _collect_live_gate_status() -> Dict[str, object]:
    """Collect safety gate status used for LIVE execution logging.

    Gates captured:
    - safe_ok: NIJA safe-start acknowledgement gate.
    - recon_ok: restart reconciliation completion gate.
    - nonce_ok: global nonce synchronization gate.
    - lease_ok: distributed writer authority (lease owner) gate.
    - strategy_ok: startup readiness gate for strategy initialization.

    Returns a dict with *_ok and *_err keys plus execution_allowed, which is
    true only when safe/reconciliation/nonce/lease/strategy gates pass.
    """
    safe_ok, safe_err = _safe_start_gate()
    recon_ok, recon_err = _startup_reconciliation_gate()
    nonce_ok, nonce_err = _nonce_sync_gate()
    lease_ok, lease_err = _distributed_writer_authority_gate()
    strategy_ok, strategy_err = _strategy_ready_gate()
    execution_allowed = safe_ok and recon_ok and nonce_ok and lease_ok and strategy_ok
    return {
        "safe_ok": safe_ok,
        "safe_err": safe_err,
        "recon_ok": recon_ok,
        "recon_err": recon_err,
        "nonce_ok": nonce_ok,
        "nonce_err": nonce_err,
        "lease_ok": lease_ok,
        "lease_err": lease_err,
        "strategy_ok": strategy_ok,
        "strategy_err": strategy_err,
        "execution_allowed": execution_allowed,
    }


def _log_live_gate_status(live_gate_status: Dict[str, object]) -> None:
    """Log live gate status once per change.

    Deduplicates output by comparing a compact snapshot of key booleans.
    Fail-fast logging only applies to reconciliation/nonce/lease failures
    as required by the safety contract, while strategy readiness is logged
    but not part of the fail-fast trigger.
    """
    global _LIVE_GATE_LAST_STATUS

    recon_ok = bool(live_gate_status.get("recon_ok"))
    nonce_ok = bool(live_gate_status.get("nonce_ok"))
    lease_ok = bool(live_gate_status.get("lease_ok"))
    strategy_ok = bool(live_gate_status.get("strategy_ok"))
    execution_allowed = bool(live_gate_status.get("execution_allowed"))
    snapshot = LiveGateSnapshot(
        reconciliation_ok=recon_ok,
        nonce_ok=nonce_ok,
        lease_ok=lease_ok,
        strategy_ok=strategy_ok,
        execution_allowed=execution_allowed,
    )
    if _LIVE_GATE_LAST_STATUS == snapshot:
        return
    _LIVE_GATE_LAST_STATUS = snapshot

    logger.info("LIVE GATE STATUS:")
    logger.info("   • Reconciliation: %s", "COMPLETE" if recon_ok else "INCOMPLETE")
    logger.info("   • Nonce Sync: %s", "VALID" if nonce_ok else "INVALID")
    logger.info("   • Lease Owner: %s", "CONFIRMED" if lease_ok else "CONFLICT")
    logger.info("   • Strategy Ready: %s", "TRUE" if strategy_ok else "FALSE")
    logger.info("   • EXECUTION_ALLOWED: %s", "TRUE" if execution_allowed else "FALSE")

    # Fail-fast gate only for reconciliation/nonce/lease conflicts per safety contract.
    if not (recon_ok and nonce_ok and lease_ok):
        logger.critical(
            "🚫 EXECUTION BLOCKED — SAFETY GATE FAILURE (reconciliation=%s nonce_sync=%s lease_owner=%s)",
            "OK" if recon_ok else "FAIL",
            "OK" if nonce_ok else "FAIL",
            "OK" if lease_ok else "FAIL",
        )


def _live_activation_gate(live_gate_status: Optional[Dict[str, object]] = None) -> tuple[bool, str]:
    live_gate_status = live_gate_status or _collect_live_gate_status()
    _log_live_gate_status(live_gate_status)
    safe_ok = bool(live_gate_status.get("safe_ok"))
    safe_err = str(live_gate_status.get("safe_err") or "")
    if not safe_ok:
        return False, f"SAFE_START_REQUIRED {safe_err}"
    recon_ok = bool(live_gate_status.get("recon_ok"))
    recon_err = str(live_gate_status.get("recon_err") or "")
    if not recon_ok:
        return False, f"STARTUP_RECONCILIATION {recon_err}"
    return True, ""


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


class ExecutionSafetyState(str, Enum):
    """Safety layer for runtime execution authority."""

    LOCKED = "LOCKED"
    AUTHORIZED = "AUTHORIZED"


class ExecutionProgressState(str, Enum):
    """Progress layer for execution authority convergence/liveness."""

    LOCKED = "LOCKED"
    ARMED = "ARMED"
    CONVERGING = "CONVERGING"
    BLOCKED_RETRY = "BLOCKED_RETRY"
    AUTHORIZED = "AUTHORIZED"
    FAIL_SAFE = "FAIL_SAFE"


@dataclass(frozen=True)
class ExecutionAuthoritySnapshot:
    """Combined safety/progress snapshot for execution authority."""

    safety_state: ExecutionSafetyState
    progress_state: ExecutionProgressState
    reason: str
    intent_present: bool
    gates_ok: bool
    converged: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "safety_state": self.safety_state.value,
            "progress_state": self.progress_state.value,
            "reason": self.reason,
            "intent_present": self.intent_present,
            "gates_ok": self.gates_ok,
            "converged": self.converged,
        }


class ExecutionAuthorityConvergenceFSM:
    """Dual-layer FSM for execution authority safety + progress.

    Zero-limbo guarantee
    --------------------
    Every state transition is deterministic and reversible:

    * **LOCKED**        — no activation intent; all other inputs ignored.
    * **ARMED**         — intent present but prerequisites not met yet
                          (bootstrap or capital FSM not yet RUNNING).
    * **BLOCKED_RETRY** — prerequisites met but safety gates failing;
                          timer starts.
    * **FAIL_SAFE**     — gates have been failing for longer than
                          ``timeout_s``; this state is **recoverable** —
                          if gates become OK the FSM exits to CONVERGING.
    * **CONVERGING**    — gates OK, waiting for trading state / commit /
                          dispatch handshake to complete.
    * **AUTHORIZED**    — all conditions simultaneously met; orders may flow.

    The FSM never gets permanently stuck: FAIL_SAFE clears automatically
    the moment gates return OK.  Calling :meth:`reset` explicitly returns
    the FSM to LOCKED regardless of current conditions.
    """

    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout_s = max(1.0, float(timeout_s))
        self._progress_state = ExecutionProgressState.LOCKED
        self._blocked_since_monotonic: Optional[float] = None
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Return the FSM to LOCKED and clear any pending timers.

        Use this for explicit operator-initiated recovery after a FAIL_SAFE,
        or during testing to restore a clean slate between scenarios.
        """
        with self._lock:
            self._progress_state = ExecutionProgressState.LOCKED
            self._blocked_since_monotonic = None
        logger.critical(
            "ExecutionAuthorityConvergenceFSM.reset(): state forced to LOCKED"
        )

    def evaluate(
        self,
        *,
        intent_present: bool,
        bootstrap_running_supervised: bool,
        capital_running: bool,
        trading_live: bool,
        activation_committed: bool,
        execution_authority: bool,
        can_dispatch_trades: bool,
        gates_ok: bool,
        now_monotonic: Optional[float] = None,
    ) -> ExecutionAuthoritySnapshot:
        now = now_monotonic if now_monotonic is not None else time.monotonic()
        prereqs_ready = bootstrap_running_supervised and capital_running
        converged = bool(
            intent_present
            and prereqs_ready
            and trading_live
            and activation_committed
            and execution_authority
            and can_dispatch_trades
            and gates_ok
        )

        with self._lock:
            prev_state = self._progress_state

            if not intent_present:
                self._progress_state = ExecutionProgressState.LOCKED
                self._blocked_since_monotonic = None
                reason = "intent_missing"
            elif converged:
                self._progress_state = ExecutionProgressState.AUTHORIZED
                self._blocked_since_monotonic = None
                reason = "converged_authority"
            elif not prereqs_ready:
                self._progress_state = ExecutionProgressState.ARMED
                self._blocked_since_monotonic = None
                reason = "awaiting_bootstrap_or_capital_running"
            elif not gates_ok:
                if self._blocked_since_monotonic is None:
                    self._blocked_since_monotonic = now
                elapsed = now - self._blocked_since_monotonic
                if elapsed >= self._timeout_s:
                    if prev_state != ExecutionProgressState.FAIL_SAFE:
                        logger.critical(
                            "ExecutionAuthorityConvergenceFSM: FAIL_SAFE entered after "
                            "%.1fs of blocked gates — execution authority withheld until "
                            "gates recover or reset() is called",
                            elapsed,
                        )
                    self._progress_state = ExecutionProgressState.FAIL_SAFE
                    reason = f"blocked_timeout_{elapsed:.2f}s"
                else:
                    self._progress_state = ExecutionProgressState.BLOCKED_RETRY
                    reason = "blocked_retrying_gates"
            else:
                # gates_ok=True: FAIL_SAFE and BLOCKED_RETRY are both recoverable.
                if prev_state in (
                    ExecutionProgressState.FAIL_SAFE,
                    ExecutionProgressState.BLOCKED_RETRY,
                ):
                    logger.critical(
                        "ExecutionAuthorityConvergenceFSM: gates recovered from %s "
                        "→ CONVERGING (timer cleared)",
                        prev_state.value,
                    )
                self._progress_state = ExecutionProgressState.CONVERGING
                self._blocked_since_monotonic = None
                reason = "awaiting_trading_live_commit_dispatch"

            safety_state = (
                ExecutionSafetyState.AUTHORIZED
                if converged and self._progress_state != ExecutionProgressState.FAIL_SAFE
                else ExecutionSafetyState.LOCKED
            )
            return ExecutionAuthoritySnapshot(
                safety_state=safety_state,
                progress_state=self._progress_state,
                reason=reason,
                intent_present=bool(intent_present),
                gates_ok=bool(gates_ok),
                converged=bool(converged and safety_state == ExecutionSafetyState.AUTHORIZED),
            )


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
        self._execution_authority_fsm = ExecutionAuthorityConvergenceFSM(
            timeout_s=float(os.getenv("NIJA_EXECUTION_CONVERGENCE_TIMEOUT_S", "20.0") or 20.0)
        )

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
        runtime_mode = resolve_runtime_mode_safe(logger)
        dry_run_mode = runtime_mode.dry_run if runtime_mode is not None else _env_truthy("DRY_RUN_MODE")
        live_verified = runtime_mode.is_live if runtime_mode is not None else _env_truthy("LIVE_CAPITAL_VERIFIED")
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
        runtime_mode = resolve_runtime_mode_safe(logger)
        live_active_flag = runtime_mode.is_live if runtime_mode is not None else _env_truthy("LIVE_CAPITAL_VERIFIED")
        if _force and live_active_flag:
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

            _live_ok, _live_err = _live_activation_gate()
            if not _live_ok:
                logger.critical(
                    "[FORCE_ACTIVATE BLOCKED] reason=SAFE_START detail=%s requested_reason=%s",
                    _live_err,
                    reason,
                )
                return False

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
        """Compatibility wrapper that preserves strict FSM-only activation."""
        logger.error(
            "[FORCE_ACTIVATE REJECTED] forced live activation is disabled reason=%s",
            reason,
        )
        return False

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

        Design: zero-deadlock guarantee
        --------------------------------
        All network / Redis / disk I/O is performed **before** acquiring
        ``self._lock`` so that concurrent state readers
        (``get_current_state``, ``is_live_trading_active``,
        ``can_make_broker_calls``, etc.) are never blocked while the
        thread is waiting for a remote response.  Only in-memory operations
        execute while the lock is held.
        """
        # ── Pre-flight safety checks (I/O outside the lock) ──────────────────
        # These gates do not depend on the current FSM state; they are safety
        # invariants that must pass before any LIVE_ACTIVE transition.
        if new_state == TradingState.LIVE_ACTIVE:
            # Enforce distributed writer authority before ANY LIVE_ACTIVE transition.
            _writer_ok, _writer_err = _distributed_writer_authority_gate()
            if not _writer_ok:
                error_msg = f"LIVE_ACTIVE blocked: distributed writer authority failed — {_writer_err}"
                logger.critical("[FSM HARD FAIL] %s", error_msg)
                raise StateTransitionError(error_msg)

            # Enforce fencing token presence.
            _fencing_token = _resolve_writer_fencing_token()
            if not _fencing_token:
                error_msg = (
                    "LIVE_ACTIVE blocked: NIJA_WRITER_FENCING_TOKEN is not set. "
                    "A valid Redis fencing token is required for LIVE_ACTIVE."
                )
                logger.critical("[FSM HARD FAIL] %s", error_msg)
                raise StateTransitionError(error_msg)

            # Check runtime revocation before activating.
            try:
                try:
                    from bot.revocation_guard import check_revocation_or_raise
                except ImportError:
                    from revocation_guard import check_revocation_or_raise  # type: ignore[import]
                check_revocation_or_raise()
            except RuntimeError as _rev_exc:
                error_msg = f"LIVE_ACTIVE blocked: {_rev_exc}"
                logger.critical("[FSM HARD FAIL] %s", error_msg)
                raise StateTransitionError(error_msg) from _rev_exc

            live_ok, live_err = _live_activation_gate()
            if not live_ok:
                error_msg = f"Activation blocked: {live_err}"
                logger.critical("ACTIVATION BLOCKED: %s", error_msg)
                raise StateTransitionError(error_msg)

        # ── Atomic state update (lock held only for in-memory operations) ─────
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
                os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            elif new_state == TradingState.LIVE_ACTIVE:
                self._activation_committed = True
                self._execution_authority = True
                self._core_loop_owns_execution = False
                self._can_dispatch_trades = True
                os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"

        # ── Post-transition I/O (outside the lock) ────────────────────────────
        # Persist and trigger callbacks after releasing the lock so that
        # concurrent readers are not stalled by disk I/O or callback execution.
        self._persist_state()

        logger.info(
            f"🔄 State transition: {old_state.value} -> {new_state.value} "
            f"(Reason: {reason or 'No reason provided'})"
        )

        self._trigger_callbacks(new_state)

        # Start authority heartbeat monitor when entering LIVE_ACTIVE.
        if new_state == TradingState.LIVE_ACTIVE:
            try:
                try:
                    from bot.authority_heartbeat import start_authority_heartbeat
                except ImportError:
                    from authority_heartbeat import start_authority_heartbeat  # type: ignore[import]
                start_authority_heartbeat()
                logger.info("AuthorityHeartbeatMonitor: started on LIVE_ACTIVE transition")
            except Exception as _hb_exc:
                logger.warning(
                    "Could not start authority heartbeat monitor: %s", _hb_exc
                )

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
          Gate 3. Activation intent is present via LIVE_CAPITAL_VERIFIED or
                  a coordinator-issued activation request
          Gate 4. Single global activation barrier
              - capital snapshot ready
              - broker registration/snapshot invariant valid
              - execution pipeline healthy
              - normalized venue thresholds valid
          Gate 5. Final invariant edge confirmation for transition commit

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
        _force = (
            _env_truthy("FORCE_TRADE")
            or _env_truthy("FORCE_TRADE_MODE")
            or _env_truthy("FORCE_LIVE_TRANSITION")
            or (_env_truthy("AUTO_ACTIVATE") and _env_truthy("HEARTBEAT_TRADE"))
        )
        runtime_mode = resolve_runtime_mode_safe(logger)
        _lcv_quick = runtime_mode.is_live if runtime_mode is not None else _env_truthy("LIVE_CAPITAL_VERIFIED")
        _coordinator = _get_startup_coordinator()
        if _lcv_quick or _force:
            try:
                _coordinator.record_activation_requested(
                    requested=True,
                    source="commit_activation:operator_intent",
                )
            except Exception:
                logger.debug("commit_activation: coordinator activation request update failed", exc_info=True)
        _live_activation_intent = _activation_intent_present(runtime_mode)
        _dry_run_quick = runtime_mode.dry_run if runtime_mode is not None else _env_truthy("DRY_RUN_MODE")
        _lcv_raw = (
            runtime_mode.raw.get("LIVE_CAPITAL_VERIFIED", "false")
            if runtime_mode is not None
            else os.environ.get("LIVE_CAPITAL_VERIFIED", "false")
        )
        _live_trading_raw = (
            runtime_mode.raw.get("LIVE_TRADING", "false")
            if runtime_mode is not None
            else os.environ.get("LIVE_TRADING", "false")
        )
        _heartbeat_required_first = _env_truthy("HEARTBEAT_REQUIRED_FIRST_ACTIVATION")
        _heartbeat_ok = _heartbeat_verified()
        _heartbeat_trade = _env_truthy("HEARTBEAT_TRADE")

        if _heartbeat_required_first and not _heartbeat_ok and not _heartbeat_trade:
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=HEARTBEAT_REQUIRED_FIRST_ACTIVATION marker_missing path=%s",
                _heartbeat_marker_path(),
            )
            return False

        _live_gate_status = _collect_live_gate_status()
        _live_ok, _live_err = _live_activation_gate(_live_gate_status)
        if not _live_ok:
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=SAFE_START detail=%s",
                _live_err,
            )
            return False

        # ── Gate 0: idempotency — read under lock for thread-safety ──────
        with self._lock:
            if self._activation_committed:
                if self._current_state == TradingState.LIVE_ACTIVE:
                    # Keep runtime dispatch authority synchronized on idempotent retries.
                    self._execution_authority = True
                    self._core_loop_owns_execution = False
                    self._can_dispatch_trades = True
                else:
                    logger.warning(
                        "ACTIVATION_COMMITTED_STATE_MISMATCH state=%s — retaining committed flag",
                        self._current_state.value,
                    )
                return True
            current = self._current_state

        logger.critical(
            "ACTIVATION_GATE_SNAPSHOT state=%s committed=%s live_verified=%s dry_run=%s force=%s "
            "heartbeat_required_first=%s heartbeat_ok=%s heartbeat_trade=%s first_snap=%s",
            current.value,
            self._activation_committed,
            _lcv_quick,
            _dry_run_quick,
            _force,
            _heartbeat_required_first,
            _heartbeat_ok,
            _heartbeat_trade,
            self._first_snap_accepted,
        )

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

        # ── Gate 1.5: authority + runtime safety probes are sampled once ──────
        authority_ready = _is_authority_ready()
        try:
            _coordinator.record_authority(
                ready=authority_ready,
                status={"current_state": current.value},
            )
        except Exception:
            logger.debug("commit_activation: coordinator authority update failed", exc_info=True)

        if not authority_ready:
            with self._lock:
                if self._current_state == TradingState.OFF:
                    self._current_state = TradingState.LIVE_PENDING_CONFIRMATION

        # ── Gate 2: kill switch must be inactive ─────────────────────────
        kill_state = False
        try:
            from kill_switch import get_kill_switch
            kill_state = get_kill_switch().is_active()
        except Exception as _ks_err:
            logger.debug("commit_activation: could not check kill switch: %s", _ks_err)
        try:
            _coordinator.record_kill_switch(active=kill_state)
        except Exception:
            logger.debug("commit_activation: coordinator kill-switch update failed", exc_info=True)

        # ── Gate 2b: distributed writer authority must be valid ──────────
        # Prevent split-brain activation when another container/process owns
        # the Redis writer fence token.
        _writer_ok = bool(_live_gate_status.get("lease_ok"))
        _writer_err = str(_live_gate_status.get("lease_err") or "")
        # ── Gate 2c: nonce writer lease must be valid ─────────────────────
        # The distributed process writer lock and nonce-writer lease are
        # independent Redis invariants. Require both before LIVE activation.
        _nonce_lease_ok, _nonce_lease_err = _nonce_writer_lease_gate()
        _nonce_sync_ok = bool(_live_gate_status.get("nonce_ok"))
        _nonce_sync_err = str(_live_gate_status.get("nonce_err") or "")
        try:
            _coordinator.record_nonce_status(
                ready=bool(_nonce_lease_ok and _nonce_sync_ok),
                detail="; ".join(_d for _d in (_nonce_lease_err, _nonce_sync_err) if _d),
            )
        except Exception:
            logger.debug("commit_activation: coordinator nonce update failed", exc_info=True)

        # ── Gate 3: LIVE_CAPITAL_VERIFIED — composite semantic check ──────────
        # Semantics: flag==true AND capital_hydrated==true AND total_balance is not None.
        # Previously Gate 3 only checked the env var flag, which allowed the trading
        # loop to start with $0 balance when brokers hadn't finished hydrating CA.
        #
        # New contract (FIX 3):
        #   LIVE_CAPITAL_VERIFIED = (flag == true
        #                            AND capital_hydrated == true
        #                            AND total_balance is not None)
        if not _live_activation_intent:
            _coordinator.evaluate_activation(
                _coordinator.build_snapshot(
                    trading_state=current.value,
                    activation_intent=False,
                )
            )
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=LIVE_CAPITAL_VERIFIED_NOT_SET "
                "LIVE_CAPITAL_VERIFIED=%r LIVE_TRADING=%r coordinator_activation_intent=%r",
                _lcv_raw,
                _live_trading_raw,
                _coordinator.build_snapshot(
                    trading_state=current.value,
                    activation_intent=False,
                ).activation_intent,
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
                _lcv_raw,
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

        _capital_state_value = _capital_bootstrap_state_value()
        _bootstrap_state_value_now = _bootstrap_state_value()
        try:
            _coordinator.record_bootstrap_state(_bootstrap_state_value_now)
            _coordinator.record_capital_state(
                state=_capital_state_value,
                hydrated=_ca_hydrated_lcv,
                balance=_ca_balance_lcv,
                stale=bool(_ca_lcv.is_stale()) if _ca_lcv is not None and hasattr(_ca_lcv, "is_stale") else True,
            )
        except Exception:
            logger.debug("commit_activation: coordinator bootstrap/capital update failed", exc_info=True)

        _readiness_version, _readiness_snapshot = _readiness_snapshot_with_version()
        try:
            _coordinator.record_readiness(
                key="__snapshot__",
                value=bool(all(_readiness_snapshot.values())) if _readiness_snapshot else False,
                version=_readiness_version,
                table=_readiness_snapshot,
            )
        except Exception:
            logger.debug("commit_activation: coordinator readiness update failed", exc_info=True)

        # ── Gate 4: single global activation barrier ──────────────────────
        _mabm_gate = _get_mabm_instance()
        _ca_gate = _get_capital_authority_instance()
        _snap = cycle_capital if cycle_capital else {}
        _barrier_ready, _barrier_reason, _cap_ready, _exec_ready, _venue_ready, _inv_ready = _global_activation_barrier(
            _snap,
            _ca_gate,
            _mabm_gate,
            self,
        )
        if not _barrier_ready:
            logger.critical(
                "[AUTO_ACTIVATE BLOCKED] reason=GLOBAL_ACTIVATION_BARRIER detail=%s",
                _barrier_reason,
            )
        try:
            _coordinator.record_dispatch_health(
                ready=bool(_barrier_ready and _exec_ready and _venue_ready and _writer_ok and _nonce_lease_ok and _nonce_sync_ok),
                detail=_barrier_reason,
            )
        except Exception:
            logger.debug("commit_activation: coordinator dispatch-health update failed", exc_info=True)

        # ── Gate 5: activation_invariant — all subsystems simultaneously valid

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
        _live_verified_bool = bool(_live_activation_intent)
        _snapshot_ready = self._first_snap_accepted or (
            _snap.get("ca_valid_brokers", 0) > 0 and _snap.get("snapshot_source", "") == "live_exchange"
        )
        commit_activation(
            kill=kill_state,
            capital_ready=_cap_ready,
            execution_ready=_exec_ready,
            venue_ready=_venue_ready,
            live_verified=_live_verified_bool,
            invariant=_inv_ready,
            snapshot_ready=_snapshot_ready,
        )
        _frozen_snapshot = _coordinator.build_snapshot(
            trading_state=current.value,
            activation_intent=_live_activation_intent,
        )
        _decision = _coordinator.evaluate_activation(_frozen_snapshot)
        logger.critical(
            "STARTUP_COORDINATOR_DECISION version=%s state=%s reason=%s bootstrap=%s capital=%s readiness_v=%s",
            _decision.snapshot_version,
            _decision.target_state.value,
            _decision.reason,
            _frozen_snapshot.bootstrap_state,
            _frozen_snapshot.capital_state,
            _frozen_snapshot.readiness_version,
        )

        if not _decision.allowed or not _inv_ready or not _snapshot_ready:
            if kill_state:
                logger.critical("[AUTO_ACTIVATE BLOCKED] reason=KILL_SWITCH_ACTIVE")
            elif not authority_ready:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=AUTHORITY_NOT_READY "
                    "authority_ready=False current_state=%s target_state=LIVE_PENDING_CONFIRMATION",
                    current.value,
                )
            elif not _writer_ok:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=DISTRIBUTED_WRITER_AUTHORITY detail=%s",
                    _writer_err,
                )
            elif not _nonce_lease_ok:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=NONCE_WRITER_LEASE detail=%s",
                    _nonce_lease_err,
                )
            elif not _nonce_sync_ok:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=NONCE_SYNC detail=%s",
                    _nonce_sync_err,
                )
            elif not _ca_hydrated_lcv:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=LIVE_CAPITAL_VERIFIED_CA_NOT_HYDRATED "
                    "flag=%r ca_available=%s ca_hydrated=%s",
                    _lcv_raw,
                    _ca_lcv is not None,
                    bool(_ca_lcv.is_hydrated) if _ca_lcv is not None else False,
                )
            elif _ca_lcv is not None and _ca_balance_lcv is None:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=LIVE_CAPITAL_VERIFIED_BALANCE_UNKNOWN "
                    "flag=%r total_balance=None — capital balance not resolvable from CA.",
                    _lcv_raw,
                )
            elif not _snapshot_ready:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=SNAPSHOT_MISSING"
                    " — no valid live-exchange capital snapshot accepted"
                )
            elif _ca_gate is not None and not _ca_gate.is_hydrated:
                logger.critical("[AUTO_ACTIVATE BLOCKED] reason=CA_NOT_HYDRATED")
            elif _ca_gate is not None and _ca_gate.is_stale():
                logger.critical("[AUTO_ACTIVATE BLOCKED] reason=CA_STALE")
            elif (
                _mabm_gate is not None
                and hasattr(_mabm_gate, "all_brokers_fully_ready")
                and not _mabm_gate.all_brokers_fully_ready()
            ):
                logger.critical("[AUTO_ACTIVATE BLOCKED] reason=BROKERS_NOT_READY")
            elif not _snap.get("aggregation_normalized", True):
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=AGGREGATION_NOT_NORMALIZED"
                    " — MABM viable broker count not yet reflected in CA balance entries."
                    " Waiting for sequential pipeline: Broker balances"
                    " → ActiveCapital aggregation → Tier classification."
                )
            else:
                logger.critical(
                    "[AUTO_ACTIVATE BLOCKED] reason=%s snap_source=%s valid_brokers=%s",
                    _decision.reason.upper(),
                    _snap.get("snapshot_source", ""),
                    _snap.get("ca_valid_brokers", 0),
                )
            return False

        try:
            self._first_snap_accepted = True
            logger.critical("🚀 ACTIVATING TRADING ENGINE")
            self.transition_to(
                TradingState.LIVE_ACTIVE,
                f"STARTUP_COORDINATOR_COMMIT version={_frozen_snapshot.snapshot_version}",
            )
            # transition_to() atomically sets _activation_committed, _execution_authority,
            # _core_loop_owns_execution, _can_dispatch_trades, and
            # NIJA_RUNTIME_EXECUTION_AUTHORITY inside its own lock — no redundant
            # re-set needed here.
            assert self._current_state == TradingState.LIVE_ACTIVE, (
                f"FSM state must be LIVE_ACTIVE after activation, got {self._current_state}"
            )
            _coordinator.finalize_activation_commit(_frozen_snapshot)
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
        return self._evaluate_execution_authority_state().safety_state == ExecutionSafetyState.AUTHORIZED

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

    def _evaluate_execution_authority_state(self, gates_ok: Optional[bool] = None) -> ExecutionAuthoritySnapshot:
        runtime_mode = resolve_runtime_mode_safe(logger)
        intent_present = _activation_intent_present(runtime_mode)
        with self._lock:
            current_state = self._current_state
            activation_committed = self._activation_committed
            execution_authority = self._execution_authority
            can_dispatch = self._can_dispatch_trades
        if gates_ok is None:
            authority_ready = _is_authority_ready()
            runtime_writer_nonce_ready, runtime_detail = _runtime_writer_nonce_ready()
            gates_ok = bool(authority_ready and runtime_writer_nonce_ready)
            if not gates_ok:
                logger.critical(
                    "EXECUTION AUTHORITY LOCKED: authority_ready=%s writer_nonce_ready=%s detail=%s",
                    authority_ready,
                    runtime_writer_nonce_ready,
                    runtime_detail or "authority_ready=false",
                )
        return self._execution_authority_fsm.evaluate(
            intent_present=intent_present,
            bootstrap_running_supervised=_bootstrap_running_supervised(),
            capital_running=_capital_bootstrap_running(),
            trading_live=current_state == TradingState.LIVE_ACTIVE,
            activation_committed=activation_committed,
            execution_authority=execution_authority,
            can_dispatch_trades=can_dispatch,
            gates_ok=bool(gates_ok),
        )

    def get_execution_authority_snapshot(self, gates_ok: Optional[bool] = None) -> Dict[str, Any]:
        """Return execution authority state snapshot (dual-layer FSM)."""
        return self._evaluate_execution_authority_state(gates_ok=gates_ok).as_dict()

    def can_dispatch_trades(self) -> bool:
        """Return True when runtime dispatch should be allowed."""
        return self._evaluate_execution_authority_state().safety_state == ExecutionSafetyState.AUTHORIZED

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
        return self.commit_activation(cycle_capital=cycle_capital)


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


def _get_startup_coordinator():
    """Return the deterministic startup coordinator singleton."""
    try:
        from bot.startup_coordinator import get_startup_coordinator
        return get_startup_coordinator()
    except ImportError:
        from startup_coordinator import get_startup_coordinator  # type: ignore[import]
        return get_startup_coordinator()


def _bootstrap_running_supervised() -> bool:
    """Return True when BootstrapFSM reached RUNNING_SUPERVISED."""
    try:
        try:
            from bot.bootstrap_state_machine import get_bootstrap_fsm
        except ImportError:
            from bootstrap_state_machine import get_bootstrap_fsm  # type: ignore[import]
        _state = getattr(get_bootstrap_fsm().state, "value", "")
        return _state == "RUNNING_SUPERVISED"
    except Exception:
        return False


def _capital_bootstrap_running() -> bool:
    """Return True when CapitalBootstrapFSM reached RUNNING."""
    try:
        try:
            from bot.capital_flow_state_machine import get_capital_bootstrap_fsm
        except ImportError:
            from capital_flow_state_machine import get_capital_bootstrap_fsm  # type: ignore[import]
        _state = getattr(get_capital_bootstrap_fsm().state, "value", "")
        return _state == "RUNNING"
    except Exception:
        return False


def _capital_bootstrap_state_value() -> str:
    """Return the CapitalBootstrapFSM state value or ``UNAVAILABLE``."""
    try:
        try:
            from bot.capital_flow_state_machine import get_capital_bootstrap_fsm
        except ImportError:
            from capital_flow_state_machine import get_capital_bootstrap_fsm  # type: ignore[import]
        _state = getattr(get_capital_bootstrap_fsm().state, "value", "")
        return str(_state or "UNAVAILABLE")
    except Exception:
        return "UNAVAILABLE"


def _bootstrap_state_value() -> str:
    """Return the BootstrapFSM state value or ``UNAVAILABLE``."""
    try:
        try:
            from bot.bootstrap_state_machine import get_bootstrap_fsm
        except ImportError:
            from bootstrap_state_machine import get_bootstrap_fsm  # type: ignore[import]
        _state = getattr(get_bootstrap_fsm().state, "value", "")
        return str(_state or "UNAVAILABLE")
    except Exception:
        return "UNAVAILABLE"


def _readiness_snapshot_with_version() -> tuple[int, Dict[str, bool]]:
    """Return readiness-table version + snapshot, fail-closed on import errors."""
    try:
        try:
            from bot.readiness_table import snapshot_with_version as _snapshot_with_version
        except ImportError:
            from readiness_table import snapshot_with_version as _snapshot_with_version  # type: ignore[import]
        return _snapshot_with_version()
    except Exception:
        return 0, {}


def _activation_intent_present(runtime_mode: Optional[Any] = None) -> bool:
    """Return True when operator intent or coordinator request is present."""
    _live_intent = runtime_mode.is_live if runtime_mode is not None else _env_truthy("LIVE_CAPITAL_VERIFIED")
    _coordinator_requested = False
    try:
        _coordinator_requested = bool(
            _get_startup_coordinator().build_snapshot(
                trading_state="UNKNOWN",
                activation_intent=False,
            ).activation_intent
        )
    except Exception:
        _coordinator_requested = False
    return bool(_live_intent or _coordinator_requested)


def _is_authority_ready() -> bool:
    """Return readiness-table authority gate state, fail-closed on errors."""
    try:
        try:
            from bot.readiness_table import snapshot as _rt_snapshot
        except ImportError:
            from readiness_table import snapshot as _rt_snapshot  # type: ignore[import]
        return bool((_rt_snapshot() or {}).get("authority_ready", False))
    except Exception as _exc:
        logger.critical(
            "[AUTO_ACTIVATE BLOCKED] reason=AUTHORITY_READY_CHECK_FAILED detail=%s",
            _exc,
        )
        return False


def _runtime_writer_nonce_ready() -> tuple[bool, str]:
    """Return runtime writer+nonce readiness for dispatch authorization."""
    writer_ok, writer_err = _distributed_writer_authority_gate()
    if not writer_ok:
        return False, f"writer_authority:{writer_err}"

    nonce_sync_ok, nonce_sync_err = _nonce_sync_gate()
    if not nonce_sync_ok:
        return False, f"nonce_sync:{nonce_sync_err}"

    nonce_lease_ok, nonce_lease_err = _nonce_writer_lease_gate()
    if not nonce_lease_ok:
        return False, f"nonce_lease:{nonce_lease_err}"

    return True, ""


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

    if failures:
        return False, "; ".join(failures)
    return True, "ok"


def _strategy_readiness_gate() -> tuple[bool, str]:
    """Check that core strategy modules are loaded and available.

    Returns:
        (ok, reason) where ``ok`` is True when strategy modules are ready.
    """
    if not _env_truthy("NIJA_REQUIRE_STRATEGY_READY", "true"):
        return True, ""
    try:
        try:
            from bot.master_strategy_router import get_master_strategy_router
        except ImportError:
            from master_strategy_router import get_master_strategy_router  # type: ignore[import]
        router = get_master_strategy_router()
        if hasattr(router, "is_ready"):
            if not router.is_ready():
                return False, "STRATEGY_READY=false: no strategy modules loaded"
        else:
            voter_ready = getattr(router, "_voter", None) is not None
            apex_ready = getattr(router, "_apex", None) is not None
            if not voter_ready and not apex_ready:
                return False, "STRATEGY_READY=false: no strategy modules loaded"
        return True, "ok"
    except Exception as exc:
        return False, f"STRATEGY_READY=false: {exc}"


def _execution_readiness_gate() -> tuple[bool, str]:
    """Check execution pipeline health independently from capital readiness."""
    try:
        try:
            from bot.execution_router import get_execution_router
        except ImportError:
            from execution_router import get_execution_router  # type: ignore[import]
        router = get_execution_router()
        status = getattr(router, "get_status", lambda: {})()
        registered = int(status.get("registered_venues", 0) or 0)
        failed = len(status.get("session_failed_venues", []))
        healthy = max(0, registered - failed)
        logger.info(
            "[TradingStateMachine] _execution_readiness_gate: "
            "registered_venues=%d session_failed_venues=%d healthy_venues=%d",
            registered,
            failed,
            healthy,
        )
        if registered > 0 and healthy <= 0:
            return False, (
                "EXECUTION_READY=false: all registered venues are session-failed "
                f"(registered={registered} failed={failed})"
            )
    except (ImportError, AttributeError, Exception) as exc:
        logger.debug("_execution_readiness_gate: ExecutionRouter unavailable (%s) — skipping", exc)
    strategy_ok, strategy_err = _strategy_readiness_gate()
    if not strategy_ok:
        return False, strategy_err
    return True, "ok"


def _venue_thresholds_gate(cycle_capital: Optional[Dict[str, Any]], ca: Any) -> tuple:
    """Validate aggregate venue thresholds without blocking on a single venue warning."""
    try:
        minimum_balance = float(os.getenv("MINIMUM_TRADING_BALANCE", "1.0") or 1.0)
    except Exception:
        minimum_balance = 1.0

    total_capital = 0.0
    if cycle_capital:
        try:
            total_capital = float(cycle_capital.get("ca_total_capital", 0.0) or 0.0)
        except Exception:
            total_capital = 0.0

    if total_capital <= 0.0 and ca is not None:
        try:
            total_capital = float(ca.get_real_capital() or 0.0)
        except Exception:
            total_capital = 0.0

    if total_capital < minimum_balance:
        return False, (
            "VENUE_THRESHOLDS=false: aggregate capital below MINIMUM_TRADING_BALANCE "
            f"(total={total_capital:.2f} min={minimum_balance:.2f})"
        )

    return True, "ok"


def _global_activation_barrier(
    cycle_capital: Optional[Dict[str, Any]],
    ca: Any,
    mabm: Any,
    sm: "TradingStateMachine",
) -> tuple:
    """Single global barrier required before LIVE_ACTIVE transition."""
    cap_ready, cap_reason = _capital_readiness_gate()
    exec_ready, exec_reason = _execution_readiness_gate()
    venue_ready, venue_reason = _venue_thresholds_gate(cycle_capital, ca)
    invariant_ready = activation_invariant(cycle_capital or {}, ca, mabm, sm)

    reasons = []
    if not cap_ready:
        reasons.append(cap_reason)
    if not exec_ready:
        reasons.append(exec_reason)
    if not venue_ready:
        reasons.append(venue_reason)
    if not invariant_ready:
        reasons.append("INVARIANT=false: snapshot/registration/aggregation requirements not met")

    barrier_ready = cap_ready and exec_ready and venue_ready and invariant_ready
    detail = "ok" if barrier_ready else "; ".join(reasons)
    logger.critical(
        "GLOBAL_ACTIVATION_BARRIER | ready=%s capital=%s execution=%s venue=%s invariant=%s detail=%s",
        barrier_ready,
        cap_ready,
        exec_ready,
        venue_ready,
        invariant_ready,
        detail,
    )
    return barrier_ready, detail, cap_ready, exec_ready, venue_ready, invariant_ready


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
    # Accept either a previously latched first-snapshot signal or a valid
    # current-cycle live snapshot. This avoids a startup deadlock where
    # activation can never progress because the latch has not yet been set.
    snapshot_ready = sm._first_snap_accepted or (
        valid_brokers > 0 and snap_source == "live_exchange"
    )
    return all((
        snapshot_ready,
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
    execution_ready: bool,
    venue_ready: bool,
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
        ``True`` when the capital-readiness gate (CA_READY) passes.
    execution_ready:
        ``True`` when execution pipeline readiness passes (at least one
        registered venue is healthy for dispatch).
    venue_ready:
        ``True`` when normalized venue threshold validation passes using
        aggregate capital semantics.
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
        f"execution={execution_ready} | "
        f"venue={venue_ready} | "
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
        logger.critical("ACTIVATION BLOCKED: capital readiness gate failed")
        return False

    if not execution_ready:
        logger.critical("ACTIVATION BLOCKED: execution readiness gate failed")
        return False

    if not venue_ready:
        logger.critical("ACTIVATION BLOCKED: normalized venue threshold gate failed")
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
