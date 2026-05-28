#!/usr/bin/env python3
print("🔥 BOT ENTRY STARTED", flush=True)
"""
NIJA Trading Bot - Main Entry Point
Runs the complete APEX v7.1 strategy with Coinbase Advanced Trade API
Railway deployment: Force redeploy with position size fix ($5 minimum)
"""


import json
import os
import sys
import time
import traceback
import logging
import socket
import hashlib
import importlib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
import signal
import threading
import subprocess
from urllib.parse import urlparse
from typing import Any, Callable, cast

# ── MODULE-LEVEL STARTUP DIAGNOSTICS ─────────────────────────────────────────
# These print() calls fire at import/exec time — before any function is called,
# before logging is configured, and before any conditional logic runs.
# They are the earliest possible signal that bot.py is being loaded.
print(
    f"DIAG_BOT_MODULE_EXEC: bot.py executing at module level "
    f"pid={os.getpid()} "
    f"python={sys.version.split()[0]} "
    f"thread={threading.current_thread().name} "
    f"thread_id={threading.get_ident()} "
    f"__name__={__name__!r} "
    f"__file__={__file__!r}",
    flush=True,
)
print(
    f"DIAG_BOT_ENV_STARTUP: "
    f"RAILWAY_DEPLOYMENT_ID={os.environ.get('RAILWAY_DEPLOYMENT_ID', '<unset>')} "
    f"RAILWAY_SERVICE_ID={os.environ.get('RAILWAY_SERVICE_ID', '<unset>')} "
    f"RAILWAY_REPLICA_ID={os.environ.get('RAILWAY_REPLICA_ID', '<unset>')} "
    f"LIVE_CAPITAL_VERIFIED={os.environ.get('LIVE_CAPITAL_VERIFIED', '<unset>')} "
    f"DRY_RUN_MODE={os.environ.get('DRY_RUN_MODE', '<unset>')} "
    f"FORCE_TRADE={os.environ.get('FORCE_TRADE', '<unset>')} "
    f"HF_SCALP_MODE={os.environ.get('HF_SCALP_MODE', '<unset>')} "
    f"NIJA_EXECUTION_ACTIVE={os.environ.get('NIJA_EXECUTION_ACTIVE', '<unset>')} "
    f"NIJA_RUNTIME_EXECUTION_AUTHORITY={os.environ.get('NIJA_RUNTIME_EXECUTION_AUTHORITY', '<unset>')}",
    flush=True,
)

from bot.redis_env import (
    get_all_redis_urls,
    get_redis_env_presence,
    get_redis_resolution_diagnostics,
    get_redis_url,
    get_redis_url_source,
)
from bot.startup_env import resolve_coinbase_retail_portfolio_id
from bot.instance_identity import (
    current_instance_identity,
    format_instance_identity,
    inspect_lock_holder,
    parse_distributed_lock_holder,
    parse_writer_lock_metadata,
)

try:
    from bot.runtime_mode import resolve_runtime_mode
except ImportError:
    from runtime_mode import resolve_runtime_mode  # type: ignore[import]

# Early bootstrap logger so pre-config startup paths (locking, env checks,
# nonce init) can log safely before the full logging pipeline is configured.
logger = logging.getLogger("nija.bootstrap")

# ── AUTHORITY HEARTBEAT — IMMEDIATE POST-IMPORT STARTUP ──────────────────────
# This block executes immediately after imports, before any function
# definitions, before any conditional logic, and before main() is called.
# Moving it here ensures it runs as early as possible in the module load
# sequence regardless of how bot.py is loaded (runpy, direct exec, or import).
# The monitor is a singleton (idempotent) so calling it again later is safe.
print(
    "DIAG_MODULE_LEVEL_HEARTBEAT: starting authority heartbeat monitor immediately after imports "
    f"pid={os.getpid()} __name__={__name__!r}",
    flush=True,
)
logger.info(
    "MODULE_LEVEL_HEARTBEAT: starting authority heartbeat monitor immediately after imports "
    "pid=%d __name__=%r fencing_token_present=%s fallback=%s",
    os.getpid(),
    __name__,
    bool(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()),
    os.environ.get("NIJA_WRITER_FENCING_TOKEN_FALLBACK", ""),
)
try:
    from bot.authority_heartbeat import start_authority_heartbeat as _early_start_ahb
    _early_ahb_monitor = _early_start_ahb()
    logger.info(
        "MODULE_LEVEL_HEARTBEAT: monitor started successfully monitor=%r "
        "thread_name=%s thread_alive=%s thread_daemon=%s",
        _early_ahb_monitor,
        _early_ahb_monitor._thread.name if _early_ahb_monitor._thread else "None",
        _early_ahb_monitor._thread.is_alive() if _early_ahb_monitor._thread else False,
        _early_ahb_monitor._thread.daemon if _early_ahb_monitor._thread else False,
    )
    print(
        f"DIAG_MODULE_LEVEL_HEARTBEAT_OK: monitor started "
        f"thread={_early_ahb_monitor._thread.name if _early_ahb_monitor._thread else 'None'} "
        f"alive={_early_ahb_monitor._thread.is_alive() if _early_ahb_monitor._thread else False}",
        flush=True,
    )
except Exception as _early_ahb_exc:
    logger.error(
        "MODULE_LEVEL_HEARTBEAT: monitor could not be started: %s",
        _early_ahb_exc,
        exc_info=True,
    )
    print(
        f"DIAG_MODULE_LEVEL_HEARTBEAT_ERR: {_early_ahb_exc}",
        flush=True,
    )

# Reserved process exit code used when startup is blocked by an active
# distributed writer lock holder. This is an expected fail-closed condition
# in singleton deployments, not an application crash.
LOCK_CONTENTION_EXIT_CODE = 42

# ── Runtime env normalization (operator-friendly aliases + safe defaults) ──
_truthy_values = ("1", "true", "yes", "on", "enabled")


def _is_truthy(value: str) -> bool:
    return str(value or "").strip().lower() in _truthy_values


# Backward-compatible alias:
#   ENABLE_COINBASE=false  -> disable Coinbase execution/connect path
if "ENABLE_COINBASE" in os.environ:
    _enable_coinbase = _is_truthy(os.environ.get("ENABLE_COINBASE", ""))
    if not _enable_coinbase:
        os.environ.setdefault("ENABLE_COINBASE_TRADING", "false")
        os.environ.setdefault("NIJA_DISABLE_COINBASE", "true")
    else:
        os.environ.setdefault("ENABLE_COINBASE_TRADING", "true")
        # Allow Coinbase to connect when ENABLE_COINBASE=true.  The defensive
        # guard in _connect_and_register defaults NIJA_DISABLE_COINBASE to
        # "true" when the variable is absent, so we must explicitly unlock it.
        os.environ.setdefault("NIJA_DISABLE_COINBASE", "false")

# Small-order mode bridge:
#   ALLOW_SMALL_ORDERS=true + MIN_NOTIONAL_OVERRIDE=3.50
# propagates floors used across sizing/execution modules.
if "MIN_TRADE_USD" in os.environ and "ALLOW_SMALL_ORDERS" not in os.environ:
    os.environ.setdefault("ALLOW_SMALL_ORDERS", "true")

if _is_truthy(os.environ.get("ALLOW_SMALL_ORDERS", "false")):
    _override_raw = (
        os.environ.get("MIN_NOTIONAL_OVERRIDE")
        or os.environ.get("MIN_TRADE_USD")
        or "3.50"
    )
    try:
        _small_order_floor = max(1.0, float(_override_raw))
    except (TypeError, ValueError):
        _small_order_floor = 3.50
    _small_order_floor_str = f"{_small_order_floor:.2f}"
    _min_cash_floor_str = f"{max(1.0, _small_order_floor - 0.5):.2f}"

    os.environ.setdefault("MIN_NOTIONAL_OVERRIDE", _small_order_floor_str)
    os.environ.setdefault("MIN_TRADE_USD", _small_order_floor_str)
    os.environ.setdefault("MIN_NOTIONAL_USD", _small_order_floor_str)
    os.environ.setdefault("MIN_CASH_TO_BUY", _min_cash_floor_str)
    os.environ.setdefault("MINIMUM_TRADING_BALANCE", _small_order_floor_str)
    os.environ.setdefault("COINBASE_MIN_ORDER_USD", _small_order_floor_str)
    os.environ.setdefault("COINBASE_MIN_ORDER", _small_order_floor_str)
    os.environ.setdefault("COINBASE_OPERATIONAL_MIN_NOTIONAL_USD", _small_order_floor_str)

# Ensure at least one frequency driver is on unless explicitly configured off.
# Operator env values always win.
if "HF_SCALP_MODE" not in os.environ and "HF_FLIP_MODE" not in os.environ:
    os.environ.setdefault("HF_SCALP_MODE", "1")
os.environ.setdefault("HF_SCALPING_MODE", os.environ.get("HF_SCALP_MODE", "1"))

# ── Operational profile: low-capital survival mode ($20-$50) ───────────────
# Enabled by default for now; set NIJA_LOW_CAPITAL_SURVIVAL_MODE=0 to opt out.
if os.getenv("NIJA_LOW_CAPITAL_SURVIVAL_MODE", "1").strip().lower() in ("1", "true", "yes", "on"):
    os.environ.setdefault("NIJA_LOW_CAPITAL_THRESHOLD", "50")
    os.environ.setdefault("NIJA_LOW_CAPITAL_POSITION_PCT", "0.20")
    os.environ.setdefault("NIJA_LOW_CAPITAL_MIN_CONFIDENCE", "0.45")
    os.environ.setdefault("COINBASE_OPERATIONAL_MIN_NOTIONAL_USD", "3.0")
    os.environ.setdefault("COINBASE_MAX_POSITION_PCT", "0.20")
    os.environ.setdefault("MIN_NOTIONAL_USD", "3.0")
    os.environ.setdefault("COINBASE_MIN_ORDER_USD", "1.0")
    os.environ.setdefault("COINBASE_MIN_ORDER", "1.0")

# FIX #6: Reduce position sizing for small accounts
if _is_truthy(os.environ.get("FORCE_TRADE", "")) or _is_truthy(os.environ.get("FORCE_TRADE_MODE", "")):
    os.environ.setdefault("MIN_POSITION_USD", "2.0")
    os.environ.setdefault("MIN_NOTIONAL_USD", "2.0")
    os.environ.setdefault("COINBASE_MIN_ORDER_USD", "2.0")
    os.environ.setdefault("MAX_POSITION_PCT", "0.10")
    os.environ.setdefault("MIN_POSITION_PCT", "0.02")
    os.environ.setdefault("ENABLE_MICRO_SCALPING", "true")
    os.environ.setdefault("ALLOW_SMALL_ACCOUNT_TRADING", "true")
    import logging as _ft_logging
    _ft_logging.getLogger(__name__).info("🚀 FORCE_TRADE: Small account position sizing enabled")

# ── Bootstrap Guard — prevent duplicate instances ──────────────────────────
# Hard-stops if a second bot instance attempts to start.
try:
    from bot.bootstrap_guard import acquire_bootstrap_guard as _acquire_bootstrap_guard
    _BOOTSTRAP_GUARD_AVAILABLE = True
except ImportError:
    try:
        from bootstrap_guard import acquire_bootstrap_guard as _acquire_bootstrap_guard
        _BOOTSTRAP_GUARD_AVAILABLE = True
    except ImportError:
        _BOOTSTRAP_GUARD_AVAILABLE = False
        _acquire_bootstrap_guard = None  # type: ignore

# ── HF Scalping Mode — import early so cycle interval is available ─────────
# When HF_SCALP_MODE=1 the cycle interval drops from 150 s → 30 s and all
# entry filters are tightened.  Falls back silently if the module is absent.
try:
    from bot.hf_scalping_mode import get_hf_scalping_mode as _get_hf_scalping_mode_bot
    _hf_bot = _get_hf_scalping_mode_bot()
except Exception:
    try:
        from hf_scalping_mode import get_hf_scalping_mode as _get_hf_scalping_mode_bot
        _hf_bot = _get_hf_scalping_mode_bot()
    except Exception:
        _hf_bot = None

# ── Module-level singletons — persist across startup retry attempts ────────────
# These are populated after first successful initialisation and reused by the
# supervisor-loop-only restart path so TradingStrategy is never created twice.
_initialized_state: dict = {}
_initialized_state_lock = threading.RLock()
_bootstrap_owner_thread_id = None
_startup_last_error: str = ""
_startup_last_error_lock = threading.RLock()


def _set_startup_last_error(message: str) -> None:
    """Persist the last startup-thread error for supervisor diagnostics."""
    global _startup_last_error
    with _startup_last_error_lock:
        _startup_last_error = str(message or "")


def _get_startup_last_error() -> str:
    """Return the last startup-thread error captured by bootstrap kernel."""
    with _startup_last_error_lock:
        return _startup_last_error


def _format_startup_attempt_reason(attempt_index: int) -> str:
    """Return a compact reason tag for startup attempt logging."""
    if attempt_index <= 1:
        return "fresh-start"

    _last = (_get_startup_last_error() or "").replace("\n", " ").strip()
    if not _last:
        return "retry"
    if len(_last) > 120:
        _last = _last[:117] + "..."
    return f"retry-after={_last}"


def _format_startup_phase_tag() -> str:
    """Return a compact startup phase tag from the bootstrap FSM state."""
    try:
        if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
            _state = _get_bootstrap_fsm().state
            return f"phase={getattr(_state, 'value', str(_state))}"
    except Exception:
        pass
    return "phase=unknown"


def _reset_startup_events_for_fresh_attempt(*, clear_initialized_state: bool = False) -> None:
    """Reset readiness table and completion events before a fresh bootstrap attempt.

    When a startup attempt fails before full handoff, the next retry must not
    inherit stale readiness signals from the previous attempt.
    """
    _rt_reset()
    if clear_initialized_state:
        _acquired = _initialized_state_lock.acquire(timeout=5.0)
        if _acquired:
            try:
                _initialized_state.clear()
            finally:
                _initialized_state_lock.release()
            logger.debug("🔄 Cleared cached initialized state for clean bootstrap cycle")
        else:
            logger.warning("Could not acquire init lock to clear cached initialized state")
    _bootstrap_complete_flag.clear()
    _bootstrap_completed_event.clear()
    _force_trade_handoff_complete_event.clear()
    os.environ["NIJA_EXECUTION_ACTIVE"] = "0"
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    try:
        from bot.nija_core_loop import TRADING_ENGINE_READY as _tl_ready
    except ImportError:
        try:
            from nija_core_loop import TRADING_ENGINE_READY as _tl_ready  # type: ignore[import]
        except ImportError:
            _tl_ready = None  # type: ignore[assignment]
    if _tl_ready is not None:
        _tl_ready.clear()
    # Reset init-once guard for TradingStrategy so that if TradingStrategy()
    # construction failed on a previous attempt, a clean retry is possible.
    # Without this reset the guard permanently blocks re-creation and leaves
    # all readiness flags False on every subsequent attempt.
    try:
        from bot.init_once_guard import get_init_registry as _get_init_reg_reset
        _get_init_reg_reset().reset("trading_strategy")
        logger.debug("🔄 Init-once guard reset for 'trading_strategy' (fresh attempt)")
    except ImportError:
        logger.debug("Init-once guard module unavailable — reset skipped (non-fatal)")
    except Exception as _guard_reset_err:
        logger.warning("Init-once guard reset failed (non-fatal): %s", _guard_reset_err)
    logger.debug("🔄 Reset readiness table and completion events for fresh bootstrap attempt")


def _set_bootstrap_owner_thread() -> None:
    """Mark the current thread as the sole bootstrap lifecycle owner."""
    global _bootstrap_owner_thread_id
    _bootstrap_owner_thread_id = threading.get_ident()


def _clear_bootstrap_owner_thread() -> None:
    """Clear bootstrap lifecycle ownership marker."""
    global _bootstrap_owner_thread_id
    _bootstrap_owner_thread_id = None


def _is_bootstrap_owner_thread() -> bool:
    """Return True only for the thread that owns bootstrap lifecycle transitions."""
    return _bootstrap_owner_thread_id == threading.get_ident()


def _is_live_trading_active_now() -> bool:
    """Best-effort probe of LIVE_ACTIVE state without raising."""
    try:
        from bot.trading_state_machine import get_state_machine as _get_tsm_live_probe
    except ImportError:
        try:
            from trading_state_machine import get_state_machine as _get_tsm_live_probe  # type: ignore[import]
        except ImportError:
            return False

    try:
        return bool(_get_tsm_live_probe().is_live_trading_active())
    except Exception:
        return False


def acquire_writer_lock() -> bool:
    """Return True if this process currently holds the distributed writer lock.

    Checks the NIJA_WRITER_LEASE_ACQUIRED environment variable (set by
    ``_acquire_distributed_process_lock`` on successful Redis lock acquisition)
    and verifies that a fencing token is present.  Returns False when the lock
    was never acquired or has been released.

    This is the canonical startup-time check for single-writer authority.
    """
    _truthy = {"1", "true", "yes", "on", "enabled"}
    lease_acquired = os.environ.get("NIJA_WRITER_LEASE_ACQUIRED", "").strip().lower() in _truthy
    fencing_token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
    return lease_acquired and bool(fencing_token)


def is_live_trading() -> bool:
    """Return True when live capital trading is enabled for this deployment.

    Checks LIVE_CAPITAL_VERIFIED environment variable.  This is the canonical
    startup-time predicate for determining whether strict single-writer
    enforcement must be applied.
    """
    _truthy = {"1", "true", "yes", "on", "enabled"}
    return os.environ.get("LIVE_CAPITAL_VERIFIED", "").strip().lower() in _truthy


def _acquire_init_lock_bootstrap_only(*, context: str, timeout_s: float) -> bool:
    """Acquire INIT lock only from bootstrap owner thread.

    Any non-owner acquire attempt is rejected and logged as an ownership
    violation to preserve deterministic bootstrap lifecycle authority.

    INIT lock serializes bootstrap state publication and supervisor handoff.
    The lock itself is the safety boundary; additional startup-state gates here
    can deadlock legitimate owner-thread writes and create false timeout bypasses.
    """
    if not _is_bootstrap_owner_thread():
        logger.error(
            "INIT_LOCK_OWNERSHIP_VIOLATION context=%s owner_tid=%s caller_tid=%s",
            context,
            _bootstrap_owner_thread_id,
            threading.get_ident(),
        )
        return False

    # INIT lock must never re-trigger once LIVE mode is active.
    if _is_live_trading_active_now():
        logger.warning("Skipping INIT lock - already in LIVE mode (context=%s)", context)
        return False

    print("INIT_LOCK_ATTEMPT", flush=True)
    acquired = _initialized_state_lock.acquire(timeout=timeout_s)
    if acquired:
        print("INIT_LOCK_ACQUIRED", flush=True)
    return acquired


def _read_initialized_state_snapshot(
    *,
    lock_timeout_s: float = 1.0,
    max_attempts: int = 5,
    context: str = "startup",
) -> dict:
    """Read `_initialized_state` safely without stalling startup.

    If the lock cannot be acquired within bounded retries, raise a runtime
    error so bootstrap retries safely instead of bypassing the lock contract.
    """
    if not _is_bootstrap_owner_thread():
        # Single-authority rule: only bootstrap owner acquires INIT lock.
        # Non-owner readers get a best-effort snapshot without locking.
        return dict(_initialized_state)

    if _is_live_trading_active_now():
        # Live path: do not re-acquire INIT lock after activation.
        return dict(_initialized_state)

    for attempt in range(1, max_attempts + 1):
        acquired = _acquire_init_lock_bootstrap_only(
            context=f"read snapshot: {context}",
            timeout_s=lock_timeout_s,
        )
        if acquired:
            try:
                return dict(_initialized_state)
            finally:
                _initialized_state_lock.release()

        logger.warning(
            "INIT_LOCK_WAIT timeout context=%s attempt=%d/%d timeout=%.1fs",
            context,
            attempt,
            max_attempts,
            lock_timeout_s,
        )

    raise RuntimeError(
        f"INIT_LOCK_TIMEOUT context={context} — lock unavailable after {max_attempts} attempts"
    )


def _start_trading_loop_from_initialized_state(*, reason: str) -> bool:
    """Start trading loop from cached state only after strict supervised readiness."""
    if any(_t.name == "TradingLoop" and _t.is_alive() for _t in threading.enumerate()):
        logger.info("TradingLoop already running - skipping duplicate start (%s)", reason)
        _bootstrap_complete_flag.set()
        _bootstrap_completed_event.set()
        return True

    _strategy = None
    _wait_started = time.monotonic()
    _last_wait_log = 0.0

    # Hard requirement: do NOT start the trading loop until BOTH conditions hold:
    #   1. the cached strategy object is present in initialized state
    #   2. strategy_ready is set in the readiness truth table
    # This prevents a partially persisted strategy object from bypassing the
    # real startup readiness contract. This wait is intentionally unbounded:
    # startup must fail closed rather than degrade into a forced-ready bypass.
    def _strategy_ready_in_table() -> bool:
        return bool(_rt_snapshot().get("strategy_ready", False))

    logger.critical(
        "LIFECYCLE: _start_trading_loop_from_initialized_state waiting for strategy_ready (reason=%s)",
        reason,
    )
    while _strategy is None or not _strategy_ready_in_table():
        _state_snapshot = dict(_initialized_state)
        _strategy = _state_snapshot.get("strategy")
        if _strategy is not None and _strategy_ready_in_table():
            break

        _elapsed = time.monotonic() - _wait_started

        # Poll indefinitely with a short sleep — startup must fail closed rather
        # than degrade into a forced-ready bypass.
        time.sleep(0.25)

        if _elapsed - _last_wait_log >= 5.0:
            logger.critical(
                "LIFECYCLE: WAITING_FOR_STRATEGY_READY — trading-loop start blocked "
                "until strategy is initialized and readiness is signaled (%s, elapsed=%.1fs) "
                "strategy_present=%s table=%s",
                reason,
                _elapsed,
                _strategy is not None,
                _rt_snapshot(),
            )
            _last_wait_log = _elapsed

    _state_snapshot = _read_initialized_state_snapshot(context="strict supervised trading-loop start")
    try:
        system_ready, broker_ready, risk_ready, strategy_ready, capital_ready, execution_ready = \
            _require_startup_ready_or_raise(
                context="cached trading-loop start",
                state_snapshot=_state_snapshot,
            )
    except RuntimeError as _startup_guard_err:
        logger.warning(
            "START_TRADING_LOOP_BLOCKED: %s (%s)",
            _startup_guard_err,
            reason,
        )
        return False

    if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
        try:
            _bootstrap_state = getattr(_get_bootstrap_fsm().state, "value", "")
        except Exception:
            _bootstrap_state = ""
        if _bootstrap_state != "RUNNING_SUPERVISED":
            logger.warning(
                "START_TRADING_LOOP_BLOCKED: BootstrapFSM must already be RUNNING_SUPERVISED "
                "before the cached trading loop may start (%s, state=%s)",
                reason,
                _bootstrap_state or "unknown",
            )
            return False

    logger.info(
        "STRICT STARTUP READY: proceeding with supervised trading-loop start (%s, wait=%.1fs)",
        reason,
        time.monotonic() - _wait_started,
    )

    if not _is_balance_hydrated_ready():
        logger.warning(
            "START_TRADING_LOOP_BLOCKED: balance hydration not complete (%s)",
            reason,
        )
        return False

    try:
        try:
            from bot.nija_core_loop import start_trading_engine as _start_trading_engine
        except ImportError:
            from nija_core_loop import start_trading_engine as _start_trading_engine  # type: ignore[import]

        logger.info("STRATEGY_LOOP_ENTRY marker=supervised_handoff reason=%s", reason)
        logger.info("Starting trading loop from supervised state (%s)", reason)
        _trading_thread = _start_trading_engine(_strategy)
        if _trading_thread is None or not _trading_thread.is_alive():
            logger.error("START_TRADING_LOOP_FAILED: trading loop thread did not start (%s)", reason)
            return False
        # Mark bootstrap handoff so supervisor treats startup-thread exit as expected.
        _bootstrap_complete_flag.set()
        _bootstrap_completed_event.set()
        return True
    except Exception as _start_loop_err:
        logger.error("Failed to start trading loop from initialized state (%s): %s", reason, _start_loop_err)
        return False


def _compute_system_ready(state_snapshot: dict) -> tuple[bool, bool, bool, bool, bool, bool]:
    """Return (system_ready, broker_ready, risk_ready, strategy_ready, capital_ready, execution_ready).

    Delegates to the readiness truth table as the single source of truth.
    The ``state_snapshot`` argument is accepted for backward compatibility with
    call sites that still pass it; it is no longer used to derive readiness.

    Note: ``risk_ready`` is reported as a separate flag but is intentionally
    excluded from the ``system_ready`` AND-expression, matching the previous
    implementation.  Risk subsystem initialization is coupled to
    ``strategy_ready``; both must be True for the trading loop to start.
    """
    _tbl = _rt_snapshot()
    broker_ready = bool(_tbl.get("broker_connected", False))
    risk_ready = bool(_tbl.get("risk_ready", False))
    strategy_ready = bool(_tbl.get("strategy_ready", False))
    authority_ready = bool(_tbl.get("authority_ready", False))
    capital_ready = bool(_tbl.get("capital_ready", False))
    execution_ready = bool(_tbl.get("execution_ready", False))
    # risk_ready is not included here; it gates _require_startup_ready_or_raise.
    system_ready = broker_ready and strategy_ready and authority_ready and capital_ready and execution_ready
    return system_ready, broker_ready, risk_ready, strategy_ready, capital_ready, execution_ready


def _require_startup_ready_or_raise(*, context: str, state_snapshot: dict) -> tuple[bool, bool, bool, bool, bool, bool]:
    """Fail closed unless the startup readiness contract is fully satisfied.

    FORCE_TRADE does not bypass this startup contract; startup must satisfy the
    full readiness handshake before trading proceeds.
    """
    system_ready, broker_ready, risk_ready, strategy_ready, capital_ready, execution_ready = \
        _compute_system_ready(state_snapshot)
    authority_ready = bool(_rt_snapshot().get("authority_ready", False))
    if not all([broker_ready, risk_ready, strategy_ready, authority_ready, capital_ready, execution_ready]):
        raise RuntimeError(
            f"BLOCKED: System not fully initialized ({context}) "
            f"broker_ready={broker_ready} risk_ready={risk_ready} "
            f"strategy_ready={strategy_ready} authority_ready={authority_ready} capital_ready={capital_ready} "
            f"execution_ready={execution_ready} "
            f"table={_rt_snapshot()}"
        )
    return (
        system_ready,
        broker_ready,
        risk_ready,
        strategy_ready,
        capital_ready,
        execution_ready,
    )


def _is_balance_hydrated_ready() -> bool:
    """True only after startup balance hydration has completed."""
    if bool(_rt_snapshot().get("balance_hydrated", False)):
        return True

    if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
        try:
            _bootstrap_fsm = _get_bootstrap_fsm()
            if hasattr(_bootstrap_fsm, "is_balance_hydrated"):
                return bool(_bootstrap_fsm.is_balance_hydrated())
            _state_value = getattr(_bootstrap_fsm.state, "value", "")
            return _state_value in _BALANCE_HYDRATED_STATE_VALUES
        except Exception as _fsm_err:
            os.environ["NIJA_BALANCE_HYDRATION_LAST_ERROR"] = f"bootstrap_fsm_check_failed:{_fsm_err}"
            return False
    return False


def _nonce_readiness_required_for_startup() -> bool:
    """Return True when startup must require Kraken nonce readiness.

    Cases:
    1) Kraken platform credentials are present -> nonce gate is required.
    2) No Kraken platform credentials (Coinbase-only) -> nonce gate is not required.
    """
    _kraken_platform_key = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
    )
    # Kraken key configured => nonce readiness is mandatory.
    return bool(_kraken_platform_key)


def _balance_hydration_debug_status() -> dict:
    """Return compact diagnostics for startup hydration gate failures."""
    _rt = _rt_snapshot()
    _state_value = "UNAVAILABLE"
    _fsm_error = ""
    if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
        try:
            _bootstrap_fsm = _get_bootstrap_fsm()
            _state_value = str(getattr(getattr(_bootstrap_fsm, "state", None), "value", "UNKNOWN"))
        except Exception as _err:
            _fsm_error = str(_err)
    return {
        "balance_hydrated": bool(_rt.get("balance_hydrated", False)),
        "authority_ready": bool(_rt.get("authority_ready", False)),
        "capital_ready": bool(_rt.get("capital_ready", False)),
        "broker_ready": bool(_rt.get("broker_ready", False)),
        "strategy_ready": bool(_rt.get("strategy_ready", False)),
        "execution_ready": bool(_rt.get("execution_ready", False)),
        "bootstrap_fsm_state": _state_value,
        "bootstrap_fsm_error": _fsm_error,
        "last_error": os.environ.get("NIJA_BALANCE_HYDRATION_LAST_ERROR", ""),
    }


def _startup_execution_authority_status(*, context: str, force_refresh: bool = False) -> dict:
    """Return startup execution-authority prerequisite status."""
    try:
        try:
            from bot.execution_authority_context import get_startup_execution_authority_prerequisites
        except ImportError:
            from execution_authority_context import get_startup_execution_authority_prerequisites  # type: ignore[import]
        _status = get_startup_execution_authority_prerequisites(force_refresh=force_refresh)
    except Exception as exc:
        raise RuntimeError(f"execution authority status unavailable ({context}): {exc}") from exc

    if _status.get("ready"):
        if not bool(_rt_snapshot().get("authority_ready", False)):
            _rt_mark_ready("authority_ready")
    return _status


def _require_startup_execution_authority(*, context: str, force_refresh: bool = False) -> dict:
    """Fail closed unless startup execution authority prerequisites are satisfied."""
    try:
        try:
            from bot.execution_authority_context import require_startup_execution_authority
        except ImportError:
            from execution_authority_context import require_startup_execution_authority  # type: ignore[import]
        require_startup_execution_authority(context=context, force_refresh=force_refresh)
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    return _startup_execution_authority_status(context=context, force_refresh=False)


def _sum_nested_balances(balance_payload) -> float:
    """Best-effort recursive sum for dict/list/number balance payloads."""
    if isinstance(balance_payload, dict):
        return float(sum(_sum_nested_balances(v) for v in balance_payload.values()))
    if isinstance(balance_payload, (list, tuple, set)):
        return float(sum(_sum_nested_balances(v) for v in balance_payload))
    try:
        return float(balance_payload)
    except (TypeError, ValueError):
        return 0.0


def _is_bootstrap_lock_acquired() -> bool:
    """Return True only after BootstrapFSM reaches LOCK_ACQUIRED or later."""
    if os.getenv("NIJA_LOCK_ACQUIRED", "").strip().lower() == "true":
        return True
    if not (_BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None):
        return True
    try:
        _bfsm = _get_bootstrap_fsm()
        _state_value = getattr(getattr(_bfsm, "state", None), "value", "")
        return _state_value in _BOOTSTRAP_LOCK_READY_STATE_VALUES
    except Exception:
        return True


def _hydrate_startup_balances(strategy) -> float:
    """Force a startup balance sync and return the authoritative total USD balance."""
    global _hydrated_total_balance_usd

    if not _is_bootstrap_lock_acquired():
        raise RuntimeError(
            "Balance hydration blocked: BootstrapFSM must reach LOCK_ACQUIRED first"
        )

    logger.info("💰 Hydration phase: starting balance sync")

    balances = None
    _mam = getattr(strategy, "multi_account_manager", None)
    _bm = getattr(strategy, "broker_manager", None)
    _is_live = os.environ.get("LIVE_CAPITAL_VERIFIED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "enabled",
        "on",
    )

    # Temporary operator bypass to validate startup pipeline end-to-end.
    _balance_override_raw = os.environ.get("ACCOUNT_BALANCE_OVERRIDE", "").strip()
    if _balance_override_raw:
        try:
            _override = float(_balance_override_raw)
            if _override > 0:
                _hydrated_total_balance_usd = _override
                os.environ["ACCOUNT_BALANCE"] = f"{_override:.8f}"
                _rt_mark_ready("balance_hydrated")
                try:
                    _startup_execution_authority_status(
                        context="hydrate_startup_balances: ACCOUNT_BALANCE_OVERRIDE",
                        force_refresh=True,
                    )
                except Exception as _auth_status_err:
                    logger.warning(
                        "Authority status unavailable during balance override hydration: %s",
                        _auth_status_err,
                    )
                _rt_mark_ready("capital_ready")
                logger.warning(
                    "⚠️ ACCOUNT_BALANCE_OVERRIDE active: forcing startup balance to $%.2f",
                    _override,
                )
                return _override
        except ValueError:
            logger.warning(
                "Invalid ACCOUNT_BALANCE_OVERRIDE=%r; ignoring override",
                _balance_override_raw,
            )

    if _mam is not None and hasattr(_mam, "get_all_balances"):
        logger.info("Fetching Kraken balance via multi_account_manager.get_all_balances")
        balances = _mam.get_all_balances()
        logger.debug("Balance response: %s", balances)
    elif _bm is not None and hasattr(_bm, "get_all_balances"):
        logger.info("Fetching Kraken balance via broker_manager.get_all_balances")
        balances = _bm.get_all_balances()
        logger.debug("Balance response: %s", balances)

    # Fallback path: strategy wiring can be temporarily unavailable during
    # startup transitions. Use the global multi-account broker manager directly
    # so hydration cannot fail with "no balance provider available".
    if balances is None:
        try:
            try:
                from bot.multi_account_broker_manager import multi_account_broker_manager as _mabm
            except ImportError:
                from multi_account_broker_manager import multi_account_broker_manager as _mabm  # type: ignore[import]

            logger.info("Hydration fallback: initializing global multi-account broker manager")
            _mabm.initialize()
            _platform_init = _mabm.initialize_platform_brokers()
            _connected_platforms = [
                _k for _k, _meta in (_platform_init or {}).items()
                if bool((_meta or {}).get("connected", False))
            ]
            logger.info(
                "Hydration fallback platform init: connected=%d (%s)",
                len(_connected_platforms),
                ", ".join(_connected_platforms) if _connected_platforms else "none",
            )
            balances = _mabm.get_all_balances()
            logger.debug("Hydration fallback balance response: %s", balances)
        except Exception as _fallback_err:
            logger.error("Hydration fallback failed: %s", _fallback_err)

    if balances is None:
        os.environ["NIJA_BALANCE_HYDRATION_LAST_ERROR"] = "no_balance_provider_available"
        raise RuntimeError("CRITICAL: Balance hydration failed (no balance provider available)")

    total_balance = _sum_nested_balances(balances)
    _hydrated_total_balance_usd = float(total_balance)
    os.environ["ACCOUNT_BALANCE"] = f"{_hydrated_total_balance_usd:.8f}"

    logger.info("💰 Hydration complete: total_balance=$%.2f", _hydrated_total_balance_usd)
    os.environ.pop("NIJA_BALANCE_HYDRATION_LAST_ERROR", None)

    if _is_live and _hydrated_total_balance_usd <= 0:
        raise RuntimeError("LIVE mode requires valid balance")
    if (not _is_live) and _hydrated_total_balance_usd <= 0:
        logger.warning("Startup hydration total is <= 0 in non-live mode; continuing")

    _rt_mark_ready("balance_hydrated")
    try:
        _startup_execution_authority_status(
            context="hydrate_startup_balances",
            force_refresh=True,
        )
    except Exception as _auth_status_err:
        logger.warning(
            "Authority status unavailable during startup hydration: %s",
            _auth_status_err,
        )
    _rt_mark_ready("capital_ready")
    logger.info("CAPITAL_READY_SET")
    return _hydrated_total_balance_usd

# Single-owner bootstrap kernel lock.
# Only one bootstrap execution sequence may run at a time.  The BotStartup
# thread acquires this non-blocking before entering the retry loop.  If another
# concurrent call sneaks in (e.g. a second spawn from an unexpected code path)
# it is rejected immediately instead of racing through shared init state.
_BOOTSTRAP_SINGLE_OWNER_LOCK = threading.Lock()

# Set once bootstrap completes successfully (FSM reaches RUNNING_SUPERVISED).
# The outer supervisor uses this to distinguish a normal "bootstrap done, trading
# threads are live" thread exit from a genuine bootstrap failure — only the
# latter should terminate the process.
_bootstrap_complete_flag = threading.Event()
# Bootstrap completion flag — separates a successful bootstrap from a failed one.
# Set when bootstrap reaches RUNNING_SUPERVISED state (trader threads are live).
# Thread lifecycle is intentionally independent of system lifecycle: the outer
# supervisor loop must continue keeping the process alive after the bootstrap
# thread hands off, so trader threads can keep running without interruption.
_bootstrap_completed_event = threading.Event()

# ---------------------------------------------------------------------------
# Startup readiness truth table — single source of truth for all readiness
# state.  Replaces the previous 8 threading.Event objects, the
# StartupReadinessGate, and the _compute_system_ready re-derivation.
# ---------------------------------------------------------------------------
try:
    from bot.readiness_table import (
        is_ready as _rt_is_ready,
        mark_ready as _rt_mark_ready,
        mark_not_applicable as _rt_mark_not_applicable,
        pending as _rt_pending,
        reset as _rt_reset,
        snapshot as _rt_snapshot,
    )
    _READINESS_TABLE_AVAILABLE = True
except ImportError:
    try:
        from readiness_table import (  # type: ignore[import]
            is_ready as _rt_is_ready,
            mark_ready as _rt_mark_ready,
            mark_not_applicable as _rt_mark_not_applicable,
            pending as _rt_pending,
            reset as _rt_reset,
            snapshot as _rt_snapshot,
        )
        _READINESS_TABLE_AVAILABLE = True
    except ImportError:
        _READINESS_TABLE_AVAILABLE = False
        _rt_is_ready = lambda: False  # type: ignore[assignment]
        _rt_mark_ready = lambda _k: None  # type: ignore[assignment]
        _rt_mark_not_applicable = lambda _k, **_kw: None  # type: ignore[assignment]
        _rt_pending = lambda: []  # type: ignore[assignment]
        _rt_reset = lambda: None  # type: ignore[assignment]
        _rt_snapshot = lambda: {}  # type: ignore[assignment]

_hydrated_total_balance_usd = 0.0
# Idempotency guard for FORCE_TRADE bootstrap handoff.
# Set only after RUNNING_SUPERVISED handoff succeeds.
_force_trade_handoff_complete_event = threading.Event()
_post_unlock_minimum_trading_balance = "1"


def dump_startup_state(context: str = "") -> None:
    """Log a startup diagnostics snapshot for timeout and deadlock investigations."""
    try:
        _snapshot = _read_initialized_state_snapshot(context=f"startup dump: {context or 'no-context'}")
    except Exception as _snapshot_err:
        logger.warning("STARTUP_STATE_DUMP_FAILED context=%s err=%s", context or "no-context", _snapshot_err)
        return

    _strategy = _snapshot.get("strategy")
    try:
        (
            _system_ready,
            _broker_ready,
            _risk_ready,
            _strategy_ready,
            _capital_ready,
            _execution_ready,
        ) = _compute_system_ready(_snapshot)
    except Exception:
        _system_ready = False
        _broker_ready = False
        _risk_ready = False
        _strategy_ready = False
        _capital_ready = False
        _execution_ready = False

    _bfsm_state = "UNAVAILABLE"
    _bfsm_exec_authority = False
    if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
        try:
            _bfsm = _get_bootstrap_fsm()
            _bfsm_state = getattr(getattr(_bfsm, "state", None), "value", str(getattr(_bfsm, "state", "UNAVAILABLE")))
            _bfsm_exec_authority = bool(
                _bfsm.has_execution_authority()
                if hasattr(_bfsm, "has_execution_authority")
                else getattr(_bfsm, "execution_authority", False)
            )
        except Exception:
            pass

    logger.warning(
        "STARTUP_STATE_DUMP context=%s system_ready=%s broker_ready=%s risk_ready=%s strategy_ready=%s "
        "capital_ready=%s execution_ready=%s strategy_present=%s bfsm_state=%s bfsm_execution_authority=%s "
        "readiness_table=%s",
        context or "no-context",
        _system_ready,
        _broker_ready,
        _risk_ready,
        _strategy_ready,
        _capital_ready,
        _execution_ready,
        _strategy is not None,
        _bfsm_state,
        _bfsm_exec_authority,
        _rt_snapshot(),
    )


def _wait_for_event_with_timeout(event: threading.Event, *, timeout_s: float, timeout_label: str) -> bool:
    """Wait for an event and emit critical diagnostics on timeout."""
    if event.wait(timeout=timeout_s):
        return True
    logger.critical("TIMEOUT_WAITING_FOR_%s", timeout_label)
    dump_startup_state(f"TIMEOUT_WAITING_FOR_{timeout_label}")
    return False


def _wait_for_predicate_with_timeout(
    *,
    predicate: Callable[[], bool],
    timeout_s: float,
    timeout_label: str,
    poll_interval_s: float = 0.5,
) -> bool:
    """Wait for a readiness predicate and emit diagnostics on timeout."""
    _deadline = time.monotonic() + max(0.1, timeout_s)
    while time.monotonic() < _deadline:
        try:
            if predicate():
                return True
        except Exception as _pred_err:
            logger.debug("Predicate probe failed for %s: %s", timeout_label, _pred_err)
        time.sleep(max(0.05, poll_interval_s))

    logger.critical("TIMEOUT_WAITING_FOR_%s", timeout_label)
    dump_startup_state(f"TIMEOUT_WAITING_FOR_{timeout_label}")
    return False


def _bootstrap_state_value() -> str:
    """Return BootstrapFSM state value or 'UNAVAILABLE' when not importable."""
    if not (_BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None):
        return "UNAVAILABLE"
    try:
        _state = _get_bootstrap_fsm().state
        return str(getattr(_state, "value", _state))
    except Exception as _state_err:
        logger.debug("Bootstrap state probe failed: %s", _state_err)
        return "UNKNOWN"


def _env_truthy(name: str, default: str = "false") -> bool:
    """Parse a boolean-like env flag using project-wide truthy semantics."""
    return os.getenv(name, default).strip().lower() in _TRUTHY_ENV_VALUES


def _startup_readiness_policy() -> dict[str, bool]:
    """Return required/optional policy for startup readiness criteria."""
    _nonce_required_default = _nonce_readiness_required_for_startup()
    return {
        "broker_connected": _env_truthy("NIJA_STARTUP_REQUIRE_BROKER_CONNECTED", "false"),
        "nonce_ready": _env_truthy(
            "NIJA_STARTUP_REQUIRE_NONCE_READY",
            "true" if _nonce_required_default else "false",
        ),
        "first_snap": _env_truthy("NIJA_STARTUP_REQUIRE_FIRST_SNAP", "false"),
    }


def _probe_first_snap_accepted() -> bool:
    """Best-effort probe for first snapshot acceptance."""
    try:
        from bot.trading_state_machine import get_state_machine as _get_tsm_probe
    except ImportError:
        try:
            from trading_state_machine import get_state_machine as _get_tsm_probe  # type: ignore[import]
        except ImportError:
            return False
    try:
        return bool(_get_tsm_probe().get_first_snap_accepted())
    except Exception as _first_snap_err:
        logger.debug("first_snap probe failed: %s", _first_snap_err)
        return False


def _evaluate_startup_readiness_policy(*, context: str, timeout_s: float) -> tuple[dict[str, bool], list[str], list[str], float]:
    """Evaluate startup readiness criteria under required/optional policy."""
    _policy = _startup_readiness_policy()
    _deadline = time.monotonic() + max(0.0, timeout_s)

    while time.monotonic() < _deadline:
        _table = _rt_snapshot()
        _criteria = {
            "broker_connected": bool(_table.get("broker_connected", False)),
            "nonce_ready": bool(_table.get("nonce_ready", False)),
            "first_snap": _probe_first_snap_accepted(),
        }
        _required_missing = sorted(k for k, v in _criteria.items() if _policy.get(k, False) and not v)
        if not _required_missing:
            _optional_missing = sorted(k for k, v in _criteria.items() if (not _policy.get(k, False)) and not v)
            logger.info(
                "STARTUP_POLICY_EVAL context=%s criteria=%s required_missing=%s optional_missing=%s deadline_in=%.2fs",
                context,
                _criteria,
                _required_missing,
                _optional_missing,
                max(0.0, _deadline - time.monotonic()),
            )
            return _criteria, _required_missing, _optional_missing, _deadline
        time.sleep(0.25)

    _table = _rt_snapshot()
    _criteria = {
        "broker_connected": bool(_table.get("broker_connected", False)),
        "nonce_ready": bool(_table.get("nonce_ready", False)),
        "first_snap": _probe_first_snap_accepted(),
    }
    _required_missing = sorted(k for k, v in _criteria.items() if _policy.get(k, False) and not v)
    _optional_missing = sorted(k for k, v in _criteria.items() if (not _policy.get(k, False)) and not v)
    logger.info(
        "STARTUP_POLICY_EVAL context=%s criteria=%s required_missing=%s optional_missing=%s deadline_in=0.00s",
        context,
        _criteria,
        _required_missing,
        _optional_missing,
    )
    return _criteria, _required_missing, _optional_missing, _deadline


def _wait_for_bootstrap_observer_ready(*, context: str) -> tuple[bool, str]:
    """Single observer API for main-thread startup wait with bounded timeout."""
    _timeout_raw = os.getenv("NIJA_BOOTSTRAP_OBSERVER_TIMEOUT_S", f"{_BOOTSTRAP_OBSERVER_TIMEOUT_S:.1f}")
    try:
        _timeout_s = max(1.0, float(_timeout_raw))
    except ValueError:
        logger.warning(
            "Invalid NIJA_BOOTSTRAP_OBSERVER_TIMEOUT_S=%r; using default %.1fs",
            _timeout_raw,
            _BOOTSTRAP_OBSERVER_TIMEOUT_S,
        )
        _timeout_s = _BOOTSTRAP_OBSERVER_TIMEOUT_S
    _deadline = time.monotonic() + _timeout_s
    # Track the last state seen so we can detect FSM stalls and log them.
    _last_logged_state: str = ""
    _last_state_log = time.monotonic()
    _state_log_interval = 10.0

    while time.monotonic() < _deadline:
        _state = _bootstrap_state_value()
        if _state == "RUNNING_SUPERVISED":
            logger.critical("LIFECYCLE: FSM state=%s", _state)
            return True, _state
        if _state in {"BOOT_FAILED_RETRY", "EXTERNAL_RESTART_REQUIRED", "SHUTDOWN"}:
            logger.error(
                "BOOTSTRAP_OBSERVER_BLOCKED context=%s state=%s deadline=%.2fs next=abort_startup",
                context,
                _state,
                _timeout_s,
            )
            return False, _state

        # Log FSM state transitions so each new state is visible in the logs.
        if _state != _last_logged_state:
            logger.critical("LIFECYCLE: FSM state=%s", _state)
            _last_logged_state = _state

        _now = time.monotonic()
        if _now - _last_state_log >= _state_log_interval:
            _elapsed = _now - (_deadline - _timeout_s)
            logger.critical(
                "LIFECYCLE: bootstrap observer waiting — FSM state=%s elapsed=%.1fs remaining=%.1fs context=%s",
                _state,
                _elapsed,
                max(0.0, _deadline - _now),
                context,
            )
            _last_state_log = _now
        time.sleep(_BOOTSTRAP_OBSERVER_POLL_INTERVAL_S)

    _state = _bootstrap_state_value()
    logger.critical(
        "BOOTSTRAP_OBSERVER_TIMEOUT context=%s state=%s deadline=%.2fs — bot will continue waiting",
        context,
        _state,
        _timeout_s,
    )
    # Do not crash — return success so the bot can proceed even if FSM is stuck.
    # The FSM may still be in a valid intermediate state (e.g. CAPITAL_READY or
    # INIT_COMPLETE) that the startup thread is actively advancing.
    logger.critical(
        "LIFECYCLE: bootstrap observer timeout reached but NOT raising — FSM state=%s; "
        "allowing startup to continue",
        _state,
    )
    return True, _state


def _assert_bootstrap_execution_authority(context: str) -> None:
    """Fail closed when lifecycle ownership has not been handed to runtime."""
    if not (_BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None):
        return
    _bfsm = _get_bootstrap_fsm()
    _has_authority = bool(
        _bfsm.has_execution_authority()
        if hasattr(_bfsm, "has_execution_authority")
        else getattr(_bfsm, "execution_authority", False)
    )
    assert _has_authority, f"BOOTSTRAP_EXECUTION_AUTHORITY_REQUIRED: {context}"

# Explicit lifecycle phases used by startup diagnostics.
BOOTSTRAP_PHASES = [
    "ENV_VERIFIED",
    "CAPABILITY_VERIFIED",
    "STARTUP_VALIDATED",
    "LOCK_ACQUIRED",
    "HEALTH_BOUND",
    "BALANCE_HYDRATED",
    "READY_FOR_TRADING",
]

# Bootstrap-window nonce flag — set to True the moment the pre-connection nonce
# jump is executed.  Any attempt to run the same jump after bootstrap is complete
# (i.e. from a background scheduler or async path) is blocked and logged so it
# can never accidentally advance the nonce during live trading.
_nonce_bootstrap_jump_done = False
_nonce_bootstrap_jump_lock = threading.Lock()

# Startup strategy publication lock timeout (seconds) used by fallback/republish paths.
_INIT_LOCK_PUBLISH_TIMEOUT_S = 5.0
# Supervisor grace window before degraded fallback strategy construction (seconds).
_STRATEGY_FALLBACK_GRACE_PERIOD_S = 30.0
# Maximum seconds to wait for platform brokers to report fully ready at the
# INIT_COMPLETE → THREADS_STARTING readiness gate.  After this timeout the
# broker_connected flag remains False and startup policy decides whether to
# block or degrade.
_BROKER_CONNECTED_READY_TIMEOUT_S = 30.0
# Seconds the B1 preflight guard polls all_brokers_fully_ready() before
# giving up.  Allows async balance-payload fetch to complete before B1 runs.
_B1_BROKER_READY_POLL_TIMEOUT_S = 10.0
_B1_BROKER_READY_POLL_INTERVAL_S = 0.5
# Retry parameters for the _rt_is_ready() THREADS_STARTING gate.
# Gives fractionally-late readiness signals time to propagate before raising.
_RT_GATE_RETRY_ATTEMPTS = 5
_RT_GATE_RETRY_INTERVAL_S = 1.0
_BOOTSTRAP_OBSERVER_TIMEOUT_S = 240.0
_BOOTSTRAP_OBSERVER_POLL_INTERVAL_S = 1.0
# Strategy publication should complete within the same startup observer window.
_STARTUP_POLICY_EVAL_TIMEOUT_S = 5.0
_STRATEGY_PUBLICATION_TIMEOUT_S = _BOOTSTRAP_OBSERVER_TIMEOUT_S
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on", "enabled"}


def _publish_strategy_runtime_readiness(strategy_obj: Any, *, context: str) -> bool:
    """Persist strategy singleton and mark strategy/execution ready in the truth table."""
    try:
        _initialized_state["strategy"] = strategy_obj
        # Preserve existing startup contract: once TradingStrategy is cached,
        # risk subsystem is considered initialized for startup gating.
        _initialized_state["risk_ready"] = True
        _initialized_state["strategy_initialized"] = True
        logger.info("STRATEGY_ASSIGNED")
    except Exception as exc:
        logger.warning("Strategy publish failed (%s): %s", context, exc)
        return False

    # Capability is independent from execution authority.  Publish strategy/risk/
    # execution capability deterministically even when authority is temporarily
    # unavailable; authority remains a separate hard gate for live activation.
    try:
        _startup_execution_authority_status(
            context=f"publish_strategy_runtime_readiness:{context}",
            force_refresh=True,
        )
    except Exception as exc:
        logger.warning(
            "Strategy readiness published without authority confirmation (%s): %s",
            context,
            exc,
        )

    _rt_mark_ready("strategy_ready")
    _rt_mark_ready("risk_ready")
    logger.info("STRATEGY_READY_SET")
    logger.info(
        "STRATEGY INITIALIZED — strategy-ready marked in truth table; awaiting hydrated runtime state persistence"
    )

    # BootstrapCoordinator: advance to STRATEGY_READY now that the trading
    # strategy has been initialized and published.  This unblocks signal
    # broadcaster, market regime detector, and any other daemon that requires
    # a live strategy before starting.

    _exec_engine = getattr(strategy_obj, "execution_engine", None)
    if _exec_engine is None:
        _apex = getattr(strategy_obj, "apex", None)
        _exec_engine = getattr(_apex, "execution_engine", None) if _apex is not None else None
    if _exec_engine is not None:
        _rt_mark_ready("execution_ready")
        logger.info("EXECUTION_READY_SET")
    else:
        # Execution engine not yet attached.  When NIJA_REQUIRE_EXECUTION_ENGINE=false
        # (the default) we still mark execution_ready so the FSM can complete its
        # transition — the engine may be initialised lazily inside the strategy.
        # Set NIJA_REQUIRE_EXECUTION_ENGINE=true to keep the strict gate.
        _require_engine = os.environ.get("NIJA_REQUIRE_EXECUTION_ENGINE", "false").strip().lower() in (
            "1", "true", "yes", "on", "enabled"
        )
        if not _require_engine:
            _rt_mark_ready("execution_ready")
            logger.info(
                "EXECUTION_READY_SET (no execution_engine attr found on strategy; "
                "set NIJA_REQUIRE_EXECUTION_ENGINE=true to keep strict gate) context=%s",
                context,
            )
        else:
            logger.warning(
                "Execution engine not yet available during strategy publish (%s); "
                "execution_ready remains unset (NIJA_REQUIRE_EXECUTION_ENGINE=true)",
                context,
            )

    return True


def _ensure_strategy_fallback_published(*, context: str) -> bool:
    """Load a default strategy and publish readiness if strategy is missing."""
    _state_snapshot = _read_initialized_state_snapshot(context=f"{context}: pre-fallback probe")
    _strategy = _state_snapshot.get("strategy")
    if _strategy is not None:
        if not bool(_rt_snapshot().get("strategy_ready", False)):
            logger.warning("Strategy present without strategy_ready in table; publishing readiness (%s)", context)
            _acquired = _initialized_state_lock.acquire(timeout=_INIT_LOCK_PUBLISH_TIMEOUT_S)
            if not _acquired:
                logger.warning("Readiness republish skipped: INIT lock unavailable (%s)", context)
                return False
            try:
                return _publish_strategy_runtime_readiness(_strategy, context=f"{context}: existing-strategy")
            finally:
                _initialized_state_lock.release()
        return True

    _authority = _startup_execution_authority_status(
        context=f"{context}: fallback authority precheck",
        force_refresh=True,
    )
    _authority_details = _authority.get("authority_status", {})
    _strict_required = bool(
        _authority_details.get(
            "effective_strict_required",
            _authority_details.get("strict_required", False),
        )
    )
    if _strict_required and not bool(_authority.get("ready", False)):
        logger.warning(
            "Default strategy fallback blocked: startup execution authority not ready "
            "(context=%s missing=%s)",
            context,
            _authority.get("missing", []),
        )
        return False

    logger.warning("No strategy published yet — attempting default strategy fallback (%s)", context)
    logger.warning("Fallback uses TradingStrategy default constructor in degraded startup mode (%s)", context)
    try:
        _fallback_strategy = TradingStrategy()
    except Exception as exc:
        logger.exception("Default strategy fallback construction failed (%s): %s", context, exc)
        return False

    _acquired = _initialized_state_lock.acquire(timeout=_INIT_LOCK_PUBLISH_TIMEOUT_S)
    if not _acquired:
        logger.warning("Fallback publish skipped: INIT lock unavailable (%s)", context)
        return False
    try:
        return _publish_strategy_runtime_readiness(_fallback_strategy, context=f"{context}: fallback-strategy")
    finally:
        _initialized_state_lock.release()


def _ensure_running_supervised(active_threads: dict, *, context: str) -> None:
    """Ensure the Bootstrap FSM reaches RUNNING_SUPERVISED after threads start.

    No-op when no active threads are present.
    """
    if not _BOOTSTRAP_FSM_AVAILABLE or _get_bootstrap_fsm is None:
        return
    if not active_threads:
        logger.debug("RUNNING_SUPERVISED safeguard skipped (no active threads): %s", context)
        return
    try:
        _bfsm = _get_bootstrap_fsm()
        _state = _bfsm.state
        if _state == _BootstrapState.RUNNING_SUPERVISED:
            return
        if _state != _BootstrapState.THREADS_STARTING:
            logger.warning(
                "RUNNING_SUPERVISED safeguard: unexpected state=%s context=%s",
                getattr(_state, "value", str(_state)),
                context,
            )

        # Prefer the legal handoff helper so we never force an illegal direct
        # state jump to RUNNING_SUPERVISED.
        _handoff_fn = globals().get("_try_finalize_running_supervised_handoff")
        if callable(_handoff_fn):
            _ok = bool(
                _handoff_fn(
                    reason=f"{len(active_threads)} trader thread(s) started; safeguard from {context}",
                    completion_log="🚀 FSM STATE: RUNNING_SUPERVISED (safeguard)",
                    set_bootstrap_events=True,
                )
            )
            if not _ok:
                logger.info(
                    "RUNNING_SUPERVISED safeguard deferred: state=%s context=%s",
                    getattr(_bfsm.state, "value", str(_bfsm.state)),
                    context,
                )
            return

        # Fallback path for early startup contexts where helper is unavailable.
        _bfsm_transition(
            _BootstrapState.RUNNING_SUPERVISED,
            f"{len(active_threads)} trader thread(s) started; safeguard fallback from {context}",
        )
        logger.info("🚀 FSM STATE: RUNNING_SUPERVISED (safeguard fallback)")
    except Exception as exc:
        logger.warning("RUNNING_SUPERVISED safeguard failed (%s): %s", context, exc)


def _enable_execution_after_bootstrap_supervised(*, context: str) -> bool:
    """Enable runtime execution after the supervised bootstrap handoff.

    Args:
        context: Diagnostic label appended to timeout and handshake logs.

    Returns:
        True when BootstrapFSM reaches RUNNING_SUPERVISED and execution flags are
        enabled. False when the supervised handoff does not complete in time.
    """
    try:
        from bot.trading_state_machine import (
            TradingState as _TSMState,
            get_state_machine as _get_tsm_unlock,
        )
    except ImportError:
        from trading_state_machine import (  # type: ignore[import]
            TradingState as _TSMState,
            get_state_machine as _get_tsm_unlock,
        )

    try:
        from bot.capital_flow_state_machine import (
            CapitalBootstrapState as _CapitalBootstrapState,
            get_capital_bootstrap_fsm as _get_capital_bootstrap_fsm_unlock,
        )
    except ImportError:
        try:
            from capital_flow_state_machine import (  # type: ignore[import]
                CapitalBootstrapState as _CapitalBootstrapState,
                get_capital_bootstrap_fsm as _get_capital_bootstrap_fsm_unlock,
            )
        except ImportError:
            _CapitalBootstrapState = None  # type: ignore[assignment]
            _get_capital_bootstrap_fsm_unlock = None  # type: ignore[assignment]

    if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
        # Give the thread-launch/supervisor handoff a short bounded window to
        # commit RUNNING_SUPERVISED before execution is enabled.
        _unlock_timeout_raw = os.getenv("NIJA_EXECUTION_UNLOCK_TIMEOUT_S", "15.0")
        try:
            _unlock_timeout_s = max(1.0, float(_unlock_timeout_raw))
        except ValueError:
            logger.warning(
                "Invalid NIJA_EXECUTION_UNLOCK_TIMEOUT_S=%r; using default 15.0s",
                _unlock_timeout_raw,
            )
            _unlock_timeout_s = 15.0

        def _bootstrap_unlock_ready() -> bool:
            try:
                _bfsm = _get_bootstrap_fsm()
                _state_obj = getattr(_bfsm, "state", None)
                _state = getattr(_state_obj, "value", "") if _state_obj is not None else ""
                _authority = bool(
                    _bfsm.has_execution_authority()
                    if hasattr(_bfsm, "has_execution_authority")
                    else getattr(_bfsm, "execution_authority", False)
                )
                return _state == "RUNNING_SUPERVISED" and _authority
            except Exception:
                return False

        if not _wait_for_predicate_with_timeout(
            predicate=_bootstrap_unlock_ready,
            timeout_s=_unlock_timeout_s,
            timeout_label="EXECUTION_ENABLE_WAITING_FOR_BOOTSTRAP_SUPERVISED",
            poll_interval_s=0.25,
        ):
            _last_bootstrap_state = "unknown"
            try:
                _last_bootstrap_state = getattr(_get_bootstrap_fsm().state, "value", "unknown")
            except Exception:
                pass
            logger.critical(
                "EXECUTION ENABLE BLOCKED: final bootstrap unlock never reached "
                "(timeout=%.2fs state=%s context=%s)",
                _unlock_timeout_s,
                _last_bootstrap_state,
                context,
            )
            return False

    _bootstrap_state_name = "UNAVAILABLE"
    if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
        try:
            _bfsm_unlock = _get_bootstrap_fsm()
            _bootstrap_state_name = getattr(_bfsm_unlock.state, "value", "unknown")
            _fsm_exec_authority = bool(
                _bfsm_unlock.has_execution_authority()
                if hasattr(_bfsm_unlock, "has_execution_authority")
                else getattr(_bfsm_unlock, "execution_authority", False)
            )
            if not (_bootstrap_state_name == "RUNNING_SUPERVISED" and _fsm_exec_authority):
                logger.critical(
                    "EXECUTION ENABLE BLOCKED: BootstrapFSM is not the active execution authority "
                    "(state=%s authority=%s context=%s)",
                    _bootstrap_state_name,
                    _fsm_exec_authority,
                    context,
                )
                return False
        except Exception:
            _bootstrap_state_name = "unknown"

    _tsm_unlock = _get_tsm_unlock()
    logger.info(
        "BOOTSTRAP EXECUTION UNLOCK CONFIRMED: bootstrap_state=%s trading_state=%s context=%s",
        _bootstrap_state_name,
        _tsm_unlock.get_current_state().value,
        context,
    )

    try:
        try:
            from bot.startup_coordinator import get_startup_coordinator as _get_startup_coordinator_unlock
        except ImportError:
            from startup_coordinator import get_startup_coordinator as _get_startup_coordinator_unlock  # type: ignore[import]
        _startup_coordinator_unlock = _get_startup_coordinator_unlock()
        _startup_coordinator_unlock.record_threads_confirmed_running(
            bootstrap_state=_bootstrap_state_name,
        )
        _startup_coordinator_unlock.record_activation_requested(
            requested=True,
            source=f"bootstrap_unlock:{context}",
        )
    except Exception as _startup_coord_err:
        logger.debug("Startup coordinator unlock handoff skipped (%s): %s", context, _startup_coord_err)

    if _get_capital_bootstrap_fsm_unlock is not None and _CapitalBootstrapState is not None:
        try:
            _capital_bootstrap_fsm = _get_capital_bootstrap_fsm_unlock()
            _capital_state_obj = getattr(_capital_bootstrap_fsm, "state", None)
            _capital_state_name = getattr(_capital_state_obj, "value", str(_capital_state_obj))
            if _capital_state_name != _CapitalBootstrapState.RUNNING.value:
                _capital_transition_ok = bool(
                    _capital_bootstrap_fsm.transition(
                        _CapitalBootstrapState.RUNNING,
                        f"execution unlock precondition ({context})",
                    )
                )
                _capital_state_obj = getattr(_capital_bootstrap_fsm, "state", None)
                _capital_state_name = getattr(_capital_state_obj, "value", str(_capital_state_obj))
                if not _capital_transition_ok and _capital_state_name != _CapitalBootstrapState.RUNNING.value:
                    logger.critical(
                        "EXECUTION ENABLE BLOCKED: CapitalBootstrapFSM failed to reach RUNNING "
                        "(state=%s context=%s)",
                        _capital_state_name,
                        context,
                    )
                    return False
            logger.critical(
                "CAPITAL BOOTSTRAP RUNNING CONFIRMED: state=%s context=%s",
                _capital_state_name,
                context,
            )
        except Exception as _capital_unlock_err:
            logger.critical(
                "EXECUTION ENABLE BLOCKED: CapitalBootstrapFSM RUNNING handoff failed "
                "(context=%s err=%s)",
                context,
                _capital_unlock_err,
            )
            return False

    # Keep the post-unlock balance floor at the runtime minimum ($1) so the
    # supervised handoff does not immediately re-block on the same guard.
    os.environ["MINIMUM_TRADING_BALANCE"] = _post_unlock_minimum_trading_balance

    try:
        _commit_timeout_raw = os.getenv("NIJA_EXECUTION_UNLOCK_COMMIT_TIMEOUT_S", "20.0")
        try:
            _commit_timeout_s = max(1.0, float(_commit_timeout_raw))
        except ValueError:
            _commit_timeout_s = 20.0
        _deadline = time.monotonic() + _commit_timeout_s

        while True:
            _current_state = _tsm_unlock.get_current_state()
            _tsm_live = _current_state == _TSMState.LIVE_ACTIVE
            _auth_snapshot = {}
            if hasattr(_tsm_unlock, "get_execution_authority_snapshot"):
                try:
                    _auth_snapshot = _tsm_unlock.get_execution_authority_snapshot() or {}
                except Exception:
                    _auth_snapshot = {}
            _converged = bool(_auth_snapshot.get("converged", False))
            _progress_state = str(_auth_snapshot.get("progress_state", "unknown"))

            if _converged or (
                _tsm_live
                and bool(_tsm_unlock.has_execution_authority())
                and bool(_tsm_unlock.can_dispatch_trades())
            ):
                break

            if hasattr(_tsm_unlock, "commit_activation"):
                try:
                    _tsm_unlock.commit_activation()
                except Exception as _commit_err:
                    logger.warning(
                        "Execution unlock commit_activation attempt failed (%s): %s",
                        context,
                        _commit_err,
                    )

            if _progress_state == "FAIL_SAFE" or time.monotonic() >= _deadline:
                logger.critical(
                    "EXECUTION ENABLE BLOCKED: TradingStateMachine activation not committed "
                    "(state=%s progress=%s context=%s timeout=%.2fs)",
                    _current_state.value,
                    _progress_state,
                    context,
                    _commit_timeout_s,
                )
                return False
            time.sleep(0.25)
    except Exception as _force_transition_err:
        logger.warning(
            "Force LIVE_ACTIVE transition failed after bootstrap unlock (%s): %s",
            context,
            _force_transition_err,
        )

    try:
        if hasattr(_tsm_unlock, "release_core_loop_ownership"):
            _tsm_unlock.release_core_loop_ownership(
                f"bootstrap unlock complete ({context})"
            )
    except Exception as _release_err:
        logger.warning(
            "Core loop ownership release handshake failed after bootstrap unlock (%s): %s",
            context,
            _release_err,
        )

    return True


def _verify_runtime_transition_states(*, context: str) -> None:
    """Fail closed unless runtime transitions reached RUNNING/RUNNING_SUPERVISED/LIVE_ACTIVE."""
    _bootstrap_state = _bootstrap_state_value()
    if _bootstrap_state != "RUNNING_SUPERVISED":
        raise RuntimeError(
            f"Transition verification failed ({context}): bootstrap_state={_bootstrap_state} "
            "expected=RUNNING_SUPERVISED"
        )

    _capital_state = "UNAVAILABLE"
    try:
        from bot.capital_flow_state_machine import get_capital_bootstrap_fsm as _get_capital_bootstrap_fsm_verify
    except ImportError:
        from capital_flow_state_machine import get_capital_bootstrap_fsm as _get_capital_bootstrap_fsm_verify  # type: ignore[import]

    try:
        _capital_state_obj = _get_capital_bootstrap_fsm_verify().state
        _capital_state = getattr(_capital_state_obj, "value", str(_capital_state_obj))
    except Exception as exc:
        raise RuntimeError(
            f"Transition verification failed ({context}): capital FSM state probe error: {exc}"
        ) from exc
    if _capital_state != "RUNNING":
        raise RuntimeError(
            f"Transition verification failed ({context}): capital_state={_capital_state} expected=RUNNING"
        )

    try:
        from bot.trading_state_machine import TradingState as _TSVerify, get_state_machine as _get_tsm_verify
    except ImportError:
        from trading_state_machine import TradingState as _TSVerify, get_state_machine as _get_tsm_verify  # type: ignore[import]

    _tsm_state = _get_tsm_verify().get_current_state()
    _tsm_state_name = getattr(_tsm_state, "value", str(_tsm_state))
    if _tsm_state != _TSVerify.LIVE_ACTIVE:
        raise RuntimeError(
            f"Transition verification failed ({context}): trading_state={_tsm_state_name} "
            "expected=LIVE_ACTIVE"
        )

    os.environ["NIJA_EXECUTION_ACTIVE"] = "1"
    logger.critical(
        "LIFECYCLE: EXECUTION_ACTIVE verified context=%s bootstrap=%s capital=%s trading=%s",
        context,
        _bootstrap_state,
        _capital_state,
        _tsm_state_name,
    )


def _launch_trading_threads(strategy, use_independent_trading: bool, hf_bot) -> tuple[dict, bool]:
    """Start trading threads and return (active_threads, use_independent_trading)."""
    _active_threads: dict = {}
    # Ensure RUNNING_SUPERVISED is reached if any threads were started.
    try:
        if use_independent_trading:
            logger.info("=" * 70)
            logger.info("🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE")
            logger.info("=" * 70)
            logger.info("   Each broker trades in its own self-healing daemon thread.")
            logger.info("   The supervisor restarts any thread that dies unexpectedly.")
            logger.info("=" * 70)

            # Detect funded platform brokers
            _funded = strategy.independent_trader.detect_funded_brokers()
            _broker_source = strategy.independent_trader._get_platform_broker_source()

            # Register all platform brokers with the failure manager
            try:
                if strategy.independent_trader.broker_failure_manager and _broker_source:
                    _equal_alloc = 1.0 / max(len(_broker_source), 1)
                    for _bt, _br in _broker_source.items():
                        strategy.independent_trader.broker_failure_manager.register_broker(
                            _bt.value, initial_allocation=_equal_alloc
                        )
                    strategy.independent_trader.broker_failure_manager.log_active_dead_banner()
            except Exception as _reg_err:
                logger.debug("Failure manager registration skipped: %s", _reg_err)

            # Start a self-healing thread for each funded, connected platform broker
            _platform_stagger = 0
            for _broker_type, _broker in _broker_source.items():
                _bname = _broker_type.value
                if _bname not in _funded:
                    logger.info("   ⏭️  %s — not funded, skipping", _bname.upper())
                    continue
                if not _broker.connected:
                    logger.warning("   ⚠️  %s — not connected, skipping", _bname.upper())
                    continue
                # Stagger starts to prevent simultaneous API bursts
                if _platform_stagger > 0:
                    logger.info(
                        "   ⏳ Staggering: 10s before starting %s…", _bname.upper()
                    )
                    time.sleep(10)
                _t, _sf = _start_trader_thread(
                    strategy.independent_trader, _broker_type, _broker
                )
                _active_threads[_bname] = {
                    "thread": _t,
                    "stop_flag": _sf,
                    "broker_type": _broker_type,
                    "broker": _broker,
                    "mode": "platform",
                }
                logger.info(
                    "   ✅ Self-healing trader thread started for %s", _bname.upper()
                )
                _platform_stagger += 1

            # Start user broker threads (individually wrapped for self-healing)
            try:
                _funded_users = strategy.independent_trader.detect_funded_user_brokers()
            except Exception as _fu_err:
                logger.warning("Could not detect funded user brokers: %s", _fu_err)
                _funded_users = {}

            if _funded_users and strategy.multi_account_manager:
                logger.info("=" * 70)
                logger.info("👤 STARTING USER BROKER THREADS")
                logger.info("=" * 70)
                for _uid, _user_brokers in strategy.multi_account_manager.user_brokers.items():
                    if _uid not in _funded_users:
                        continue
                    for _ubt, _ubr in _user_brokers.items():
                        _ubname = f"{_uid}_{_ubt.value}"
                        # Respect user-mode policy from IndependentBrokerTrader.
                        # This auto-promotes to independent when copy trading is inactive.
                        if not strategy.independent_trader.should_start_user_independent_thread(_uid):
                            logger.info(
                                "   ⏭️  %s — copy trading active and independent_trading not enabled", _ubname
                            )
                            continue
                        if _ubt.value not in _funded_users.get(_uid, {}):
                            continue
                        if not _ubr.connected:
                            logger.warning(
                                "   ⚠️  %s — not connected, skipping", _ubname
                            )
                            continue
                        _user_sf = threading.Event()
                        _user_t = threading.Thread(
                            target=strategy.independent_trader.run_user_broker_trading_loop,
                            args=(_uid, _ubt, _ubr, _user_sf),
                            name=f"Trader-{_ubname}",
                            daemon=True,
                        )
                        _user_t.start()
                        _active_threads[_ubname] = {
                            "thread": _user_t,
                            "stop_flag": _user_sf,
                            "broker_type": _ubt,
                            "broker": _ubr,
                            "mode": "user",
                            "user_id": _uid,
                        }
                        logger.info("   ✅ User trader thread started: %s", _ubname)

            if not _active_threads:
                logger.warning(
                    "⚠️  No funded/connected brokers — falling back to single-broker mode"
                )
                use_independent_trading = False

            # Start connection monitor for brokers that couldn't connect at boot
            try:
                strategy.independent_trader.start_connection_monitor()
            except Exception as _cm_err:
                logger.debug("Connection monitor start skipped: %s", _cm_err)

        if not use_independent_trading:
            # Single-broker fallback: run strategy.run_cycle() in a self-healing thread
            _hf_cycle_secs = hf_bot.get_cycle_interval() if hf_bot is not None else 150
            _hf_label = (
                f"HF scalping ({_hf_cycle_secs}s)"
                if (hf_bot is not None and hf_bot.enabled)
                else "2.5 minute"
            )
            logger.info(
                "🚀 Starting single-broker trading thread (%s cadence)…", _hf_label
            )
            _t, _sf = _start_single_broker_thread(strategy, _hf_cycle_secs)
            _active_threads["__single_broker__"] = {
                "thread": _t,
                "stop_flag": _sf,
                "broker_type": None,
                "broker": None,
                "mode": "single",
            }
            logger.info("   ✅ Self-healing single-broker thread started")
    finally:
        _ensure_running_supervised(_active_threads, context="threads live (post-start)")

    try:
        try:
            from bot.startup_coordinator import get_startup_coordinator as _get_startup_coordinator_launch
        except ImportError:
            from startup_coordinator import get_startup_coordinator as _get_startup_coordinator_launch  # type: ignore[import]
        _get_startup_coordinator_launch().record_threads_launched(len(_active_threads))
    except Exception as _coord_err:
        logger.debug("Startup coordinator thread-launch update skipped: %s", _coord_err)
    return _active_threads, use_independent_trading


def _emit_startup_orchestration_snapshot(context: str) -> None:
    """Emit a single authoritative startup snapshot for diagnostics."""
    try:
        from bot.startup_event_buffer import StartupSnapshot
    except ImportError:
        try:
            from startup_event_buffer import StartupSnapshot  # type: ignore[import]
        except ImportError:
            StartupSnapshot = None  # type: ignore[assignment]

    runtime_mode = resolve_runtime_mode()
    bootstrap_state = "UNAVAILABLE"
    if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
        try:
            _bfsm = _get_bootstrap_fsm()
            bootstrap_state = getattr(_bfsm.state, "value", str(_bfsm.state))
        except Exception:
            bootstrap_state = "ERROR"

    gate_ready = _rt_is_ready()
    gate_detail = "" if gate_ready else f"pending={_rt_pending()}"
    readiness_proof_detail = "unavailable"
    readiness_first_blocker = "unknown"
    try:
        try:
            from bot.startup_coordinator import get_startup_coordinator as _get_startup_coordinator_diag
        except ImportError:
            from startup_coordinator import get_startup_coordinator as _get_startup_coordinator_diag  # type: ignore[import]
        _coordinator_diag = _get_startup_coordinator_diag()
        _proof_snapshot = _coordinator_diag.build_snapshot(
            trading_state="UNKNOWN",
            activation_intent=bool(runtime_mode.is_live),
        )
        _proof = _coordinator_diag.evaluate_system_readiness_proof(_proof_snapshot)
        readiness_first_blocker = _proof.first_blocking_gate
        readiness_proof_detail = (
            f"passed={_proof.passed} blocker={_proof.first_blocking_gate} "
            f"version={_proof.proof_version} epoch={_proof.global_epoch}"
        )
    except Exception as _proof_exc:
        readiness_proof_detail = f"error={_proof_exc}"

    env_flags = {
        "AUTO_ACTIVATE": os.getenv("AUTO_ACTIVATE", "false"),
        "HEARTBEAT_TRADE": os.getenv("HEARTBEAT_TRADE", "false"),
        "HEARTBEAT_REQUIRED_FIRST_ACTIVATION": os.getenv("HEARTBEAT_REQUIRED_FIRST_ACTIVATION", "false"),
        "FORCE_LIVE_TRANSITION": os.getenv("FORCE_LIVE_TRANSITION", "false"),
    }

    if StartupSnapshot is None:
        logger.info(
            "STARTUP SNAPSHOT (%s) bootstrap_state=%s gate_ready=%s proof_first_blocker=%s proof=%s runtime_mode=%s env=%s",
            context,
            bootstrap_state,
            gate_ready,
            readiness_first_blocker,
            readiness_proof_detail,
            runtime_mode.as_dict(),
            env_flags,
        )
        return

    snap = StartupSnapshot("Startup Orchestration")
    snap.record("bootstrap_state", bootstrap_state == "RUNNING_SUPERVISED", detail=bootstrap_state)
    if gate_ready is None:
        snap.record("readiness_gate", True, detail="unavailable")
    else:
        snap.record("readiness_gate", bool(gate_ready), detail=gate_detail)
    snap.record(
        "system_readiness_proof",
        "passed=True" in readiness_proof_detail,
        detail=readiness_proof_detail,
    )
    snap.record("first_blocking_gate", readiness_first_blocker == "none", detail=readiness_first_blocker)
    mode_detail = f"mode={runtime_mode.mode} source={runtime_mode.source}"
    if runtime_mode.conflicts:
        mode_detail = f"{mode_detail} conflicts={','.join(runtime_mode.conflicts)}"
    snap.record("runtime_mode", not runtime_mode.conflicts, detail=mode_detail)
    live_detail = (
        f"lcv={runtime_mode.raw.get('LIVE_CAPITAL_VERIFIED')} "
        f"live_trading={runtime_mode.raw.get('LIVE_TRADING')}"
    )
    snap.record("live_flags", True, detail=live_detail)
    for flag_name, flag_val in env_flags.items():
        snap.record(flag_name.lower(), True, detail=flag_val)
    snap.emit(logger, level=logging.CRITICAL)


def _capital_bootstrap_state_value() -> str:
    """Return capital bootstrap FSM state value, or 'UNAVAILABLE' if import fails."""
    try:
        from bot.capital_flow_state_machine import get_capital_bootstrap_fsm as _get_cbfsm
    except ImportError:
        try:
            from capital_flow_state_machine import get_capital_bootstrap_fsm as _get_cbfsm  # type: ignore[import]
        except ImportError:
            return "UNAVAILABLE"
    try:
        return str(_get_cbfsm().state.value)
    except Exception:
        return "UNAVAILABLE"


def _bootstrap_nonce_reset_once() -> None:
    """Bootstrap-owned nonce reset gate (single execution, post-READY only).

    Deterministic nonce kernel: bootstrap nonce mutations are disabled.
    Runtime nonce issuance is exclusively delegated to DistributedNonceManager.
    """
    if not _is_bootstrap_owner_thread():
        logger.debug("NONCE_BOOTSTRAP_SKIP non-owner thread attempted bootstrap nonce reset")
        return

    global _nonce_bootstrap_jump_done
    with _nonce_bootstrap_jump_lock:
        if _nonce_bootstrap_jump_done:
            logger.debug(
                "NONCE BOOTSTRAP guard: nonce jump already completed in this process"
            )
            return
        _nonce_bootstrap_jump_done = True

    logger.info(
        "NONCE_BOOTSTRAP_SKIP deterministic nonce kernel active — "
        "bootstrap nonce jump disabled; nonce issuance delegated to DistributedNonceManager"
    )

# B1 bootstrap phase execution guard — prevents B1 pre-flight from running twice.
# The single-owner bootstrap kernel (BotStartup thread) sets this the first time
# B1 runs.  Any subsequent code path that would re-run B1 checks this flag first
# and skips directly to B2 when it is already True.  This is the module-level
# equivalent of ``if getattr(self, "_b1_executed", False): return B2``.
_b1_executed: bool = False
_b1_executed_lock = threading.Lock()

# State machine loop thread — started once after INIT completes.
# Runs a periodic health check that fires maybe_auto_activate() if the
# state machine is stuck in OFF while CapitalAuthority is ready.
_sm_loop_thread = None  # type: threading.Thread | None
_sm_loop_lock = threading.Lock()


@dataclass
class _ExternalWatchdogRestartState:
    requested: bool = False
    reason: str = ""


_external_watchdog_restart = _ExternalWatchdogRestartState()
_external_watchdog_restart_lock = threading.Lock()


def _request_external_watchdog_restart(reason: str) -> None:
    """Flag that the main supervisor must exit for an external watchdog restart."""
    with _external_watchdog_restart_lock:
        _external_watchdog_restart.requested = True
        _external_watchdog_restart.reason = str(reason)


def _consume_external_watchdog_restart_reason() -> str:
    """Return pending external-restart reason and clear the pending flag."""
    with _external_watchdog_restart_lock:
        if not _external_watchdog_restart.requested:
            return ""
        reason = str(_external_watchdog_restart.reason).strip()
        _external_watchdog_restart.requested = False
        _external_watchdog_restart.reason = ""
        return reason


def _is_fatal_nonce_restart_error(exc: Exception) -> bool:
    """Return True for fatal nonce RuntimeErrors that must be externally restarted.

    Triggers on:
      - ``RuntimeError: nonce not authorized``
      - ``RuntimeError: Invalid nonce spike detected``

    These indicate nonce state/auth desync that should not be retried in-process.
    Exiting lets the external watchdog restart with a clean runtime state.
    """
    if not isinstance(exc, RuntimeError):
        return False
    msg = str(exc).lower()
    return (
        "nonce not authorized" in msg
        or "invalid nonce spike detected" in msg
    )

# Import broker types for error reporting
try:
    from bot.broker_manager import BrokerType
except ImportError:
    # Fallback if running from different directory
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    from broker_manager import BrokerType

# Constants for error formatting
# Separator length of 63 matches the width of the error message
# "🚨 KRAKEN MASTER CREDENTIALS ARE SET BUT CONNECTION FAILED" (61 chars + 2 spaces padding)
ERROR_SEPARATOR = "═" * 63

# Configuration error heartbeat interval (seconds)
# When configuration errors prevent trading, the bot stays alive to report status
# and updates its heartbeat at this interval
CONFIG_ERROR_HEARTBEAT_INTERVAL = 60

# Heartbeat update interval (seconds) for Railway health check responsiveness
# Background thread updates heartbeat at this frequency to ensure health checks
# always get fresh data (Railway checks every ~30s, this is faster)
HEARTBEAT_INTERVAL_SECONDS = 10

# Keep-alive loop sleep interval (seconds)
# When trading loops exit, the keep-alive loop sleeps for this duration between status logs
# Note: Heartbeat is updated by dedicated background thread, not by this loop
KEEP_ALIVE_SLEEP_INTERVAL_SECONDS = 300

# Synthetic price used only for startup market-readiness probe.
_MARKET_GATE_PROBE_PRICE = 100.0

# EMERGENCY STOP CHECK
# Note: Uses print() instead of logger because logger is not yet initialized
if os.path.exists('EMERGENCY_STOP'):
    print("\n" + "┏" + "━" * 78 + "┓")
    print("┃ 🚨 EXIT POINT - EMERGENCY STOP FILE DETECTED                             ┃")
    print(f"┃ Exit Code: {0:<67} ┃")
    print(f"┃ PID: {os.getpid():<71} ┃")
    print("┣" + "━" * 78 + "┫")
    print("┃ Bot is disabled. See EMERGENCY_STOP file for details.                   ┃")
    print("┃ Delete EMERGENCY_STOP file to resume trading.                           ┃")
    print("┃ This is an intentional shutdown (not a crash).                          ┃")
    print("┗" + "━" * 78 + "┛")
    print("")
    sys.exit(0)

# ── Process lock — prevent multiple bot instances ─────────────────────────────
# Only ONE process should ever touch the Kraken API key.  A second instance
# would generate its own nonce sequence, immediately desyncing from the first
# and producing continuous "EAPI:Invalid nonce" errors on both.
_PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "nija.pid")

# Keywords that identify a NIJA bot process in /proc/<pid>/cmdline.
# Used to distinguish a genuinely-running duplicate from PID reuse in a new container.
_NIJA_CMDLINE_MARKERS = (
    "bot.py", "trading_strategy.py", "nija_core_loop.py",
    "tradingview_webhook.py",
)


def _is_nija_process(pid: int) -> bool:
    """Return True only when *pid* belongs to a NIJA bot process.

    Reads ``/proc/<pid>/cmdline`` (Linux) and checks for known NIJA entry-point
    names.  Falls back to ``True`` (conservative / block startup) when the proc
    filesystem is unavailable so the existing safety guarantee is preserved on
    non-Linux platforms.
    """
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as _cf:
            cmdline = _cf.read().replace(b"\x00", b" ").decode("utf-8", errors="replace")
        return any(marker in cmdline for marker in _NIJA_CMDLINE_MARKERS)
    except (FileNotFoundError, ProcessLookupError):
        # PID disappeared between os.kill check and /proc read — treat as gone.
        return False
    except (PermissionError, OSError):
        # /proc unavailable or not accessible — fall back to conservative assumption.
        return True


def _read_pid_file_meta(path: str) -> dict:
    """Read JSON metadata written on line 2+ of *path* (empty dict on any error)."""
    try:
        with open(path, "r", encoding="utf-8") as _mf:
            lines = [ln.strip() for ln in _mf.readlines() if ln.strip()]
        if len(lines) >= 2:
            return json.loads(lines[1])
    except Exception:
        pass
    return {}
_distributed_writer_lock_client = None
_distributed_writer_lock_key = ""
_distributed_writer_lock_meta_key = ""
_distributed_writer_lock_token = ""
_distributed_writer_fencing_key = ""
_distributed_writer_fencing_token = 0
_distributed_writer_lock_stop = threading.Event()
_distributed_writer_lock_thread = None
_running_in_degraded_mode = False  # True if bot runs without Redis distributed lock safety
os.environ.setdefault("NIJA_WRITER_LEASE_ACQUIRED", "0")
os.environ.setdefault("NIJA_WRITER_HEARTBEAT_ACTIVE", "0")
os.environ.setdefault("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "0")


def _writer_lock_scope() -> str:
    """Return a stable, non-secret scope id for the current Kraken key."""
    _raw = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
        or "default"
    )
    return hashlib.sha256(_raw.encode("utf-8")).hexdigest()[:16]


def _is_multi_instance_deployment_possible() -> bool:
    """Best-effort detection that deployment may run multiple concurrent instances."""
    _truthy = {"1", "true", "yes", "on", "enabled"}
    if os.environ.get("NIJA_MULTI_INSTANCE_POSSIBLE", "").strip().lower() in _truthy:
        return True

    # Operator override for confirmed singleton deployments.
    # This is intentionally lower precedence than NIJA_MULTI_INSTANCE_POSSIBLE.
    if os.environ.get("NIJA_ASSUME_SINGLE_INSTANCE", "").strip().lower() in _truthy:
        return False

    for _var in ("K_SERVICE", "DYNO"):
        if os.environ.get(_var, "").strip():
            return True

    try:
        if int(os.environ.get("WEB_CONCURRENCY", "1") or "1") > 1:
            return True
    except (TypeError, ValueError):
        pass

    try:
        if int(os.environ.get("NIJA_EXPECTED_INSTANCES", "1") or "1") > 1:
            return True
    except (TypeError, ValueError):
        pass

    return False


def _release_distributed_process_lock() -> None:
    """Release distributed single-writer lock iff this process still owns it."""
    global _distributed_writer_lock_client
    global _distributed_writer_lock_key, _distributed_writer_lock_meta_key, _distributed_writer_lock_token
    global _distributed_writer_fencing_key, _distributed_writer_fencing_token
    if not _distributed_writer_lock_client or not _distributed_writer_lock_key or not _distributed_writer_fencing_token:
        return
    try:
        _client = _distributed_writer_lock_client
        _client.eval(
            """
            local current = redis.call('GET', KEYS[1])
            if not current then
                return 0
            end
            local sep = string.find(current, ':', 1, true)
            local token = current
            if sep then
                token = string.sub(current, 1, sep - 1)
            end
            if token == ARGV[1] then
                local deleted = redis.call('DEL', KEYS[1])
                if KEYS[2] and KEYS[2] ~= '' then
                    redis.call('DEL', KEYS[2])
                end
                return deleted
            end
            return 0
            """,
            2,
            _distributed_writer_lock_key,
            _distributed_writer_lock_meta_key,
            str(_distributed_writer_fencing_token),
        )
    except Exception:
        pass
    finally:
        _distributed_writer_lock_client = None
        _distributed_writer_lock_key = ""
        _distributed_writer_lock_meta_key = ""
        _distributed_writer_lock_token = ""
        _distributed_writer_fencing_key = ""
        _distributed_writer_fencing_token = 0
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"


def _release_nonce_writer_lease() -> None:
    """Release the Redis nonce writer lease for the platform Kraken key."""
    platform_key = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
    )
    if not platform_key:
        return
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
        if get_distributed_nonce_manager().release_writer_lease(key_id):
            logger.info("✅ Released Redis nonce writer lease for key_id=%s", key_id)
    except Exception as exc:
        logger.debug("Nonce lease release skipped: %s", exc)


def _build_writer_lock_meta_payload(
    fencing_token: int,
    instance_identity: dict[str, str],
    *,
    acquired_at: float,
    heartbeat_at: float,
) -> str:
    """Return JSON metadata mirrored beside the distributed writer lock."""
    return json.dumps(
        {
            "token": str(fencing_token),
            "instance": instance_identity,
            "acquired_at": acquired_at,
            "heartbeat_at": heartbeat_at,
        },
        sort_keys=True,
    )


def _distributed_writer_lock_heartbeat(ttl_s: int) -> None:
    """Keep the distributed writer lock alive; fail closed if ownership is lost.

    The heartbeat Lua script now returns three distinct codes:
      1  — lock still held by this process and TTL successfully refreshed.
     -1  — lock key was missing (expired due to transient Redis outage); safe
            to re-acquire with NX because no other writer holds it.
      0  — lock key held by a different token; another writer has taken over —
            hard exit to preserve the single-writer invariant.

    When the key is missing (-1) the heartbeat attempts a single NX SET to
    re-acquire the lock with the original fencing token.  If that succeeds the
    heartbeat continues transparently.  If another process wins the NX race the
    heartbeat exits immediately (same as the wrong-token path).

    ``NIJA_WRITER_HEARTBEAT_ALIVE_TS`` is updated on every loop iteration
    (including failure iterations) so callers can detect a dead thread versus a
    thread that is alive but temporarily unable to reach Redis.
    """
    _interval = max(3, ttl_s // 3)
    _now_ts = str(time.time())
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
    os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = _now_ts
    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = _now_ts
    try:
        _max_failures = max(3, int(os.environ.get("NIJA_WRITER_LOCK_HEARTBEAT_MAX_FAILURES", "12")))
    except (TypeError, ValueError):
        _max_failures = 12
    _failure_streak = 0
    while not _distributed_writer_lock_stop.wait(_interval):
        # Update alive TS on every iteration so authority checks can distinguish
        # "thread dead" from "thread alive but Redis temporarily unreachable".
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = str(time.time())
        try:
            if _distributed_writer_lock_client is None:
                raise RuntimeError("distributed writer lock client became None")

            _result = _distributed_writer_lock_client.eval(
                """
                local current = redis.call('GET', KEYS[1])
                if not current then
                    return -1
                end
                local sep = string.find(current, ':', 1, true)
                local token = current
                if sep then
                    token = string.sub(current, 1, sep - 1)
                end
                if token == ARGV[1] then
                    local lock_refreshed = redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
                    if KEYS[2] and KEYS[2] ~= '' then
                        redis.call('SET', KEYS[2], ARGV[3], 'EX', tonumber(ARGV[2]))
                    end
                    return lock_refreshed
                end
                return 0
                """,
                2,
                _distributed_writer_lock_key,
                _distributed_writer_lock_meta_key,
                str(_distributed_writer_fencing_token),
                str(ttl_s),
                _build_writer_lock_meta_payload(
                    _distributed_writer_fencing_token,
                    current_instance_identity(),
                    acquired_at=float(os.environ.get("NIJA_WRITER_LOCK_ACQUIRED_AT", "0") or 0.0),
                    heartbeat_at=time.time(),
                ),
            )
            _result_code = int(_result or 0)
            if _result_code == 1:
                # Lock refreshed successfully.
                _failure_streak = 0
                os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = str(time.time())
            elif _result_code == -1:
                # Lock key is missing — it expired due to a transient Redis
                # outage while the heartbeat was failing.  Attempt re-acquisition
                # using the same fencing token and NX so the operation is atomic.
                _reacquired = _distributed_writer_lock_client.set(
                    _distributed_writer_lock_key,
                    _distributed_writer_lock_token,
                    ex=ttl_s,
                    nx=True,
                )
                if _reacquired:
                    try:
                        _distributed_writer_lock_client.set(
                            _distributed_writer_lock_meta_key,
                            _build_writer_lock_meta_payload(
                                _distributed_writer_fencing_token,
                                current_instance_identity(),
                                acquired_at=float(os.environ.get("NIJA_WRITER_LOCK_ACQUIRED_AT", "0") or 0.0),
                                heartbeat_at=time.time(),
                            ),
                            ex=ttl_s,
                        )
                    except Exception:
                        pass
                    _failure_streak = 0
                    _reacq_ts = str(time.time())
                    os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = _reacq_ts
                    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = _reacq_ts
                    print(
                        "⚠️ Distributed writer lock had expired (transient Redis outage); "
                        "successfully re-acquired with same fencing token.",
                        flush=True,
                    )
                    logger.warning(
                        "WRITER LOCK RE-ACQUIRED: lock had expired (transient outage) and was "
                        "re-acquired atomically. fencing_token=%s lock_key=%s",
                        _distributed_writer_fencing_token,
                        _distributed_writer_lock_key,
                    )
                else:
                    # Another process acquired the lock while ours was expired.
                    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
                    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
                    print(
                        "\n🚫 Distributed writer lock expired and another process re-acquired it; "
                        "exiting for safety.",
                        flush=True,
                    )
                    _distributed_writer_lock_stop.set()
                    _release_distributed_process_lock()
                    os._exit(1)
            else:
                # _result_code == 0: lock is held by a different token — another
                # writer has taken over.  Hard exit to preserve single-writer safety.
                os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
                os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
                print(
                    "\n🚫 Distributed single-writer lock lost; "
                    "another NIJA writer may be active. Exiting for safety.",
                    flush=True,
                )
                _distributed_writer_lock_stop.set()
                _release_distributed_process_lock()
                os._exit(1)
        except Exception as _hb_exc:
            _failure_streak += 1
            if _failure_streak == 1 or _failure_streak % 3 == 0:
                print(
                    "⚠️ Distributed lock heartbeat error "
                    f"streak={_failure_streak}/{_max_failures} ({_hb_exc})",
                    flush=True,
                )
            if _failure_streak >= _max_failures:
                os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
                os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
                print(
                    f"\n🚫 Distributed lock heartbeat failed {_failure_streak}x ({_hb_exc}); "
                    "exiting to preserve single-writer invariant.",
                    flush=True,
                )
                _distributed_writer_lock_stop.set()
                _release_distributed_process_lock()
                os._exit(1)
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"


def _acquire_distributed_process_lock() -> None:
    """Acquire cross-deployment fenced single-writer lock via Redis when configured."""
    global _distributed_writer_lock_client
    global _distributed_writer_lock_key, _distributed_writer_lock_token
    global _distributed_writer_fencing_key, _distributed_writer_fencing_token
    global _distributed_writer_lock_thread
    global _running_in_degraded_mode

    os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
    _truthy = ("1", "true", "yes", "enabled", "on")
    _standby_retry_active = os.environ.get("NIJA_STANDBY_RETRY_ACTIVE", "0").strip() == "1"
    try:
        _standby_retry_count = int(os.environ.get("NIJA_STANDBY_RETRY_COUNT", "0") or "0")
    except (TypeError, ValueError):
        _standby_retry_count = 0

    def _is_nonrecoverable_redis_config_error(_reason: str) -> bool:
        _reason_lc = str(_reason or "").lower()
        return any(
            _token in _reason_lc
            for _token in (
                "endpoint responded as http/non-redis",
                "must not include wrapping quotes",
                "contains leading or trailing whitespace",
                "redis url not configured while distributed single-writer lock is required",
                "is not a valid redis connection url",
            )
        )

    def _enter_fail_closed_standby(_reason: str) -> None:
        """Block startup safely and retry lock acquisition instead of crash-looping."""
        nonlocal _standby_retry_count
        if not _require_lock:
            print(
                "⚠️ Fail-closed standby skipped because distributed writer lock is optional in this mode.",
                flush=True,
            )
            print(f"   Lock error: {_reason}", flush=True)
            return
        _reason_lc = str(_reason or "").lower()
        _retry_enabled = os.environ.get(
            "NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE", "true"
        ).strip().lower() in _truthy
        if not _retry_enabled:
            print("❌ FAILED TO ACQUIRE WRITER LOCK", flush=True)
            print(f"❌ Failed to acquire distributed single-writer lock: {_reason}")
            print("   Exiting fail-closed to preserve one-writer invariant.")
            sys.exit(1)

        _retry_sleep_raw = os.environ.get(
            "NIJA_FAIL_CLOSED_RETRY_INTERVAL_S", "5"
        ).strip()
        _degraded_mode_requested = os.environ.get(
            "NIJA_RUNTIME_DEGRADED_MODE", "0"
        ).strip() == "1"
        _default_max_retry_attempts = "0" if _degraded_mode_requested else ("12" if _live_mode else "0")
        _max_retry_attempts_raw = os.environ.get(
            "NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS", _default_max_retry_attempts
        ).strip()
        try:
            _retry_sleep_s = max(5.0, float(_retry_sleep_raw or "5"))
        except (TypeError, ValueError):
            _retry_sleep_s = 5.0
        try:
            _max_retry_attempts = max(0, int(_max_retry_attempts_raw or "0"))
        except (TypeError, ValueError):
            _max_retry_attempts = 0
        if _live_mode and _require_lock and not _unsafe_bypass and _max_retry_attempts <= 0:
            _max_retry_attempts = 12
            os.environ["NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS"] = "12"
            print(
                "⚠️ Live lock-required mode forbids infinite standby retries in fail-closed mode; "
                "forcing NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS=12.",
                flush=True,
            )
        print("❌ FAILED TO ACQUIRE WRITER LOCK", flush=True)
        print(f"❌ Failed to acquire distributed single-writer lock: {_reason}")
        print(
            "🛑 FAIL-CLOSED STANDBY ACTIVE: trading remains blocked until writer lock is acquired."
        )
        print(
            f"   Retrying distributed lock acquisition every {_retry_sleep_s:.0f}s "
            "until acquired (set NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE=false to exit instead)."
        )
        if _max_retry_attempts > 0:
            print(
                "   Standby retry cap enabled: "
                f"NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS={_max_retry_attempts}. "
                "Startup will exit 1 after the cap is reached."
            )
        else:
            print(
                "   Standby retry cap disabled: "
                "set NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS>0 to stop infinite retries."
            )
        print(
            "   DIAGNOSTIC STEPS:"
            "\n     1. Verify Redis URL scheme:  rediss:// for Railway proxy, redis:// for local"
            "\n     2. Test connectivity:         redis-cli -h <host> -p <port> -a \"$REDIS_PASSWORD\" --tls --insecure ping"
            "\n     3. Check Railway service:     Redis service must show Running in Railway dashboard"
            "\n     4. Check for conflicting env: REDIS_URL / REDIS_PRIVATE_URL / REDIS_TLS_URL"
            "\n     5. Single-instance bypass:    set NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true (UNSAFE)"
        )

        _is_nonrecoverable_config_error = _is_nonrecoverable_redis_config_error(_reason)
        _retry_on_nonrecoverable = os.environ.get(
            "NIJA_FAIL_CLOSED_RETRY_ON_NONRECOVERABLE_REDIS_ERROR", "false"
        ).strip().lower() in _truthy
        if _is_nonrecoverable_config_error and not _retry_on_nonrecoverable:
            print(
                "❌ Non-recoverable Redis configuration error detected; "
                "exiting immediately instead of retrying standby loop."
            )
            print(
                "   Set NIJA_FAIL_CLOSED_RETRY_ON_NONRECOVERABLE_REDIS_ERROR=true "
                "to keep retrying anyway."
            )
            sys.exit(1)

        _default_exit_on_unreachable = "true" if _live_mode else "false"
        _exit_on_unreachable = os.environ.get(
            "NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS", _default_exit_on_unreachable
        ).strip().lower() in _truthy
        _preflight_timeout_raw = os.environ.get(
            "NIJA_FAIL_CLOSED_REDIS_PREFLIGHT_TIMEOUT_S", "3"
        ).strip()
        try:
            _preflight_timeout_s = min(max(float(_preflight_timeout_raw or "3"), 0.5), 15.0)
        except (TypeError, ValueError):
            _preflight_timeout_s = 3.0
        _connectivity_reason = any(
            _token in _reason_lc
            for _token in (
                "timeout",
                "unreachable",
                "connection reset",
                "connection refused",
                "network",
                "no route",
                "handshake",
                "ssl",
            )
        )
        if _exit_on_unreachable and _connectivity_reason and _redis_url:
            print("❌ Redis startup preflight failed: endpoint unreachable")
            print(f"   Redis source: {_redis_url_source or 'NIJA_REDIS_URL'}")
            print(f"   Probe timeout: {_preflight_timeout_s:.2f}s")
            print(f"   Probe error: {_reason}")
            print("   Exiting immediately due to NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS=true")
            sys.exit(1)

        os.environ["NIJA_STANDBY_RETRY_ACTIVE"] = "1"

        while True:
            if _max_retry_attempts > 0 and _standby_retry_count >= _max_retry_attempts:
                print(
                    "❌ FAIL-CLOSED STANDBY RETRY CAP REACHED: "
                    f"attempts={_standby_retry_count} "
                    f"max={_max_retry_attempts}. Exiting with code 1."
                )
                sys.exit(1)
            print("⏳ Waiting for Redis lock...", flush=True)
            time.sleep(_retry_sleep_s)
            _standby_retry_count += 1
            _next_retry_count = _standby_retry_count
            os.environ["NIJA_STANDBY_RETRY_COUNT"] = str(_next_retry_count)
            print(
                "🔁 Retrying distributed writer lock acquisition... "
                f"(attempt {_next_retry_count})"
            )
            try:
                _acquire_distributed_process_lock()
                os.environ.pop("NIJA_STANDBY_RETRY_ACTIVE", None)
                os.environ.pop("NIJA_STANDBY_RETRY_COUNT", None)
                print("✅ Distributed writer lock recovered; leaving fail-closed standby.")
                return
            except SystemExit as _standby_exit:
                if str(getattr(_standby_exit, "code", "1")) == "1":
                    continue
                raise
            except Exception as _standby_exc:
                _msg = str(_standby_exc).splitlines()[0] if str(_standby_exc) else type(_standby_exc).__name__
                if _is_nonrecoverable_redis_config_error(_msg) and not _retry_on_nonrecoverable:
                    print(
                        "❌ Non-recoverable Redis configuration error persisted during standby retry; "
                        "exiting immediately."
                    )
                    sys.exit(1)
                print(f"⚠️ Retry failed: {_msg}")

    _live_mode = os.environ.get("LIVE_CAPITAL_VERIFIED", "").strip().lower() in _truthy
    _strict_lock_alias = os.environ.get("STRICT_REDIS_WRITER_LOCK", "").strip().lower() in _truthy
    _require_lock_env = os.environ.get("NIJA_REQUIRE_DISTRIBUTED_LOCK", "").strip().lower()
    _require_lock_from_env = _require_lock_env in _truthy
    _single_instance_assumed = os.environ.get("NIJA_ASSUME_SINGLE_INSTANCE", "").strip().lower() in _truthy
    _require_lock = _require_lock_from_env or _strict_lock_alias
    _multi_instance_possible = _is_multi_instance_deployment_possible()
    if _multi_instance_possible:
        _require_lock = True
    _disable_writer_lock_alias = os.environ.get("NIJA_DISABLE_WRITER_LOCK", "").strip().lower() in _truthy
    _unsafe_bypass = (
        os.environ.get("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", "").strip().lower() in _truthy
        or _disable_writer_lock_alias
    )
    _single_instance_lock_opt_out = (
        _live_mode
        and _single_instance_assumed
        and not _multi_instance_possible
        and not _require_lock_from_env
        and not _strict_lock_alias
    )

    if _live_mode and not _single_instance_lock_opt_out:
        _require_lock = True
    elif _single_instance_lock_opt_out:
        print(
            "⚠️ Single-instance live mode detected with NIJA_REQUIRE_DISTRIBUTED_LOCK disabled; "
            "distributed writer lock is optional by operator choice.",
            flush=True,
        )
        print(
            "   Keep only one NIJA instance active for this API key.",
            flush=True,
        )

    if _live_mode:
        if _unsafe_bypass:
            _require_lock = False
            if _disable_writer_lock_alias:
                print("🚨 UNSAFE MODE: NIJA_DISABLE_WRITER_LOCK=1 alias enabled.")
            print("🚨 UNSAFE MODE: NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true in LIVE mode.")
            print("   Distributed single-writer safety is DISABLED by explicit operator override.")
            print("   Use only when you are certain exactly one container/process can run.")

    if _multi_instance_possible and _unsafe_bypass:
        print("🚫 Multi-instance deployment detected; unsafe distributed-lock bypass is forbidden.")
        print("   Forcing fail-closed mode: distributed writer lock will remain enabled.")
        os.environ["NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK"] = "0"
        os.environ["NIJA_DISABLE_WRITER_LOCK"] = "0"
        _unsafe_bypass = False
        _require_lock = True

    _redis_url = get_redis_url()
    _redis_url_source = get_redis_url_source()
    _redis_env_presence = get_redis_env_presence()
    _redis_resolution_diag = get_redis_resolution_diagnostics()
    _strict_single_redis = os.environ.get("NIJA_STRICT_SINGLE_REDIS_URL", "true").strip().lower() in _truthy
    _allow_plain_redis_fallback = os.environ.get("NIJA_REDIS_ALLOW_PLAIN_FALLBACK", "false").strip().lower() in _truthy
    _force_redis_tls_env = os.environ.get("NIJA_REDIS_FORCE_TLS", "true").strip().lower() in _truthy
    _redis_primary_is_tls = _redis_url.startswith("rediss://")
    _force_redis_tls = _force_redis_tls_env or _redis_primary_is_tls
    if _redis_primary_is_tls and not _force_redis_tls_env:
        print(
            "⚠️ NIJA_REDIS_FORCE_TLS=false ignored because NIJA_REDIS_URL uses rediss://; enforcing TLS.",
            flush=True,
        )
    _effective_allow_plain_redis_fallback = (
        (not _redis_primary_is_tls)
        and (_allow_plain_redis_fallback or (not _force_redis_tls))
    )
    if _effective_allow_plain_redis_fallback:
        print(
            "⚠️ NIJA_REDIS_ALLOW_PLAIN_FALLBACK is ignored; plaintext Redis fallback is disabled.",
            flush=True,
        )
    _effective_allow_plain_redis_fallback = False
    _fail_closed_retry_enabled = os.environ.get(
        "NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE", "true"
    ).strip().lower() in _truthy
    _degraded_mode_requested = os.environ.get(
        "NIJA_RUNTIME_DEGRADED_MODE", "0"
    ).strip() == "1"
    _default_fail_closed_max_retries = 0 if _degraded_mode_requested else (12 if _live_mode else 0)
    _fail_closed_max_retries_raw = os.environ.get(
        "NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS", str(_default_fail_closed_max_retries)
    ).strip()
    try:
        _fail_closed_max_retries = max(0, int(_fail_closed_max_retries_raw or str(_default_fail_closed_max_retries)))
    except (TypeError, ValueError):
        _fail_closed_max_retries = _default_fail_closed_max_retries
    _default_exit_unreachable = _live_mode
    _fail_closed_exit_unreachable = os.environ.get(
        "NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS",
        "true" if _default_exit_unreachable else "false",
    ).strip().lower() in _truthy
    if _live_mode and _require_lock and not _unsafe_bypass:
        if _fail_closed_max_retries <= 0:
            _fail_closed_max_retries = 12
            os.environ["NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS"] = "12"
            print(
                "⚠️ Live lock-required mode forbids infinite fail-closed standby retries; "
                "forcing NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS=12.",
                flush=True,
            )
        if not _fail_closed_exit_unreachable:
            _fail_closed_exit_unreachable = True
            os.environ["NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS"] = "true"
            print(
                "⚠️ Live lock-required mode forbids NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS=false; "
                "forcing true.",
                flush=True,
            )
    _allow_local_lock_fallback = os.environ.get(
        "NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK", "false"
    ).strip().lower() in _truthy
    _force_local_lock_fallback = os.environ.get(
        "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK", "false"
    ).strip().lower() in _truthy
    if _allow_local_lock_fallback and _multi_instance_possible and not _force_local_lock_fallback:
        print(
            "🚫 Multi-instance deployment detected; local writer-lock fallback is forbidden.",
            flush=True,
        )
        print(
            "   Forcing NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK=false to preserve single-writer safety.",
            flush=True,
        )
        os.environ["NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK"] = "0"
        _allow_local_lock_fallback = False
    if _live_mode and _require_lock and _allow_local_lock_fallback and not _unsafe_bypass:
        print(
            "🚫 LIVE mode with distributed lock required forbids local writer-lock fallback.",
            flush=True,
        )
        print(
            "   Set NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true only if you intentionally accept single-instance risk.",
            flush=True,
        )
        os.environ["NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK"] = "0"
        os.environ["NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"] = "0"
        _allow_local_lock_fallback = False
        _force_local_lock_fallback = False
    elif _allow_local_lock_fallback and _multi_instance_possible and _force_local_lock_fallback:
        print(
            "🚨 UNSAFE MODE: forcing local writer-lock fallback while multi-instance risk is detected.",
            flush=True,
        )
        print(
            "   This can allow duplicate writers. Use only as a temporary emergency override.",
            flush=True,
        )
    _kraken_buy_buffer_pct_raw = os.environ.get("KRAKEN_BUY_BUFFER_PCT", "0.004").strip() or "0.004"
    _kraken_buy_headroom_pct_raw = os.environ.get("NIJA_KRAKEN_BUY_HEADROOM_PCT", "0.005").strip() or "0.005"
    try:
        _kraken_buy_buffer_pct = min(max(float(_kraken_buy_buffer_pct_raw), 0.0), 0.05)
    except (TypeError, ValueError):
        _kraken_buy_buffer_pct = 0.004
    try:
        _kraken_buy_headroom_pct = min(max(float(_kraken_buy_headroom_pct_raw), 0.0), 0.05)
    except (TypeError, ValueError):
        _kraken_buy_headroom_pct = 0.005
    print(
        "🔐 Writer lock mode | "
        f"live={_live_mode} required={_require_lock} unsafe_bypass={_unsafe_bypass} "
        f"redis_configured={bool(_redis_url)} source={_redis_url_source or 'unset'} "
        f"strict_single_url={_strict_single_redis} plain_fallback={_effective_allow_plain_redis_fallback}"
    )
    print(f"🔐 Redis env presence | {_redis_env_presence}")
    print(f"🔐 Redis resolution diag | {_redis_resolution_diag}")
    print(
        "🛡️ Hardening config | "
        f"redis_force_tls={_force_redis_tls} "
        f"kraken_buy_buffer={_kraken_buy_buffer_pct * 100:.2f}% "
        f"kraken_buy_headroom={_kraken_buy_headroom_pct * 100:.2f}%"
    )
    print(
        "🧯 Fail-closed config | "
        f"retry_on_lock_failure={_fail_closed_retry_enabled} "
        f"max_retry_attempts={_fail_closed_max_retries} "
        f"exit_on_unreachable_redis={_fail_closed_exit_unreachable} "
        f"local_fallback={_allow_local_lock_fallback} "
        f"force_local_fallback={_force_local_lock_fallback}"
    )

    def _validate_primary_redis_url_shape() -> str:
        if not _redis_url:
            return ""
        try:
            _parsed_primary = urlparse(_redis_url)
        except Exception:
            return "Primary Redis URL is not parseable"

        _scheme = (_parsed_primary.scheme or "").lower()
        _host = (_parsed_primary.hostname or "").lower()
        _source = (_redis_url_source or "").strip().upper()

        if _scheme in {"http", "https"}:
            return (
                "Primary Redis URL uses HTTP(S), not Redis protocol. "
                "Set NIJA_REDIS_URL to the exact Redis Connect URL from Railway Redis service."
            )
        if _scheme not in {"redis", "rediss"}:
            return (
                f"Primary Redis URL uses unsupported scheme '{_scheme or 'missing'}'. "
                "Expected redis:// or rediss://."
            )
        if not _parsed_primary.hostname or _parsed_primary.port is None:
            return "Primary Redis URL is missing host or port"
        if (
            _source == "NIJA_REDIS_URL"
            and (".proxy.rlwy.net" in _host or _host.endswith(".up.railway.app"))
            and _scheme != "rediss"
            and _force_redis_tls
        ):
            return (
                "Primary NIJA_REDIS_URL points to Railway proxy with redis:// while TLS is required. "
                "Use rediss:// from Railway Redis Connect tab."
            )
        return ""

    _primary_url_shape_error = _validate_primary_redis_url_shape()
    if _primary_url_shape_error:
        _shape_msg = (
            f"Invalid primary Redis URL ({_redis_url_source or 'unset'}): {_primary_url_shape_error}"
        )
        print("❌ REDIS URL VALIDATION FAILED")
        print(f"   {_shape_msg}")
        print("   Steps:")
        print("     1. Open Railway -> Redis service -> Connect tab")
        print("     2. Copy the full Redis URL exactly as provided")
        print("     3. Set NIJA_REDIS_URL to that exact value")
        print("     4. Redeploy bot service")
        if _live_mode and _require_lock and not _unsafe_bypass:
            if _standby_retry_active:
                raise RuntimeError(_shape_msg)
            _enter_fail_closed_standby(_shape_msg)
            return
        print(
            "⚠️ Distributed lock is optional in this mode; skipping writer lock for this startup.",
            flush=True,
        )
        return

    if not _redis_url:
        _msg = (
            "⚠️ Distributed single-writer lock disabled "
            "(no valid Redis URL resolved from URL vars or component vars; see Redis resolution diag above)."
        )
        if _require_lock:
            if _standby_retry_active:
                raise RuntimeError(
                    "Redis URL not configured while distributed single-writer lock is required"
                )
            print(_msg)
            _enter_fail_closed_standby(
                "Redis URL not configured while distributed single-writer lock is required"
            )
            return
        print(_msg)
        return
    try:
        redis = cast(Any, importlib.import_module("redis"))
        _ttl_s_raw = os.environ.get("NIJA_WRITER_LOCK_TTL_S", "").strip()
        _lease_ttl_ms_raw = os.environ.get("NIJA_REDIS_LEASE_TTL_MS", "").strip()
        try:
            if _ttl_s_raw:
                _ttl_s = max(15, int(_ttl_s_raw))
            elif _lease_ttl_ms_raw:
                _lease_ttl_ms = int(_lease_ttl_ms_raw)
                _ttl_s = max(15, int((_lease_ttl_ms + 999) // 1000))
            else:
                _ttl_s = 15
        except (TypeError, ValueError):
            _ttl_s = 15
            print("⚠️ Invalid lock TTL env value; using default 15s")
        _scope = _writer_lock_scope()
        _lock_key = os.environ.get("NIJA_WRITER_LOCK_KEY", "").strip() or f"nija:writer_lock:{_scope}"
        _meta_key = os.environ.get("NIJA_WRITER_LOCK_META_KEY", "").strip() or f"nija:writer_lock_meta:{_scope}"
        _fencing_key = os.environ.get("NIJA_WRITER_FENCING_KEY", "").strip() or f"nija:writer_fence:{_scope}"
        _instance_identity = current_instance_identity()
        _owner = format_instance_identity(_instance_identity)
        def _validate_nija_redis_env() -> None:
            _raw_env_value = os.environ.get("NIJA_REDIS_URL")
            if not _raw_env_value:
                return
            if _raw_env_value != _raw_env_value.strip():
                raise RuntimeError("NIJA_REDIS_URL contains leading or trailing whitespace")
            _trimmed = _raw_env_value.strip()
            if len(_trimmed) >= 2 and _trimmed[0] == _trimmed[-1] and _trimmed[0] in {'"', "'"}:
                raise RuntimeError("NIJA_REDIS_URL must not include wrapping quotes")
            if not (_trimmed.startswith("redis://") or _trimmed.startswith("rediss://")):
                # Redact potential credentials before including the value in the message.
                if "@" in _trimmed:
                    _display = "<redacted>@" + _trimmed.split("@", 1)[1]
                else:
                    _display = _trimmed[:80] + ("..." if len(_trimmed) > 80 else "")
                raise RuntimeError(
                    f"NIJA_REDIS_URL is set to {_display!r}, which is not a valid Redis connection URL. "
                    "In Railway, copy the full Connect URL from the Redis service Connect tab "
                    "(format: rediss://default:PASSWORD@<host>.proxy.rlwy.net:PORT) "
                    "and set that exact value as NIJA_REDIS_URL."
                )
            _force_tls_check = _force_redis_tls
            if (
                _trimmed.startswith("redis://")
                and _force_tls_check
                and not _redis_url.startswith("rediss://")
                and (
                    ".proxy.rlwy.net" in _trimmed.lower()
                    or _trimmed.lower().split("@", 1)[-1].split("/")[0].endswith(".up.railway.app")
                )
            ):
                print(
                    "⚠️  CONFIG WARNING: NIJA_REDIS_URL uses redis:// (plain) against a Railway "
                    "public proxy endpoint while NIJA_REDIS_FORCE_TLS=true. "
                    "Set NIJA_REDIS_URL explicitly to rediss:// for this endpoint.",
                    flush=True,
                )

        def _try_plain_railway_proxy_fallback(_url: str, _exc: Exception):
            return None

        def _detect_non_redis_http_endpoint(_url: str) -> str:
            """Return a direct operator-facing error when endpoint behaves like HTTP."""
            try:
                _parsed = urlparse(_url)
                # Do not plaintext-probe TLS Redis endpoints. A rediss:// proxy can
                # legitimately reject plaintext probes and look like HTTP noise.
                if (_parsed.scheme or "").lower() == "rediss":
                    return ""
                _host = _parsed.hostname
                _port = _parsed.port
                if not _host or _port is None:
                    return ""
                with socket.create_connection((_host, int(_port)), timeout=2.5) as _sock:
                    _sock.sendall(b"*1\r\n$4\r\nPING\r\n")
                    _resp = _sock.recv(128)
                if not _resp:
                    return ""
                _head = _resp[:80].decode("latin-1", errors="ignore")
                if _resp.startswith(b"HTTP/") or b"<!DOCTYPE HTML" in _resp or "Bad request syntax" in _head:
                    return (
                        "NIJA_REDIS_URL endpoint responded as HTTP/non-Redis. "
                        "Copy the Redis URL from Railway Redis service Connect tab and set NIJA_REDIS_URL to that exact value."
                    )
            except Exception:
                return ""
            return ""

        _validate_nija_redis_env()
        _connect_timeout_raw = os.environ.get("NIJA_REDIS_CONNECT_TIMEOUT_S", "5").strip()
        _socket_timeout_raw = os.environ.get("NIJA_REDIS_SOCKET_TIMEOUT_S", "5").strip()
        _ping_retries_raw = os.environ.get("NIJA_REDIS_STARTUP_PING_RETRIES", "5").strip()
        _ping_retry_delay_raw = os.environ.get("NIJA_REDIS_STARTUP_PING_RETRY_DELAY_S", "2").strip()
        try:
            _redis_connect_timeout_s = min(max(float(_connect_timeout_raw or "5"), 1.0), 30.0)
        except (TypeError, ValueError):
            _redis_connect_timeout_s = 5.0
        try:
            _redis_socket_timeout_s = min(max(float(_socket_timeout_raw or "5"), 1.0), 30.0)
        except (TypeError, ValueError):
            _redis_socket_timeout_s = 5.0
        try:
            _ping_retries = min(max(int(_ping_retries_raw or "5"), 1), 20)
        except (TypeError, ValueError):
            _ping_retries = 5
        try:
            _ping_retry_delay_s = min(max(float(_ping_retry_delay_raw or "2"), 0.25), 30.0)
        except (TypeError, ValueError):
            _ping_retry_delay_s = 2.0
        print(
            "🔐 Redis startup connectivity | "
            f"connect_timeout={_redis_connect_timeout_s:.2f}s "
            f"socket_timeout={_redis_socket_timeout_s:.2f}s "
            f"ping_retries={_ping_retries} "
            f"retry_delay={_ping_retry_delay_s:.2f}s"
        )

        def _build_strict_redis_client(_url: str):
            assert _url.startswith("redis://") or _url.startswith("rediss://")
            _kwargs: dict[str, Any] = {
                "decode_responses": True,
                "socket_connect_timeout": _redis_connect_timeout_s,
                "socket_timeout": _redis_socket_timeout_s,
            }
            _parsed_url = urlparse(_url)
            _tls_ca_certs = os.getenv("NIJA_REDIS_TLS_CA_CERT", "").strip()
            if (_parsed_url.scheme or "").lower() == "rediss":
                if _tls_ca_certs:
                    _kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
                    _kwargs["ssl_check_hostname"] = True
                    _kwargs["ssl_ca_certs"] = _tls_ca_certs
                else:
                    _kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
                    _kwargs["ssl_check_hostname"] = True
            return redis.Redis.from_url(_url, **_kwargs)

        _ping_exc = None
        _client: Any
        _non_redis_hint = _detect_non_redis_http_endpoint(_redis_url)
        if _non_redis_hint:
            _ping_exc = RuntimeError(_non_redis_hint)
            _primary_source_is_nija = (_redis_url_source or "").strip().upper() == "NIJA_REDIS_URL"
            if _live_mode and _require_lock and _primary_source_is_nija and not _unsafe_bypass:
                raise RuntimeError(
                    "LIVE mode fail-closed: primary NIJA_REDIS_URL endpoint appears HTTP/non-Redis. "
                    "Update NIJA_REDIS_URL to the exact Railway Redis Connect URL before trading."
                ) from _ping_exc
            if _strict_single_redis:
                raise _ping_exc
            print(
                "⚠️ Primary NIJA_REDIS_URL appears non-Redis; "
                "strict_single_url=false so attempting configured fallback Redis URLs..."
            )
            _client = cast(Any, None)
        else:
            _client = _build_strict_redis_client(_redis_url)

            # Retry logic before any lock operations use Redis.
            _max_retries = _ping_retries
            for _attempt in range(_max_retries):
                try:
                    _client.ping()
                    _ping_exc = None
                    break
                except Exception as _exc:
                    _ping_exc = _exc
                    if _attempt < _max_retries - 1:
                        print(
                            f"⚠️ Redis connection attempt {_attempt + 1}/{_max_retries} failed: "
                            f"{_exc}. Retrying in {_ping_retry_delay_s:.2f}s..."
                        )
                        time.sleep(_ping_retry_delay_s)
                    else:
                        print(f"❌ Redis connection failed after {_max_retries} attempts")

        if _ping_exc:
            if _strict_single_redis:
                raise RuntimeError(
                    f"Strict Redis URL mode active: {_redis_url_source} unreachable ({_ping_exc})"
                )
            # Primary URL failed — try remaining configured URLs in priority order
            # First, log host details for all configured URLs (credentials redacted) to aid diagnosis
            def _redact_url(u: str) -> str:
                try:
                    from urllib.parse import urlparse
                    _p = urlparse(u)
                    return f"{_p.scheme}://***@{_p.hostname}:{_p.port}"
                except Exception:
                    return "<unparseable>"

            def _probe_non_redis_endpoint(u: str) -> str:
                """Return a human-friendly hint if endpoint responds like HTTP/non-Redis."""
                try:
                    _p = urlparse(u)
                    if (_p.scheme or "").lower() == "rediss":
                        return ""
                    _host = _p.hostname
                    _port = _p.port
                    if not _host or not _port:
                        return ""
                    with socket.create_connection((_host, _port), timeout=2.5) as _sock:
                        _sock.sendall(b"*1\r\n$4\r\nPING\r\n")
                        _data = _sock.recv(128)
                    if not _data:
                        return ""
                    _head = _data[:64].decode("latin-1", errors="ignore").strip()
                    if _data.startswith(b"HTTP/") or b"<!DOCTYPE HTML" in _data or "Bad request syntax" in _head:
                        return (
                            "\n  ⚠️  Endpoint appears to be an HTTP service, not Redis.\n"
                            "     Verify NIJA_REDIS_URL was copied from Railway Redis → Connect tab\n"
                            "     (not from an app/public HTTP endpoint)."
                        )
                except Exception:
                    return ""
                return ""

            _all_urls = get_all_redis_urls()
            _standby_log_every_raw = os.environ.get("NIJA_STANDBY_LOG_EVERY", "8").strip()
            try:
                _standby_log_every = max(1, int(_standby_log_every_raw or "8"))
            except (TypeError, ValueError):
                _standby_log_every = 8
            _verbose_standby = (not _standby_retry_active) or (_standby_retry_count % _standby_log_every == 0)

            if _verbose_standby:
                print(f"⚠️ Redis primary URL ({_redis_url_source}) unreachable: {_ping_exc}")
                print("  Configured Redis URLs (hosts only):")
                for _src, _u in _all_urls:
                    print(f"    {_src}: {_redact_url(_u)}")
            _fallback_tried: list[str] = []
            _client_resolved = False
            for _fb_source, _fb_url in _all_urls:
                if _fb_url == _redis_url:
                    continue  # already tried
                _fallback_tried.append(_fb_source)
                if _verbose_standby:
                    print(f"  Trying fallback: {_fb_source} ({_redact_url(_fb_url)})")
                try:
                    _fb_client = _build_strict_redis_client(_fb_url)
                    _fb_client.ping()
                    _client = _fb_client
                    _redis_url = _fb_url
                    _redis_url_source = _fb_source
                    print(f"✅ Redis fallback connected via {_fb_source}")
                    _client_resolved = True
                    break
                except Exception as _fb_exc:
                    if _verbose_standby:
                        print(f"  ↳ {_fb_source} also unreachable: {_fb_exc}")
            if not _client_resolved:
                if _allow_local_lock_fallback and (not _multi_instance_possible or _force_local_lock_fallback):
                    if _live_mode and _require_lock and not _unsafe_bypass:
                        raise RuntimeError(
                            "Redis unreachable in LIVE mode with distributed lock required; "
                            "local writer-lock fallback is blocked"
                        ) from _ping_exc
                    print(
                        "🚨 LOCAL WRITER LOCK FALLBACK ACTIVE: Redis lock is unreachable; "
                        "continuing without distributed lock because NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK=true. "
                        "No degraded-mode override flags will be activated.",
                        flush=True,
                    )
                    print(
                        "⚠️ Use this only for confirmed single-instance deployments. "
                        "Re-enable distributed lock after Redis recovery.",
                        flush=True,
                    )
                    if _force_local_lock_fallback:
                        os.environ["NIJA_CONFIRM_BYPASS_RISKS"] = "1"
                        print(
                            "🚨 UNSAFE EMERGENCY OVERRIDE: forcing live activation gates to fail-open "
                            "under local writer-lock fallback.",
                            flush=True,
                        )
                    return
                # Check if all URLs point to Railway internal networking
                _internal_hosts = [
                    _src for _src, _u in _all_urls
                    if ".railway.internal" in _u
                ]
                _proxy_hosts = [
                    _src for _src, _u in _all_urls
                    if ".proxy.rlwy.net" in _u or (urlparse(_u).hostname or "").lower().endswith(".up.railway.app")
                ]
                _railway_hint = ""
                if _all_urls and len(_internal_hosts) == len(_all_urls):
                    _railway_hint = (
                        f"\n  ⚠️  ALL configured Redis URLs use Railway internal networking "
                        f"({', '.join(_internal_hosts)}).\n"
                        f"     Internal hostnames only work within the same Railway project with private networking.\n"
                        f"     FIX: Go to Railway → Redis service → Connect tab → copy the PUBLIC proxy URL\n"
                        f"     (format: rediss://default:PASSWORD@maglev.proxy.rlwy.net:PORT)\n"
                        f"     Set it as NIJA_REDIS_URL in the bot service Variables and redeploy."
                    )
                elif _internal_hosts:
                    _railway_hint = (
                        f"\n  ⚠️  Some configured Redis URLs use Railway internal networking "
                        f"({', '.join(_internal_hosts)}).\n"
                        f"     Internal hostnames only work within compatible Railway private networking contexts.\n"
                        f"     Prefer NIJA_REDIS_URL/REDIS_PUBLIC_URL set to a public proxy rediss:// endpoint."
                    )
                elif _proxy_hosts and "connection reset" in str(_ping_exc).lower():
                    _railway_hint = (
                        f"\n  ⚠️  Railway public proxy returned 'Connection reset by peer' "
                        f"({', '.join(_proxy_hosts)}).\n"
                        f"     This means the Railway Redis service is down, restarting, or was re-provisioned.\n"
                        f"     Steps to fix:\n"
                        f"       1. Go to Railway → Redis service → verify the service is Running\n"
                        f"       2. If re-provisioned, copy the new PUBLIC proxy URL from the Connect tab\n"
                        f"          (format: rediss://default:NEW_PASSWORD@maglev.proxy.rlwy.net:NEW_PORT)\n"
                        f"       3. Update NIJA_REDIS_URL in the bot service Variables and redeploy\n"
                        f"       4. To bypass the lock while Redis recovers (UNSAFE, single-instance only):\n"
                        f"          set NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true and redeploy"
                    )
                elif _proxy_hosts and "record layer failure" in str(_ping_exc).lower():
                    _railway_hint = (
                        f"\n  ⚠️  Railway public proxy returned TLS record-layer failure "
                        f"({', '.join(_proxy_hosts)}).\n"
                        f"     This usually means wrong/stale Redis URL credentials or endpoint details.\n"
                        f"     Steps to fix:\n"
                        f"       1. Go to Railway → Redis service → Connect tab\n"
                        f"       2. Copy the full PUBLIC proxy URL exactly as shown\n"
                        f"       3. Set NIJA_REDIS_URL to that value in bot service Variables\n"
                        f"       4. Ensure TLS validation is strict (do not set NIJA_REDIS_TLS_INSECURE)\n"
                        f"       5. Remove conflicting vars: REDIS_URL / REDIS_PRIVATE_URL / REDIS_TLS_URL\n"
                        f"       6. Redeploy the bot service"
                    )
                if not _railway_hint and _proxy_hosts:
                    _probe_hint = _probe_non_redis_endpoint(_redis_url)
                    if _probe_hint:
                        _railway_hint = _probe_hint
                _tls_policy_hint = ""
                if _redis_url.startswith("rediss://") and not _force_redis_tls:
                    _tls_policy_hint = (
                        "\n  ⚠️  TLS policy mismatch detected: NIJA_REDIS_URL uses rediss:// but "
                        "redis_force_tls is false.\n"
                        "     Set NIJA_REDIS_FORCE_TLS=true and redeploy."
                    )
                if _standby_retry_active and not _verbose_standby:
                    _ping_err_msg = (
                        "Redis connectivity check failed for distributed writer lock: "
                        f"{_ping_exc}"
                    )
                else:
                    _ping_err_msg = (
                        f"Redis connectivity check failed for distributed writer lock: {_ping_exc}"
                        f"{_railway_hint}{_tls_policy_hint}\n"
                        f"  Primary source: {_redis_url_source or 'unset'}\n"
                        f"  Fallbacks tried: {_fallback_tried or 'none'}\n"
                        f"  Redis env presence: {_redis_env_presence}"
                    )
                if _require_lock:
                    raise RuntimeError(_ping_err_msg) from _ping_exc
                print(f"⚠️ {_ping_err_msg}")
                print("⚠️ Distributed writer lock SKIPPED (Redis unreachable and lock not required in this mode).")
                if _unsafe_bypass:
                    print(
                        "   Clear NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK to restore fail-closed distributed lock enforcement."
                    )
                elif _live_mode:
                    print("   Set NIJA_REQUIRE_DISTRIBUTED_LOCK=1 to enforce fail-closed behaviour.")
                else:
                    print(
                        "   Set NIJA_REQUIRE_DISTRIBUTED_LOCK=1 or LIVE_CAPITAL_VERIFIED=1 to enforce fail-closed behaviour."
                    )
                return

        def _try_acquire_once() -> tuple[int, str, int]:
            """Try one atomic acquire and return (token, holder, pttl_ms)."""
            _res = _client.eval(
                """
                if redis.call('EXISTS', KEYS[1]) == 1 then
                    local holder = redis.call('GET', KEYS[1])
                    local pttl = redis.call('PTTL', KEYS[1])
                    return {0, holder or '', pttl or -2}
                end
                local token = redis.call('INCR', KEYS[2])
                local value = tostring(token) .. ':' .. ARGV[1]
                redis.call('SET', KEYS[1], value, 'EX', tonumber(ARGV[2]))
                local pttl = redis.call('PTTL', KEYS[1])
                return {token, value, pttl or -2}
                """,
                2,
                _lock_key,
                _fencing_key,
                _owner,
                str(_ttl_s),
            )
            _token = 0
            _holder_local = "<unknown-holder>"
            _pttl_ms = -2
            if isinstance(_res, (list, tuple)):
                if len(_res) >= 1:
                    try:
                        _token = int(_res[0] or 0)
                    except (TypeError, ValueError):
                        _token = 0
                if len(_res) >= 2:
                    _holder_local = str(_res[1] or _holder_local)
                if len(_res) >= 3:
                    try:
                        _pttl_ms = int(_res[2] or -2)
                    except (TypeError, ValueError):
                        _pttl_ms = -2
            return _token, _holder_local, _pttl_ms

        def _read_lock_meta() -> dict[str, object]:
            try:
                return parse_writer_lock_metadata(str(_client.get(_meta_key) or ""))
            except Exception as _meta_exc:
                return {"present": False, "error": str(_meta_exc), "display": "<meta-read-failed>"}

        print("=== ATTEMPTING REDIS LOCK ===", flush=True)
        _fencing_token, _holder, _holder_pttl_ms = _try_acquire_once()
        acquired = _fencing_token > 0
        print(f"=== LOCK ACQUIRED: {acquired} ===", flush=True)

        # ═══════════════════════════════════════════════════════════════════════════════════════
        # DETERMINISTIC LOCK ACQUISITION STATE MACHINE (FIX 4: No "retries indefinitely")
        # ═══════════════════════════════════════════════════════════════════════════════════════
        # Replaces dangerous infinite retry loop with explicit timeout + safe fallback states.
        # State flow: ATTEMPTING → [ACQUIRED + proceed] or CONTENDING → TIMEOUT → [DEGRADED or EXIT]
        
        # Configure explicit timeout (FIX 4 requirement: deterministic, not indefinite)
        # Live mode: 120s (allows time for stale-lock rescue over Railway transients)
        # Non-live mode: 60s (faster fallback to degraded mode for testing)
        _lock_acquire_timeout_s_raw = os.environ.get("NIJA_LOCK_ACQUIRE_TIMEOUT_S", "").strip()
        try:
            _lock_acquire_timeout_s = float(_lock_acquire_timeout_s_raw) if _lock_acquire_timeout_s_raw else (120.0 if _live_mode else 60.0)
        except (TypeError, ValueError):
            _lock_acquire_timeout_s = 120.0 if _live_mode else 60.0
        
        # Enforce minimum timeout: live mode 30s (time for Railway recovery + rescue), non-live 15s
        if _live_mode:
            _lock_acquire_timeout_s = max(_lock_acquire_timeout_s, 30.0)
        else:
            _lock_acquire_timeout_s = max(_lock_acquire_timeout_s, 15.0)
        
        # Checkpoint interval: emit warnings + attempt stale-lock rescue (FIX 4: explicit checkpoints)
        _checkpoint_interval_s_raw = os.environ.get("NIJA_LOCK_CHECKPOINT_INTERVAL_S", "").strip()
        try:
            _checkpoint_interval_s = float(_checkpoint_interval_s_raw) if _checkpoint_interval_s_raw else 30.0
        except (TypeError, ValueError):
            _checkpoint_interval_s = 30.0
        _checkpoint_interval_s = max(_checkpoint_interval_s, 5.0)  # Minimum 5s between checkpoints
        
        # Retry interval: time between lock acquisition attempts (FIX 4: bounded retry rate)
        _lock_retry_interval = 0.5  # 500ms between retries
        
        # Initialize FSM state  
        _wait_started_at = time.time()
        _next_checkpoint = _wait_started_at + _checkpoint_interval_s
        def _resolve_holder_state(holder_raw: str) -> tuple[dict[str, str], dict[str, object], dict[str, object]]:
            holder_info_local = parse_distributed_lock_holder(holder_raw)
            holder_inspection_local = inspect_lock_holder(_instance_identity, holder_info_local)
            holder_meta_local = _read_lock_meta()
            return holder_info_local, holder_inspection_local, holder_meta_local

        _holder_info, _holder_inspection, _holder_meta = _resolve_holder_state(_holder)

        try:
            _stale_heartbeat_timeout_s = max(
                float(_ttl_s * 2),
                float(os.environ.get("NIJA_STALE_RAILWAY_LOCK_HEARTBEAT_TIMEOUT_S", "90") or 90.0),
            )
        except (TypeError, ValueError):
            _stale_heartbeat_timeout_s = max(float(_ttl_s * 2), 90.0)

        _auto_clear_stale_railway = os.environ.get("NIJA_AUTO_CLEAR_STALE_RAILWAY_LOCK", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "enabled",
        }

        print(f"🔐 Writer instance | {format_instance_identity(_instance_identity)}")
        print(f"🔐 Lock acquire timeout: {_lock_acquire_timeout_s:.0f}s (checkpoint interval: {_checkpoint_interval_s:.0f}s)")
        if _fencing_token <= 0:
            print(
                "🔎 Writer lock inspector | "
                f"{_holder_inspection.get('summary', 'holder inspection unavailable')}"
            )
            if _holder_meta.get("present"):
                _heartbeat_age = _holder_meta.get("heartbeat_age_s")
                _heartbeat_age_txt = (
                    f"{float(_heartbeat_age):.1f}s" if isinstance(_heartbeat_age, (int, float)) else "unknown"
                )
                print(
                    "🔎 Writer lock heartbeat | "
                    f"holder_meta={_holder_meta.get('display', '<missing-meta>')} age={_heartbeat_age_txt}"
                )

        # ═══════════════════════════════════════════════════════════════════════════════════════
        # FSM CONTENDING STATE: Loop with explicit timeout (FIX 4: bounded wait, not indefinite)
        # ═══════════════════════════════════════════════════════════════════════════════════════
        while _fencing_token <= 0:
            _now = time.time()
            _total_waited_s = _now - _wait_started_at
            
            # FIX 4: CHECK TIMEOUT FIRST — Exit loop if we've exceeded max wait time
            if _total_waited_s >= _lock_acquire_timeout_s:
                print("\n" + "┏" + "━" * 78 + "┓")
                print("┃ ⏱️  LOCK ACQUISITION TIMEOUT REACHED                                       ┃")
                print(f"┃ Lock acquire timeout: {_lock_acquire_timeout_s:.0f}s | Elapsed: {_total_waited_s:.1f}s              ┃")
                print(f"┃ Lock key: {_lock_key[-60:]:<60} ┃")
                print(f"┃ Holder:   {_holder_info.get('display', _holder)[:60]:<60} ┃")
                print("┗" + "━" * 78 + "┛\n")
                print(f"   Current instance: {format_instance_identity(_instance_identity)}")
                print(f"   Holder relationship: {_holder_inspection.get('relationship', 'unknown')}")
                print(f"   Redis source: {_redis_url_source or 'unset'}")
                logger.warning(
                    "Lock acquisition timeout after %.1fs | holder=%s | redis_source=%s",
                    _total_waited_s,
                    _holder_info.get('display', _holder),
                    _redis_url_source,
                )
                # FIX 2: Timeout reached → enter explicit degraded mode (safe fallback)
                break  # Exit loop and handle timeout in post-FSM state logic
            
            # Checkpoint: emit warnings and attempt stale-lock rescue
            if _now >= _next_checkpoint:
                _holder_info, _holder_inspection, _holder_meta = _resolve_holder_state(_holder)
                logger.warning(
                    "Distributed lock still unavailable (timeout in %.1fs, elapsed=%.1fs). "
                    "holder=%s parsed=%s inspection=%s pttl_ms=%s",
                    max(0, _lock_acquire_timeout_s - _total_waited_s),
                    _total_waited_s,
                    _holder,
                    _holder_info,
                    _holder_inspection,
                    _holder_pttl_ms,
                )

                # Stale lock rescue: only delete when holder matches and lock appears stale
                _rescued = 0
                _allow_railway_rescue = False
                try:
                    _holder_token = str(_holder_info.get("token", "") or "")
                    _holder_deployment = str(_holder_info.get("deployment_id", "") or "")
                    _current_deployment = str(_instance_identity.get("deployment_id", "") or "")
                    _meta_token = str(_holder_meta.get("token", "") or "")
                    _heartbeat_age = _holder_meta.get("heartbeat_age_s")
                    _heartbeat_is_stale = isinstance(_heartbeat_age, (int, float)) and float(_heartbeat_age) >= _stale_heartbeat_timeout_s
                    _cross_deployment = bool(
                        _current_deployment and _holder_deployment and _current_deployment != _holder_deployment
                    )
                    # "other-instance" means the holder shares NO identity attribute
                    # (instance_id, container, hostname, deployment, replica) with this
                    # process.  That is already stronger evidence of a stale foreign lock
                    # than a cross-deployment check alone, so the rescue is allowed for
                    # that relationship without requiring deployment IDs to be present.
                    _is_other_instance = _holder_inspection.get("relationship") == "other-instance"
                    _allow_railway_rescue = bool(
                        _auto_clear_stale_railway
                        and (_cross_deployment or _is_other_instance)
                        and _holder_token
                        and _meta_token == _holder_token
                        and _heartbeat_is_stale
                    )
                    # Emit a single diagnostic when rescue is eligible but waiting on
                    # heartbeat staleness, so operators can see what is blocking.
                    if (
                        _auto_clear_stale_railway
                        and (_cross_deployment or _is_other_instance)
                        and _holder_token
                        and _meta_token == _holder_token
                        and not _heartbeat_is_stale
                        and isinstance(_heartbeat_age, (int, float))
                    ):
                        logger.warning(
                            "Stale-lock rescue eligible but heartbeat not yet stale "
                            "(relationship=%s age=%.1fs threshold=%.1fs remaining=%.1fs)",
                            _holder_inspection.get("relationship"),
                            float(_heartbeat_age),
                            _stale_heartbeat_timeout_s,
                            max(0.0, _stale_heartbeat_timeout_s - float(_heartbeat_age)),
                        )
                    _rescued = int(
                        _client.eval(
                            """
                            local current = redis.call('GET', KEYS[1])
                            if not current then return 0 end
                            local pttl = redis.call('PTTL', KEYS[1])
                            if current ~= ARGV[1] then return 0 end
                            local stale_by_ttl = (pttl == -1 or pttl <= 0)
                            local stale_by_heartbeat = (ARGV[2] == '1')
                            if stale_by_ttl or stale_by_heartbeat then
                                redis.call('DEL', KEYS[1])
                                if KEYS[2] and KEYS[2] ~= '' then
                                    redis.call('DEL', KEYS[2])
                                end
                                return 1
                            end
                            return 0
                            """,
                            2,
                            _lock_key,
                            _meta_key,
                            _holder,
                            "1" if _allow_railway_rescue else "0",
                        )
                        or 0
                    )
                except Exception as _stale_exc:
                    logger.warning("Stale-lock rescue check failed: %s", _stale_exc)

                if _rescued == 1:
                    _rescue_trigger = "other-instance" if _is_other_instance else "cross-deployment"
                    logger.info(
                        "🔓 Cleared and recovered stale writer lock; retrying acquire "
                        "(trigger=%s relationship=%s)",
                        _rescue_trigger,
                        _holder_inspection.get("relationship"),
                    )
                    _fencing_token, _holder, _holder_pttl_ms = _try_acquire_once()
                    _holder_info, _holder_inspection, _holder_meta = _resolve_holder_state(_holder)
                    if _fencing_token > 0:
                        break  # Acquired after rescue — exit loop
                
                _next_checkpoint = time.time() + _checkpoint_interval_s
                print(f"⏳ Awaiting lock release... (timeout in {max(0, _lock_acquire_timeout_s - _total_waited_s):.0f}s)")
                print(f"   Holder: {_holder_info.get('display', _holder)}")
                print(f"   Relationship: {_holder_inspection.get('relationship', 'unknown')}")
            
            # Sleep and retry lock acquisition
            time.sleep(_lock_retry_interval)
            try:
                _fencing_token, _holder, _holder_pttl_ms = _try_acquire_once()
                _holder_info, _holder_inspection, _holder_meta = _resolve_holder_state(_holder)
                if _fencing_token > 0:
                    break  # Successfully acquired — exit loop
            except Exception as _retry_err:
                logger.debug("Lock retry attempt failed: %s", _retry_err)
                _fencing_token = 0
                _holder_pttl_ms = -2
        
        # ═══════════════════════════════════════════════════════════════════════════════════════
        # FSM POST-LOOP: Handle exit condition — either ACQUIRED or TIMEOUT
        # ═══════════════════════════════════════════════════════════════════════════════════════
        if _fencing_token <= 0:
            # Lock acquisition timeout (FIX 2: explicit degraded mode fallback for resilience)
            print("\n" + "┏" + "━" * 78 + "┓")
            print("┃ ⏱️  LOCK ACQUISITION TIMEOUT — NO ACTIVE WRITER FOUND                       ┃")
            print(f"┃ Another deployment may hold the lock, or Redis is unavailable.           ┃")
            print(f"┃ Lock key: {_lock_key[-60:]:<60} ┃")
            print(f"┃ Holder:   {_holder_info.get('display', _holder)[:60]:<60} ┃")
            print("┗" + "━" * 78 + "┛\n")
            print(f"   Current instance: {format_instance_identity(_instance_identity)}")
            print(f"   Holder relationship: {_holder_inspection.get('relationship', 'unknown')}")
            print(f"   Lock holder raw: {_holder}")
            print(f"   Redis URL source: {_redis_url_source or 'unset'}")
            
            # FIX 2: Decision tree for safe fallback
            if _live_mode and _require_lock and not _unsafe_bypass:
                # LIVE + LOCK_REQUIRED + NO BYPASS: Fail-closed (safest, prevents split-brain)
                print("❌ FAILED TO ACQUIRE WRITER LOCK (entering fail-closed standby)")
                logger.critical(
                    "Distributed writer lock timeout in live mode with lock required; "
                    "entering fail-closed standby. This is safe — trading will be blocked until lock acquired."
                )
                _enter_fail_closed_standby(
                    f"Lock acquisition timeout after {_lock_acquire_timeout_s:.0f}s "
                    "(lock required in live mode)"
                )
                return
            elif _live_mode and _require_lock and _unsafe_bypass:
                # LIVE + LOCK_REQUIRED + UNSAFE_BYPASS: Trade locally (risky, only for single-instance)
                print("⚠️  UNSAFE: Proceeding with UNSAFE lock bypass enabled (single-instance only)")
                logger.warning(
                    "Distributed writer lock timeout but UNSAFE bypass enabled; proceeding with local trading. "
                    "DO NOT RUN MULTIPLE INSTANCES."
                )
                # Continue only with explicit unsafe bypass; degraded-mode overrides are disabled.
            else:
                # NON-LIVE or NOT_REQUIRED: continue without distributed lock.
                print("⚠️  Non-live/non-required mode: continuing without distributed lock")
                print("   No degraded-mode override flags will be activated")
                logger.info(
                    "Lock acquisition timeout in non-live or non-required mode; "
                    "continuing without distributed writer lock"
                )
            return
        
        # ═══════════════════════════════════════════════════════════════════════════════════════
        # FSM SUCCESS STATE: Lock acquired — proceed to trading
        # ═══════════════════════════════════════════════════════════════════════════════════════
        if _fencing_token > 0:
            token = _fencing_token
            owner_id = _owner
            instance_id = _instance_identity.get("instance_id", "")

            os.environ["NIJA_WRITER_FENCING_TOKEN"] = str(token)
            os.environ["NIJA_WRITER_OWNER_ID"] = str(owner_id)
            os.environ["NIJA_WRITER_INSTANCE_ID"] = str(instance_id)

            logger.critical(
                "WRITER AUTHORITY ESTABLISHED token=%s owner=%s instance=%s",
                token,
                owner_id,
                instance_id,
            )

            _token = f"{_fencing_token}:{_owner}"
            _distributed_writer_lock_client = _client
            _distributed_writer_lock_key = _lock_key
            _distributed_writer_lock_meta_key = _meta_key
            _distributed_writer_lock_token = _token
            _distributed_writer_fencing_key = _fencing_key
            _distributed_writer_fencing_token = _fencing_token
            _distributed_writer_lock_stop.clear()
            _acquired_at = time.time()
            os.environ["NIJA_WRITER_LOCK_ACQUIRED_AT"] = str(_acquired_at)
            os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
            os.environ["NIJA_WRITER_LOCK_TTL_S"] = str(_ttl_s)
            try:
                _client.set(_meta_key, _build_writer_lock_meta_payload(
                    _fencing_token,
                    _instance_identity,
                    acquired_at=_acquired_at,
                    heartbeat_at=_acquired_at,
                ), ex=_ttl_s)
            except Exception as _meta_write_exc:
                logger.warning("Unable to write distributed lock metadata key=%s: %s", _meta_key, _meta_write_exc)
            _distributed_writer_lock_thread = threading.Thread(
                target=_distributed_writer_lock_heartbeat,
                args=(_ttl_s,),
                daemon=True,
                name="DistributedWriterLockHeartbeat",
            )
            _distributed_writer_lock_thread.start()
            os.environ["NIJA_WRITER_LOCK_KEY"] = _lock_key
            os.environ["NIJA_WRITER_LOCK_META_KEY"] = _meta_key
            os.environ["NIJA_WRITER_LOCK_SCOPE"] = _scope
            print("✅ WRITER LOCK ACQUIRED", flush=True)
            print(
                "🔒 Distributed writer lock acquired — "
                f"key={_lock_key} fencing_token={_fencing_token} holder={_owner} meta_key={_meta_key}"
            )
    except Exception as _lock_exc:
        _retry_on_nonrecoverable = os.environ.get(
            "NIJA_FAIL_CLOSED_RETRY_ON_NONRECOVERABLE_REDIS_ERROR", "false"
        ).strip().lower() in _truthy
        if _standby_retry_active and _is_nonrecoverable_redis_config_error(str(_lock_exc)) and not _retry_on_nonrecoverable:
            raise SystemExit(1)
        if _standby_retry_active:
            raise RuntimeError(str(_lock_exc))
        if not _require_lock:
            print(
                "⚠️ Distributed writer lock unavailable, but lock is optional in this mode; continuing without standby loop.",
                flush=True,
            )
            print(f"   Lock error: {_lock_exc}", flush=True)
            return
        _enter_fail_closed_standby(str(_lock_exc))


def _acquire_process_lock() -> bool:
    """
    Write PID file and abort if another bot instance is already running.

    Stale PID files (process no longer exists or belongs to a non-NIJA process)
    are silently overwritten so a clean restart after a crash or a container
    redeploy always succeeds.

    In containerised deployments (Docker / Railway) the same PID number can be
    re-assigned to a completely different process in the new container.  To
    prevent a false-positive "DUPLICATE INSTANCE BLOCKED" we cross-check:

    1. Is the PID alive?           (os.kill signal-0)
    2. Is it actually a NIJA bot?  (_is_nija_process — reads /proc/<pid>/cmdline)
    3. Does the saved fingerprint  (_read_pid_file_meta — hostname/container)
       match the current host?

    If any check fails the stored PID is treated as stale and overwritten.
    """
    os.makedirs(os.path.dirname(_PID_FILE), exist_ok=True)

    stale_lock_detected = False
    if os.path.exists(_PID_FILE):
        try:
            with open(_PID_FILE) as _pf:
                _first_line = _pf.readline().strip()
            _old_pid = int(_first_line)
            os.kill(_old_pid, 0)   # signal 0 = "does this PID exist?"

            # PID exists — but verify it's genuinely a NIJA process, not a
            # recycled PID from a different container / system process.
            if not _is_nija_process(_old_pid):
                print(
                    f"⚠️  PID {_old_pid} in lock file is not a NIJA process "
                    "(likely PID reuse after container restart) — overwriting stale lock."
                )
                raise ProcessLookupError  # treat as stale

            # Cross-check the saved container fingerprint so we don't block a
            # restart caused by a previous deployment on a different host.
            _meta = _read_pid_file_meta(_PID_FILE)
            _saved_container = _meta.get("container_id", "")
            _saved_hostname   = _meta.get("hostname", "")
            _current_hostname = socket.gethostname()
            # Use empty string when HOSTNAME is missing so the comparison is
            # explicit — an unknown current container never falsely matches.
            _current_container = os.environ.get("HOSTNAME", "").strip()
            if (
                _saved_container
                and _current_container  # skip check when current container is unknown
                and _saved_container != _current_container
            ):
                print(
                    f"⚠️  Lock file container ({_saved_container}) ≠ current container "
                    f"({_current_container}) — overwriting stale cross-container lock."
                )
                raise ProcessLookupError  # treat as stale
            if (
                _saved_hostname
                and _saved_hostname != _current_hostname
            ):
                print(
                    f"⚠️  Lock file hostname ({_saved_hostname}) ≠ current hostname "
                    f"({_current_hostname}) — overwriting stale cross-host lock."
                )
                raise ProcessLookupError  # treat as stale

            # Process is alive, is a NIJA bot, and belongs to this host — block.
            print("\n" + "┏" + "━" * 78 + "┓")
            print(f"┃ 🚫 DUPLICATE INSTANCE BLOCKED                                             ┃")
            print(f"┃ Another NIJA bot is already running (PID {_old_pid:<33}) ┃")
            print(f"┃ Only ONE process may hold the API key at a time.                         ┃")
            print(f"┃ Stop the running bot first:  kill {_old_pid:<44} ┃")
            print(f"┃ Then remove the lock:        rm {_PID_FILE[-40:]:<42} ┃")
            print("┗" + "━" * 78 + "┛\n")
            sys.exit(1)
        except (ProcessLookupError, ValueError, OSError):
            # Stale PID file — the previous process is gone; safe to overwrite.
            stale_lock_detected = True

    if stale_lock_detected:
        os.environ["NIJA_UNCLEAN_SHUTDOWN"] = "true"
        os.environ["NIJA_SAFE_START_REQUIRED"] = "true"
        os.environ["NIJA_SAFE_START_REASON"] = "unclean shutdown detected"
        logger.warning(
            "⚠️  Unclean shutdown detected (stale PID lock) — safe-start mode required "
            "(set NIJA_SAFE_START_ACK or complete reconciliation to resume live trading)."
        )

    # Write PID + fingerprint metadata so future instances can cross-check.
    _pid_meta = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "container_id": os.environ.get("HOSTNAME", "").strip() or "unknown",
        "started_at": time.time(),
    }
    with open(_PID_FILE, "w") as _pf:
        _pf.write(f"{os.getpid()}\n")
        _pf.write(json.dumps(_pid_meta, sort_keys=True) + "\n")

    import atexit
    atexit.register(_release_process_lock)
    _acquire_distributed_process_lock()
    lock_acquired = os.environ.get("NIJA_WRITER_LEASE_ACQUIRED", "0").strip() == "1"
    if not lock_acquired:
        logger.critical(
            "STARTUP_OBSERVER_STANDBY: distributed writer authority denied"
        )
        if _is_live_trading_active_now():
            raise RuntimeError(
                "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: another instance owns writer authority"
            )
        return False
    print(f"🔒 Process lock acquired (PID {os.getpid()}) — {_PID_FILE}")



    return True


def _release_process_lock() -> None:
    """Remove the PID file on clean exit."""
    _distributed_writer_lock_stop.set()
    _release_distributed_process_lock()
    _release_nonce_writer_lease()
    try:
        if os.path.exists(_PID_FILE):
            with open(_PID_FILE) as _pf:
                _stored = int(_pf.readline().strip())
            if _stored == os.getpid():
                os.remove(_PID_FILE)
    except Exception:
        pass


def _apply_startup_debug_env_aliases() -> None:
    """Apply operator-friendly debug env aliases before lock acquisition."""
    _fail_fast_singleton = os.environ.get("FAIL_FAST_SINGLETON", "").strip().lower()
    if _fail_fast_singleton in ("0", "false", "no", "off"):
        if "NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE" not in os.environ:
            os.environ["NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE"] = "true"
        print(
            "⚠️  Debug override: FAIL_FAST_SINGLETON=false -> "
            "NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE=true",
            flush=True,
        )


def _emit_boot_trace(stage: str, detail: str) -> None:
    """Print an always-flushed boot marker for early startup debugging."""
    print(f"{stage}: {detail}", flush=True)


def _log_startup_trace(context: str) -> None:
    """Log the current call stack and thread state for startup path tracing.

    Call this from every possible entry point so we can identify which code
    path is actually being used when the bot starts.  Uses both print() and
    logger so the trace appears in both stdout and the rotating log file.
    """
    import traceback as _tb
    _stack_lines = _tb.format_stack()
    _stack_str = "".join(_stack_lines).strip()
    _ts = datetime.now(timezone.utc).isoformat()
    _thread = threading.current_thread()
    _all_threads = [
        f"{t.name}(id={t.ident},daemon={t.daemon},alive={t.is_alive()})"
        for t in threading.enumerate()
    ]
    _msg = (
        f"DIAG_STARTUP_TRACE context={context!r} "
        f"ts={_ts} "
        f"pid={os.getpid()} "
        f"thread={_thread.name} "
        f"thread_id={_thread.ident} "
        f"all_threads=[{', '.join(_all_threads)}] "
        f"stack=\n{_stack_str}"
    )
    print(_msg, flush=True)
    try:
        logger.info(_msg)
    except Exception:
        pass


_health_server_started: bool = False


def _start_health_server():
    """
    Start HTTP health server with Railway-optimized liveness endpoint.

    CRITICAL for Railway deployment:
    - /health and /healthz ALWAYS return 200 OK (stateless, < 50ms)
    - No dependencies on bot state, locks, or initialization
    - Binds immediately before any Kraken connections or user loading

    This prevents Railway from killing the container during startup.
    Called at module load time so the health server is live even while the
    distributed writer lock acquisition is retrying (fail-closed standby).

    Other endpoints:
    - /ready or /readiness - Readiness probe (is service ready to handle traffic?)
    - /status - Detailed status information for operators
    """
    global _health_server_started
    if _health_server_started:
        return
    _health_server_started = True
    try:
        # Resolve port with a safe default if env is missing
        port_env = os.getenv("PORT", "")
        default_port = 8080
        try:
            port = int(port_env) if port_env else default_port
        except Exception:
            port = default_port
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import json

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    # Railway liveness probe - ALWAYS returns 200 OK (stateless, no checks)
                    # No logging. No conditionals. No imports. Dumb and fast wins.
                    # This ensures Railway never kills the container during startup
                    if self.path in ("/health", "/healthz"):
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain")
                        self.end_headers()
                        self.wfile.write(b"ok")

                    # Readiness probe - returns 200 only if ready, 503 if not ready/config error
                    elif self.path in ("/ready", "/readiness"):
                        try:
                            from bot.health_check import get_health_manager
                            health_manager = get_health_manager()
                            status, http_code = health_manager.get_readiness_status()
                            self.send_response(http_code)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps(status).encode())
                        except Exception:
                            # If health manager not ready, return not ready
                            self.send_response(503)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"status": "not_ready", "reason": "initializing"}).encode())

                    # Detailed status for operators and debugging
                    elif self.path in ("/status", "/"):
                        try:
                            from bot.health_check import get_health_manager
                            health_manager = get_health_manager()
                            status: dict[str, object] = health_manager.get_detailed_status()
                            try:
                                from bot.execution_authority_context import get_distributed_writer_authority_status
                            except ImportError:
                                from execution_authority_context import get_distributed_writer_authority_status  # type: ignore[import]

                            try:
                                status["writer_lock"] = get_distributed_writer_authority_status(force_refresh=False)
                            except Exception as lock_err:
                                status["writer_lock"] = {"ok": False, "error": str(lock_err)}

                            _writer_lock_status = status.get("writer_lock")
                            if isinstance(_writer_lock_status, dict):
                                status["writer_lock_ok"] = bool(_writer_lock_status.get("ok", False))
                            else:
                                status["writer_lock_ok"] = False

                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps(status, indent=2).encode())
                        except Exception:
                            # If health manager not ready, return basic status
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            _fallback: dict[str, object] = {"status": "initializing"}
                            try:
                                from bot.execution_authority_context import get_distributed_writer_authority_status
                            except ImportError:
                                from execution_authority_context import get_distributed_writer_authority_status  # type: ignore[import]

                            try:
                                _fallback["writer_lock"] = get_distributed_writer_authority_status(force_refresh=False)
                            except Exception as lock_err:
                                _fallback["writer_lock"] = {"ok": False, "error": str(lock_err)}

                            _fallback_writer_lock = _fallback.get("writer_lock")
                            if isinstance(_fallback_writer_lock, dict):
                                _fallback["writer_lock_ok"] = bool(_fallback_writer_lock.get("ok", False))
                            else:
                                _fallback["writer_lock_ok"] = False

                            self.wfile.write(json.dumps(_fallback, indent=2).encode())

                    # Prometheus metrics endpoint
                    elif self.path == "/metrics":
                        try:
                            from bot.health_check import get_health_manager
                            health_manager = get_health_manager()
                            metrics = health_manager.get_prometheus_metrics()
                            self.send_response(200)
                            self.send_header("Content-Type", "text/plain; version=0.0.4")
                            self.end_headers()
                            self.wfile.write(metrics.encode())
                        except Exception:
                            # Return minimal metrics if health manager not ready
                            self.send_response(200)
                            self.send_header("Content-Type", "text/plain; version=0.0.4")
                            self.end_headers()
                            self.wfile.write(b"# Initializing\nnija_up 1\n")

                    # Distributed writer lock authority self-test
                    elif self.path == "/writer-lock":
                        try:
                            from bot.execution_authority_context import get_distributed_writer_authority_status
                        except ImportError:
                            from execution_authority_context import get_distributed_writer_authority_status  # type: ignore[import]

                        try:
                            lock_status = get_distributed_writer_authority_status(force_refresh=True)
                            http_code = 200
                            if lock_status.get("strict_required") and not lock_status.get("ok"):
                                http_code = 503
                            self.send_response(http_code)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps(lock_status, indent=2).encode())
                        except Exception as lock_err:
                            self.send_response(500)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"ok": False, "error": str(lock_err)}).encode())

                    else:
                        self.send_response(404)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "error": "Not found",
                            "available_endpoints": ["/health", "/healthz", "/ready", "/readiness", "/status", "/metrics", "/writer-lock"]
                        }).encode())
                except Exception as e:
                    try:
                        self.send_response(500)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": str(e)}).encode())
                    except Exception:
                        pass

            def log_message(self, format, *args):
                # Silence default HTTP server logging to reduce noise
                return

        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True, name="HealthServer")
        t.start()
        _health_server_started = True
        print(f"🌐 Health server listening on port {port} (Railway-optimized)")
        print(f"   📍 Liveness:  http://0.0.0.0:{port}/health (ALWAYS returns 200 OK)")
        print(f"   📍 Readiness: http://0.0.0.0:{port}/ready")
        print(f"   📍 Status:    http://0.0.0.0:{port}/status")
        print(f"   📍 Metrics:   http://0.0.0.0:{port}/metrics")
    except Exception as e:
        print(f"❌ Health server failed to start: {e}")


_apply_startup_debug_env_aliases()
def _apply_startup_debug_env_aliases() -> None:
    """Apply operator-friendly debug env aliases before lock acquisition."""
    _fail_fast_singleton = os.environ.get("FAIL_FAST_SINGLETON", "").strip().lower()
    if _fail_fast_singleton in ("0", "false", "no", "off"):
        if "NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE" not in os.environ:
            os.environ["NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE"] = "true"
        print(
            "⚠️  Debug override: FAIL_FAST_SINGLETON=false -> "
            "NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE=true",
            flush=True,
        )


def _emit_boot_trace(stage: str, detail: str) -> None:
    """Print an always-flushed boot marker for early startup debugging."""
    print(f"{stage}: {detail}", flush=True)


_apply_startup_debug_env_aliases()
# Start health server BEFORE the writer-lock acquisition loop so Railway
# health checks pass even while the bot is retrying Redis lock acquisition
# in fail-closed standby (the bot is blocked at the lock gate, not the
# trading engine — health/liveness must remain reachable throughout).
_start_health_server()
_acquire_process_lock()

# ── Fallback fencing token bootstrap ─────────────────────────────────────────
# If the Redis distributed lock was not acquired (e.g. Redis unavailable or
# lock not required in this deployment), NIJA_WRITER_FENCING_TOKEN will not be
# set.  Generate a process-local UUID token and attempt to register it in Redis
# so that assert_distributed_writer_authority() and the writer-heartbeat gate
# can pass.  This is a best-effort operation; if Redis is unavailable the
# authority heartbeat monitor will use ping-only verification.
if not os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip():
    try:
        import uuid as _uuid_mod
        import hashlib as _hashlib_mod
        _fb_token = str(_uuid_mod.uuid4())
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = _fb_token
        os.environ["NIJA_WRITER_FENCING_TOKEN_FALLBACK"] = "1"
        print(
            f"⚠️  NIJA_WRITER_FENCING_TOKEN not set by Redis lock; "
            f"generated process-local fallback token={_fb_token[:8]}... "
            "for authority heartbeat",
            flush=True,
        )
        # Attempt to register the fallback token in Redis.
        try:
            from bot.redis_env import get_redis_url as _get_redis_url_fb
            _fb_redis_url = _get_redis_url_fb()
            if _fb_redis_url:
                import redis as _redis_mod_fb
                _fb_scope_raw = (
                    os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
                    or os.environ.get("KRAKEN_API_KEY", "").strip()
                    or "default"
                )
                _fb_scope = _hashlib_mod.sha256(_fb_scope_raw.encode("utf-8")).hexdigest()[:16]
                _fb_lock_key = (
                    os.environ.get("NIJA_WRITER_LOCK_KEY", "").strip()
                    or f"nija:writer_lock:{_fb_scope}"
                )
                _fb_ttl_s = max(30, int(os.environ.get("NIJA_WRITER_LOCK_TTL_S", "30") or 30))
                _fb_owner = os.environ.get("NIJA_WRITER_OWNER_ID", "fallback")
                _fb_value = f"{_fb_token}:{_fb_owner}"
                _fb_client = _redis_mod_fb.from_url(
                    _fb_redis_url,
                    decode_responses=True,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )
                _fb_set = _fb_client.set(_fb_lock_key, _fb_value, ex=_fb_ttl_s, nx=True)
                if _fb_set:
                    os.environ["NIJA_WRITER_LOCK_KEY"] = _fb_lock_key
                    os.environ["NIJA_WRITER_LOCK_SCOPE"] = _fb_scope
                    os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
                    os.environ["NIJA_WRITER_FENCING_TOKEN_FALLBACK"] = "0"
                    _fb_now_ts = str(time.time())
                    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
                    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = _fb_now_ts
                    os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = _fb_now_ts
                    print(
                        f"✅ Fallback fencing token registered in Redis: "
                        f"key={_fb_lock_key} ttl={_fb_ttl_s}s",
                        flush=True,
                    )
                else:
                    print(
                        f"⚠️  Redis lock key {_fb_lock_key} already held; "
                        "using fallback-token (ping-only) authority mode",
                        flush=True,
                    )
        except Exception as _fb_redis_err:
            print(
                f"⚠️  Could not register fallback fencing token in Redis: {_fb_redis_err}",
                flush=True,
            )
    except Exception as _fb_err:
        print(f"⚠️  Fallback fencing token generation failed: {_fb_err}", flush=True)


# Load .env and verify the result at runtime
_dotenv_loaded = False
try:
    _dotenv_mod = importlib.import_module("dotenv")
    load_dotenv = getattr(_dotenv_mod, "load_dotenv", None)
    if callable(load_dotenv):
        from pathlib import Path as _Path
        _env_path = _Path(__file__).parent / ".env"
        if _env_path.exists():
            load_dotenv(str(_env_path))
            _dotenv_loaded = True
        else:
            # No .env file — env vars must be injected by the platform (e.g. Railway)
            load_dotenv()  # still call so any inline env exports are picked up
except Exception:
    pass  # dotenv not available, env vars should be set externally

# Setup paths (must come before _verify_env so trading_state_machine is importable)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# ── Bootstrap FSM — best-effort import ───────────────────────────────────────
# Imported here so transitions are available throughout the module.  All usage
# is wrapped in try/except so a missing or broken module never stops the bot.
_BALANCE_HYDRATED_STATE_VALUES = {
    "BALANCE_HYDRATED",
    "CAPITAL_REFRESHING",
    "CAPITAL_READY",
    "INIT_COMPLETE",
    "THREADS_STARTING",
    "RUNNING_SUPERVISED",
}
_BOOTSTRAP_LOCK_READY_STATE_VALUES = {
    "LOCK_ACQUIRED",
    "HEALTH_BOUND",
    "ENV_VERIFIED",
    "CAPABILITY_VERIFIED",
    "STARTUP_VALIDATED",
    "MODE_GATED",
    "PLATFORM_CONNECTING",
    "PLATFORM_READY",
    "BALANCE_HYDRATED",
    "CAPITAL_REFRESHING",
    "CAPITAL_READY",
    "INIT_COMPLETE",
    "THREADS_STARTING",
    "RUNNING_SUPERVISED",
}
try:
    _bfsm_mod = importlib.import_module("bot.bootstrap_state_machine")
    _BootstrapState = cast(Any, getattr(_bfsm_mod, "BootstrapState"))
    _get_bootstrap_fsm = cast(Any, getattr(_bfsm_mod, "get_bootstrap_fsm"))
    _balance_states = getattr(_bfsm_mod, "BALANCE_POLLING_DISABLED_STATES", None)
    if _balance_states:
        _BALANCE_HYDRATED_STATE_VALUES = {state.value for state in _balance_states}
    _BOOTSTRAP_FSM_AVAILABLE = True
except ImportError:
    class _BootstrapStateFallback:
        BOOT_INIT = "BOOT_INIT"
        LOCK_ACQUIRED = "LOCK_ACQUIRED"
        HEALTH_BOUND = "HEALTH_BOUND"
        ENV_VERIFIED = "ENV_VERIFIED"
        CAPABILITY_VERIFIED = "CAPABILITY_VERIFIED"
        STARTUP_VALIDATED = "STARTUP_VALIDATED"
        MODE_GATED = "MODE_GATED"
        PLATFORM_CONNECTING = "PLATFORM_CONNECTING"
        PLATFORM_READY = "PLATFORM_READY"
        BALANCE_HYDRATED = "BALANCE_HYDRATED"
        CAPITAL_REFRESHING = "CAPITAL_REFRESHING"
        CAPITAL_READY = "CAPITAL_READY"
        INIT_COMPLETE = "INIT_COMPLETE"
        THREADS_STARTING = "THREADS_STARTING"
        RUNNING_SUPERVISED = "RUNNING_SUPERVISED"
        BOOT_FAILED_RETRY = "BOOT_FAILED_RETRY"
        CONFIG_ERROR_KEEPALIVE = "CONFIG_ERROR_KEEPALIVE"
        EXTERNAL_RESTART_REQUIRED = "EXTERNAL_RESTART_REQUIRED"
        SHUTDOWN = "SHUTDOWN"

    _BootstrapState = cast(Any, _BootstrapStateFallback)

    class _NoopBootstrapFSM:
        def __init__(self) -> None:
            self.state = _BootstrapState.BOOT_INIT

        def transition(self, state: Any, reason: str = "") -> None:
            self.state = state

        def claim_bootstrap_ownership(self) -> None:
            return

        def reset_for_retry(self, reason: str = "") -> None:
            self.state = _BootstrapState.BOOT_INIT

        def is_balance_hydrated(self) -> bool:
            _state_value = getattr(self.state, "value", "")
            return _state_value in _BALANCE_HYDRATED_STATE_VALUES

    _NOOP_BOOTSTRAP_FSM = _NoopBootstrapFSM()

    _get_bootstrap_fsm = cast(Any, lambda: _NOOP_BOOTSTRAP_FSM)

    _BOOTSTRAP_FSM_AVAILABLE = False


def _bfsm_transition(state, reason: str = "") -> None:
    """Best-effort bootstrap FSM transition.  Never raises; never blocks."""
    if not _BOOTSTRAP_FSM_AVAILABLE:
        return
    try:
        _bfsm = _get_bootstrap_fsm()
        _bfsm.transition(state, reason)
    except Exception as _bfsm_err:
        try:
            import logging as _lg
            _lg.getLogger("nija.bootstrap_fsm").debug(
                "bootstrap FSM transition to %s failed (non-fatal): %s", state, _bfsm_err
            )
        except Exception:
            pass


_execution_layer_initialized = False
_execution_layer_init_lock = threading.Lock()

# ── Bootstrap Coordinator — single source of truth for bootstrap authority ───
# Consolidates all startup authority into one coordinator with explicit phase
# barriers.  All auxiliary daemons block on their prerequisite phase before
# starting.  Imported here so the coordinator is available throughout the module.
_BOOTSTRAP_COORDINATOR_AVAILABLE = False  # default; set to True on successful import below
try:
    from bot.bootstrap_coordinator import (
        BootstrapCoordinator as _BootstrapCoordinator,
        BootstrapPhase as _BootstrapPhase,
        BootstrapPhaseError as _BootstrapPhaseError,
        get_bootstrap_coordinator as _get_bootstrap_coordinator,
    )
    _BOOTSTRAP_COORDINATOR_AVAILABLE = True
    logger.info(
        "BootstrapCoordinator: imported successfully pid=%d",
        os.getpid(),
    )
except ImportError as _bc_import_err:
    _BOOTSTRAP_COORDINATOR_AVAILABLE = False
    _get_bootstrap_coordinator = None  # type: ignore[assignment]
    _BootstrapPhase = None  # type: ignore[assignment]
    _BootstrapPhaseError = RuntimeError  # type: ignore[assignment]
    logger.warning(
        "BootstrapCoordinator: import failed (non-fatal, coordinator disabled): %s",
        _bc_import_err,
    )


def run_bootstrap() -> None:
    """Single initialization entry point.

    All subsystem initialization MUST pass through here via InitRegistry.run_once().
    This function is the ONLY place allowed to drive multi-subsystem startup.
    Called from the BotStartup thread after acquire_bootstrap_guard().
    """
    try:
        from bot.init_registry import InitRegistry as _IR
    except ImportError:
        logger.warning("[run_bootstrap] InitRegistry not available — falling back to direct init")
        initialize_execution_layer()
        return

    # ── 1. Feature flags (if module exists) ────────────────────────────────
    def _init_feature_flags() -> None:
        try:
            _ff_mod = importlib.import_module("bot.feature_flags")
            _iff = getattr(_ff_mod, "initialize_feature_flags", None)
            if callable(_iff):
                _iff()
        except Exception:
            pass

    _IR.run_once("FEATURE_FLAGS", _init_feature_flags)

    # ── 2. ECEL ─────────────────────────────────────────────────────────────
    def _init_ecel() -> None:
        try:
            from bot.ecel_execution_compiler import initialize_ecel as _ie
            _ie()
        except ImportError:
            pass

    _IR.run_once("ECEL", _init_ecel)

    # ── 3. MABM ─────────────────────────────────────────────────────────────
    def _init_mabm() -> None:
        from bot.multi_account_broker_manager import multi_account_broker_manager as _mabm
        _mabm.initialize()

    _IR.run_once("MABM", _init_mabm)

    # ⚡ FAST VERIFICATION (Step 2: Don't skip) — Print activation state
    try:
        from bot.trading_state_machine import get_state_machine as _get_tsm_verify
        _tsm_verify = _get_tsm_verify()
        _verify_state = _tsm_verify.get_current_state().value
        _verify_live = _tsm_verify.is_live_trading_active()
        logger.info(
            "⚡ FAST VERIFICATION: state=%s live=%s %s",
            _verify_state,
            _verify_live,
            "✅ (trading active)" if _verify_live else "⚠️ (NOT LIVE — CHECK GATES)",
        )
    except Exception as _verify_err:
        logger.warning("[run_bootstrap] Fast verification failed: %s", _verify_err)

    # ── 4. Execution layer ownership (capital FSM bootstrap) ────────────────
    _IR.run_once("EXECUTION_LAYER", initialize_execution_layer)


def initialize_execution_layer() -> None:
    """One-time execution-layer bootstrap guard.

    Ownership model:
    - Called only by BotStartup/bootstrap thread.
    - Drives CapitalBootstrapFSM early startup states.
    - Idempotent via module-level guard.
    """
    global _execution_layer_initialized
    with _execution_layer_init_lock:
        if _execution_layer_initialized:
            return
        _execution_layer_initialized = True

    try:
        try:
            from bot.capital_flow_state_machine import (
                CapitalBootstrapState as _CapitalBootstrapState,
                get_capital_bootstrap_fsm as _get_capital_bootstrap_fsm,
            )
        except ImportError:
            from capital_flow_state_machine import (  # type: ignore[import]
                CapitalBootstrapState as _CapitalBootstrapState,
                get_capital_bootstrap_fsm as _get_capital_bootstrap_fsm,
            )

        _capital_boot_fsm = _get_capital_bootstrap_fsm()
        _capital_boot_fsm.claim_bootstrap_ownership()
        _capital_boot_fsm.transition(
            _CapitalBootstrapState.WAIT_PLATFORM,
            "bootstrap_execution_layer_init",
        )
    except Exception as _exec_layer_err:
        logger.warning("[Bootstrap] initialize_execution_layer failed: %s", _exec_layer_err)


# Verify critical environment variables are present
def _verify_env() -> None:
    """Warn loudly if required runtime variables are absent after .env loading."""
    import logging as _log
    _ev = _log.getLogger("nija.env")
    _ev.info("=" * 60)
    if _dotenv_loaded:
        _ev.info("✅ .env file loaded from disk")
    else:
        _ev.info("ℹ️  No .env file on disk — relying on platform environment variables")

    _required = {
        "COINBASE_API_KEY":    "Coinbase API key",
        "COINBASE_API_SECRET": "Coinbase API secret",
        "LIVE_CAPITAL_VERIFIED": "Live-trading safety gate",
    }
    _missing = [name for name in _required if not os.getenv(name)]
    if _missing:
        for name in _missing:
            _ev.warning("⚠️  Missing required env var: %s (%s)", name, _required[name])
        _ev.warning(
            "⚠️  Set the above variables in your .env file (local) "
            "or in the Railway Variables tab (production)."
        )
    else:
        _ev.info("✅ All required environment variables are present")

    # Kraken platform credentials must BOTH be present or BOTH absent.
    # A partial configuration (key without secret, or vice versa) causes the
    # platform-first gate to mark Kraken as failed at startup, which permanently
    # blocks user accounts from connecting for the lifetime of the process.
    kraken_api_key    = os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY")
    kraken_api_secret = os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET")
    if bool(kraken_api_key) != bool(kraken_api_secret):
        _ev.warning(
            "⚠️  Kraken credentials are INCOMPLETE — set BOTH "
            "KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET "
            "(or leave both empty to disable Kraken). "
            "A partial config causes the platform-first gate to block ALL user accounts."
        )
    elif kraken_api_key and kraken_api_secret:
        _ev.info("✅ Kraken platform credentials detected")
    _lcv = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower().strip()
    if _lcv in ("true", "1", "yes", "enabled"):
        # Activation is now owned exclusively by the core trading loop.
        # maybe_auto_activate() is NOT called here — the loop drives it.
        _ev.info("ℹ️  LIVE_CAPITAL_VERIFIED=true detected — activation will be handled by the core loop")
    else:
        _ev.info(
            "🔒 LIVE_CAPITAL_VERIFIED is not 'true' — live trading remains OFF. "
            "Set LIVE_CAPITAL_VERIFIED=true in .env to enable."
        )
    _ev.info("=" * 60)

_verify_env()


# =====================================================================
# BOOTSTRAP PRELOAD LAYER — Balance Hydration Before Strategy Import
# =====================================================================
# CRITICAL: Must run BEFORE trading_strategy import so risk config can
# read ACCOUNT_BALANCE from environment.
def _bootstrap_hydrate_account_balances() -> dict:
    """
    Hydrate account balances at startup, BEFORE strategy initialization.
    Sets ACCOUNT_BALANCE, ACCOUNT_EQUITY, ACCOUNT_AVAILABLE env vars.
    
    CRITICAL GUARDS:
    - Exchange balance fetch is MANDATORY (must initialize broker manager first)
    - Mock/default balances are BLOCKED in live mode
    - Fails closed if balance <= 0 in live mode
    """
    try:
        print("💰 BOOTSTRAP BALANCE HYDRATION: STARTING")
        
        _is_live = os.environ.get("LIVE_CAPITAL_VERIFIED", "").strip().lower() in ("1", "true", "yes", "enabled")

        _balance_override_raw = os.environ.get("ACCOUNT_BALANCE_OVERRIDE", "").strip()
        if _balance_override_raw:
            try:
                _override = float(_balance_override_raw)
                if _override > 0:
                    print(f"⚠️ ACCOUNT_BALANCE_OVERRIDE active — forcing bootstrap balance=${_override:.2f}")
                    os.environ["ACCOUNT_BALANCE"] = f"{_override:.8f}"
                    os.environ["ACCOUNT_EQUITY"] = f"{_override:.8f}"
                    os.environ["ACCOUNT_AVAILABLE"] = f"{_override:.8f}"
                    return {
                        "total_usd": _override,
                        "equity": _override,
                        "available": _override,
                        "source": "override",
                    }
            except ValueError:
                print(f"⚠️ Invalid ACCOUNT_BALANCE_OVERRIDE={_balance_override_raw!r}; ignoring override")
        
        # 🔥 STEP 1: Initialize broker manager BEFORE any balance fetch
        try:
            from bot.multi_account_broker_manager import multi_account_broker_manager
            mabm = multi_account_broker_manager
            
            # 🔥 STEP 2: Force initialization
            print("🔧 FORCING BROKER MANAGER INITIALIZATION...")
            mabm.initialize()
            
            # 🔥 STEP 3: Check readiness
            if not mabm.is_ready():
                raise RuntimeError("BrokerManager failed to initialize — not ready for balance fetch")

            # 🔥 STEP 3.5: Ensure platform brokers are created/connected before hydration
            print("🔌 INITIALIZING PLATFORM BROKERS...")
            _platform_init = mabm.initialize_platform_brokers()
            _connected_platforms = [
                _k for _k, _meta in (_platform_init or {}).items()
                if bool((_meta or {}).get("connected", False))
            ]
            _connected_platform_labels = [str(_p) for _p in _connected_platforms]
            print(
                "✅ PLATFORM BROKER INIT COMPLETE: "
                f"connected={len(_connected_platforms)} "
                f"({', '.join(_connected_platform_labels) if _connected_platform_labels else 'none'})"
            )
            
            print("✅ BROKER MANAGER INITIALIZED — FETCHING BALANCES")
            print("Fetching Kraken balance...")
            
            # 🔥 STEP 4: Fetch balances (now safe, will raise if balance is None)
            balances = None
            total_usd = 0.0
            try:
                balances = mabm.get_all_balances()
                print(f"Balance response: {balances}")
                total_usd = _sum_nested_balances(balances)
            except Exception as _bal_err:
                print(f"⚠️  Aggregate balance fetch failed: {_bal_err}")
                balances = {"platform": {}, "users": {}, "error": str(_bal_err)}

            # Live-mode resilience: if aggregate fetch fails/zeros out, try direct
            # Kraken PLATFORM balance so Kraken can continue trading even if a
            # secondary broker payload is temporarily unavailable.
            if _is_live and total_usd <= 0:
                try:
                    from bot.broker_manager import BrokerType as _BrokerType

                    _kraken = mabm.platform_brokers.get(_BrokerType.KRAKEN)
                    if _kraken and getattr(_kraken, "connected", False):
                        _kraken_balance = _kraken.get_account_balance()
                        if _kraken_balance is not None:
                            _kraken_total = _sum_nested_balances({"platform": {"kraken": _kraken_balance}})
                            if _kraken_total > 0:
                                total_usd = float(_kraken_total)
                                balances = {
                                    "platform": {"kraken": _kraken_balance},
                                    "users": {},
                                    "source": "kraken_direct_fallback",
                                }
                                print(
                                    "✅ LIVE fallback: using direct Kraken PLATFORM balance "
                                    f"(${total_usd:.2f})"
                                )
                except Exception as _kraken_bal_err:
                    print(f"⚠️  Kraken direct-balance fallback failed: {_kraken_bal_err}")
            
            # 🔥 GUARD 1: Exchange balance must be > 0
            if total_usd <= 0:
                if _is_live:
                    raise RuntimeError(
                        f"CRITICAL: Exchange balance fetch failed — balance is ${total_usd:.2f} (zero/negative not allowed in LIVE mode)"
                    )
                print(f"⚠️  Warning: Exchange balance is ${total_usd:.2f} (non-live mode, continuing)")
            
            os.environ["ACCOUNT_BALANCE"] = f"{total_usd:.8f}"
            os.environ["ACCOUNT_EQUITY"] = f"{total_usd:.8f}"
            # Available is assumed equal to total at bootstrap time
            os.environ["ACCOUNT_AVAILABLE"] = f"{total_usd:.8f}"
            
            print(f"✅ BOOTSTRAP HYDRATION COMPLETE: balance=${total_usd:.2f} (source=broker_manager)")
            return {
                "total_usd": total_usd,
                "equity": total_usd,
                "available": total_usd,
                "source": "broker_manager",
            }
        except Exception as _mabm_err:
            print(f"⚠️  Bootstrap hydration via broker_manager failed: {_mabm_err}")
            if _is_live:
                raise RuntimeError(f"CRITICAL: Broker manager initialization failed in LIVE mode: {_mabm_err}") from _mabm_err
        
        # Fallback: use existing hydrated balance if available
        existing_balance = os.environ.get("ACCOUNT_BALANCE", "").strip()
        if existing_balance:
            try:
                total_usd = float(existing_balance)
                
                # 🔥 HARD FAIL GUARD 2: Mock/default balances blocked in live mode
                if _is_live:
                    raise RuntimeError(
                        "CRITICAL: Mock/cached balance detected in LIVE mode — "
                        "refusing to trade with non-exchange balance. "
                        "Exchange connection required for real trading."
                    )
                
                os.environ["ACCOUNT_EQUITY"] = existing_balance
                os.environ["ACCOUNT_AVAILABLE"] = existing_balance
                print(f"✅ BOOTSTRAP HYDRATION: using cached balance=${total_usd:.2f} (source=environment_cache)")
                return {
                    "total_usd": total_usd,
                    "equity": total_usd,
                    "available": total_usd,
                    "source": "environment_cache",
                }
            except ValueError:
                pass
        
        # If live mode and no balance available, fail closed
        if _is_live:
            raise RuntimeError(
                "CRITICAL: Exchange balance fetch failed in LIVE mode — "
                "no balance provider available and no cached balance set. "
                "Refusing to start trading without real exchange balance."
            )
        
        # In non-live mode, warn but continue with default
        print("⚠️  BOOTSTRAP HYDRATION: no balance available (non-live mode, continuing)")
        os.environ.setdefault("ACCOUNT_BALANCE", "0")
        os.environ.setdefault("ACCOUNT_EQUITY", "0")
        os.environ.setdefault("ACCOUNT_AVAILABLE", "0")
        return {
            "total_usd": 0.0,
            "equity": 0.0,
            "available": 0.0,
            "source": "default",
        }
        
    except Exception as _bootstrap_err:
        os.environ["NIJA_BALANCE_HYDRATION_LAST_ERROR"] = str(_bootstrap_err)
        print(f"❌ BOOTSTRAP BALANCE HYDRATION FAILED: {_bootstrap_err}")
        print("   Verify exchange API key/secret, key permissions, and IP restrictions.")
        raise


# Run bootstrap balance hydration before strategy import
try:
    _bootstrap_balances = _bootstrap_hydrate_account_balances()
except RuntimeError as _bootstrap_fatal:
    print(f"🚫 Bootstrap balance hydration failed: {_bootstrap_fatal}")
    print("🚫 Bootstrap hydration is fail-closed; exiting.")
    sys.exit(1)


# Import after path setup
from trading_strategy import TradingStrategy

# Setup logging - configure ONCE to prevent duplicates
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'nija.log'))

# Remove any existing handlers first
root = logging.getLogger()
if root.handlers:
    for handler in list(root.handlers):
        root.removeHandler(handler)

# Get nija logger
logger = logging.getLogger("nija")
logger.propagate = False  # Prevent propagation to root logger


def _resolve_log_profile() -> tuple[str, int]:
    """Resolve runtime logging profile and effective nija logger level."""
    profile_raw = os.getenv("NIJA_LOG_PROFILE", "normal").strip().lower()
    profile = profile_raw if profile_raw in ("normal", "verbose") else "normal"

    # Optional explicit level override (e.g. DEBUG/INFO/WARNING).
    level_override = os.getenv("NIJA_LOG_LEVEL", "").strip().upper()
    if level_override:
        level = getattr(logging, level_override, None)
        if isinstance(level, int):
            return profile, level

    if profile == "verbose":
        return profile, logging.DEBUG
    return profile, logging.INFO


_log_profile, _nija_log_level = _resolve_log_profile()
logger.setLevel(_nija_log_level)

# Tune key noisy loggers by profile. Keep external SDK chatter limited in normal mode.
if _log_profile == "verbose":
    logging.getLogger("nija.capital_flow_sm").setLevel(logging.DEBUG)
    logging.getLogger("nija.capital_brain").setLevel(logging.DEBUG)
else:
    logging.getLogger("nija.capital_flow_sm").setLevel(logging.INFO)
    logging.getLogger("nija.capital_brain").setLevel(logging.INFO)

# Single formatter with consistent timestamp format
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add handlers only if not already present
if not logger.hasHandlers():
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=2)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    # Ensure immediate flushing to prevent log message interleaving
    console_handler.flush = lambda: sys.stdout.flush()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

logger.info(
    "🪵 Log profile active: profile=%s level=%s",
    _log_profile,
    logging.getLevelName(_nija_log_level),
)

# ── A. Startup Event Buffer ───────────────────────────────────────────────────
# Intercepts the console handler during startup so all log records are batched
# and flushed once per phase.  The file handler keeps writing immediately —
# nothing is lost.  Eliminates Railway log-throttle bursts.
_startup_buffer = None
try:
    from bot.startup_event_buffer import install_startup_buffer as _install_seb
    for _h in list(logger.handlers):
        if isinstance(_h, logging.StreamHandler) and getattr(_h, "stream", None) is sys.stdout:
            _startup_buffer = _install_seb(logger, _h)
            break
    if _startup_buffer is None:
        print("⚠️  Startup event buffer: no stdout handler found — buffer inactive")
    else:
        try:
            _flush_chunk_env = os.getenv("NIJA_STARTUP_BUFFER_MAX_LINES", "").strip()
            if _flush_chunk_env:
                _flush_chunk_size = max(0, int(_flush_chunk_env))
            elif _log_profile == "verbose":
                _flush_chunk_size = 25
            else:
                _flush_chunk_size = 0
            _startup_buffer.configure(max_lines_per_flush=_flush_chunk_size)
            if _flush_chunk_size > 0:
                logger.info(
                    "🧵 Startup buffer chunking enabled: max_lines_per_flush=%d",
                    _flush_chunk_size,
                )
        except Exception as _seb_cfg_err:
            print(f"⚠️  Startup event buffer configuration failed (non-fatal): {_seb_cfg_err}")
except Exception as _seb_err:
    print(f"⚠️  Startup event buffer unavailable (non-fatal): {_seb_err}")

# ── B. Phase Gate  +  C. Init-Once Registry ───────────────────────────────────
# Import the hard-gate enforcement layer.  A minimal fallback class is used
# when the module is unavailable so bot.py never crashes due to missing infra.
try:
    from bot.startup_phase_gate import Phase as _Phase, advance_phase as _advance_phase
    from bot.init_once_guard import check_init_once as _check_init_once
    _PHASE_GATE_AVAILABLE = True
except Exception as _pg_err:
    print(f"⚠️  Phase gate / init-once guard unavailable (non-fatal): {_pg_err}")
    _PHASE_GATE_AVAILABLE = False

    class _PhaseFallback:
        ENV_VALIDATION = BROKER_REGISTRY = CAPITAL_BRAIN = 0
        STRATEGY_ENGINE = EXECUTION_LAYER = LIVE_ENABLE = 0

    _Phase = cast(Any, _PhaseFallback)

    def _advance_phase(*_a, **_kw) -> None:  # type: ignore[misc]
        pass

    def _check_init_once(name: str) -> bool:  # type: ignore[misc]
        return True


def _log_lifecycle_banner(title, details=None):
    """
    Log a visual lifecycle banner for major state transitions.
    
    Args:
        title: The main title to display
        details: Optional list of detail strings to include
    """
    logger.info("")
    logger.info("╔" + "═" * 78 + "╗")
    logger.info(f"║ {title:^76} ║")
    if details:
        logger.info("╠" + "═" * 78 + "╣")
        for detail in details:
            logger.info(f"║ {detail:76} ║")
    logger.info("╚" + "═" * 78 + "╝")
    logger.info("")


def _log_exit_point(reason, exit_code=0, details=None):
    """
    Log a visual exit point marker before sys.exit().
    
    Args:
        reason: Why the process is exiting
        exit_code: The exit code (0 = success, 1 = error)
        details: Optional list of detail strings
    """
    icon = "✅" if exit_code == 0 else "❌"
    logger.info("")
    logger.info("┏" + "━" * 78 + "┓")
    logger.info(f"┃ {icon} EXIT POINT - {reason:68} ┃")
    logger.info(f"┃ Exit Code: {exit_code:<67} ┃")
    logger.info(f"┃ PID: {os.getpid():<71} ┃")
    if details:
        logger.info("┣" + "━" * 78 + "┫")
        for detail in details:
            logger.info(f"┃ {detail:76} ┃")
    logger.info("┗" + "━" * 78 + "┛")
    logger.info("")


def _get_thread_status():
    """Get status of all running threads for visual verification."""
    threads = threading.enumerate()
    status = []
    status.append(f"Total Threads: {len(threads)}")
    for thread in threads:
        daemon_marker = "🔹" if thread.daemon else "🔸"
        alive_marker = "✅" if thread.is_alive() else "❌"
        status.append(f"  {daemon_marker} {alive_marker} {thread.name} (ID: {thread.ident})")
    return status


def _handle_signal(sig, frame):
    """Handle shutdown signals (SIGTERM, SIGINT) with visual logging."""
    _release_process_lock()
    # Stop the heartbeat first so it doesn't renew the lock after we release it,
    # then release the Redis distributed writer lock so the next deployment can
    # acquire it immediately instead of waiting for the TTL to expire.
    _distributed_writer_lock_stop.set()
    _release_distributed_process_lock()
    try:
        from bot.bootstrap_utils import signal_shutdown
    except ImportError:
        try:
            from bootstrap_utils import signal_shutdown  # type: ignore[import]
        except ImportError:
            signal_shutdown = None  # type: ignore[assignment]
    if signal_shutdown is not None:
        signal_shutdown()
    if _BOOTSTRAP_FSM_AVAILABLE:
        _bfsm_transition(_BootstrapState.SHUTDOWN, f"signal {sig} received")
    signal_name = signal.Signals(sig).name if hasattr(signal, 'Signals') else str(sig)
    _log_exit_point(
        f"Signal {signal_name} received",
        exit_code=0,
        details=[
            "Graceful shutdown initiated by signal handler",
            "This is an expected exit (not a crash)",
            *_get_thread_status()
        ]
    )
    sys.exit(0)


def _log_kraken_connection_error_header(error_msg):
    """
    Log Kraken Master connection error header with consistent formatting.

    Args:
        error_msg: The error message to display, or None if no specific error
    """
    logger.error("")
    logger.error(f"      {ERROR_SEPARATOR}")
    logger.error(f"      🚨 KRAKEN PLATFORM CREDENTIALS ARE SET BUT CONNECTION FAILED")
    logger.error(f"      {ERROR_SEPARATOR}")
    if error_msg:
        logger.error(f"      ❌ Error: {error_msg}")
    else:
        logger.error("      ❌ No specific error message was captured")
    logger.error("")


def _log_memory_usage():
    """
    Log lightweight memory usage at startup.
    
    Logs RSS (Resident Set Size) and VMS (Virtual Memory Size) in a single line.
    Optionally warns if memory usage exceeds 70% of available system memory.
    """
    try:
        import psutil
        
        # Get current process memory info
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        
        # RSS: Resident Set Size (physical memory used)
        # VMS: Virtual Memory Size (total virtual memory)
        rss_mb = mem_info.rss / (1024 * 1024)  # Convert to MB
        vms_mb = mem_info.vms / (1024 * 1024)  # Convert to MB
        
        # Get system memory for percentage calculation
        system_mem = psutil.virtual_memory()
        total_mb = system_mem.total / (1024 * 1024)
        percent_used = (mem_info.rss / system_mem.total) * 100
        
        # Single line log with RSS and VMS
        logger.info(f"💾 Memory: RSS={rss_mb:.1f}MB, VMS={vms_mb:.1f}MB ({percent_used:.1f}% of {total_mb:.0f}MB system)")
        
        # Optional: warn if memory usage is at 70% of system memory
        if percent_used >= 70.0:
            logger.warning(f"⚠️  High memory usage: {percent_used:.1f}% (threshold: 70%)")
            
    except ImportError:
        # psutil not available - use basic resource module as fallback
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # maxrss is in KB on Linux, bytes on macOS
            import platform
            if platform.system() == 'Darwin':  # macOS
                rss_mb = usage.ru_maxrss / (1024 * 1024)
            else:  # Linux
                rss_mb = usage.ru_maxrss / 1024
            logger.info(f"💾 Memory: RSS={rss_mb:.1f}MB (psutil not available, limited info)")
        except Exception as e:
            logger.debug(f"Could not log memory usage: {e}")
    except Exception as e:
        logger.debug(f"Error logging memory usage: {e}")


def _try_recover_state_machine() -> None:
    """No-op: activation is now owned exclusively by the core trading loop.

    Formerly attempted to drive the trading state machine from OFF →
    LIVE_ACTIVE as a best-effort recovery call, but calling
    maybe_auto_activate() outside the core loop caused races.  The core
    loop (nija_core_loop.run_trading_loop) calls maybe_auto_activate()
    on every cycle and is the single authority for activation.
    """
    logger.debug("_try_recover_state_machine: no-op — activation owned by core loop")


def _start_trader_thread(independent_trader, broker_type, broker):
    """
    Wrap a single broker's trading loop in a self-healing daemon thread.

    The inner runner calls ``run_broker_trading_loop`` in a loop so that if
    the function ever returns unexpectedly (fatal crash escaping the inner
    guard), the thread automatically restarts after a 5-second back-off.
    The stop_flag is the single clean-shutdown mechanism.

    Returns:
        tuple: (threading.Thread, threading.Event) – thread and its stop flag.
    """
    broker_name = broker_type.value
    stop_flag = threading.Event()

    def _runner():
        logger.info("🚀 [Orchestrator] Trader thread started for %s", broker_name.upper())
        cycle = 0
        while not stop_flag.is_set():
            try:
                cycle += 1
                logger.info("💓 CYCLE_HEARTBEAT mode=platform broker=%s cycle=%d", broker_name.upper(), cycle)
                independent_trader.run_broker_trading_loop(broker_type, broker, stop_flag)
            except Exception as _loop_err:
                if stop_flag.is_set():
                    break
                logger.error(
                    "💥 [Orchestrator] Trader crashed for %s: %s — restarting in 5s",
                    broker_name.upper(),
                    _loop_err,
                    exc_info=True,
                )
                stop_flag.wait(5)
        logger.info("🛑 [Orchestrator] Trader thread stopped for %s", broker_name.upper())

    t = threading.Thread(target=_runner, daemon=True, name=f"Trader-{broker_name}")
    t.start()
    return t, stop_flag


def _start_single_broker_thread(strategy, cycle_secs):
    """
    Wrap ``strategy.run_cycle()`` in a self-healing daemon thread.

    Used as a fallback when ``independent_trader`` is unavailable or when no
    funded platform brokers are detected.  Any exception from ``run_cycle``
    is caught, logged, and retried after 10 seconds so the thread never dies
    silently.

    Returns:
        tuple: (threading.Thread, threading.Event) – thread and its stop flag.
    """
    stop_flag = threading.Event()

    def _is_live_active() -> bool:
        """Return True if the trading state machine is in LIVE_ACTIVE state."""
        try:
            from bot.trading_state_machine import get_state_machine as _gsm, TradingState as _TS
            return _gsm().get_current_state() == _TS.LIVE_ACTIVE
        except Exception:
            try:
                from trading_state_machine import get_state_machine as _gsm, TradingState as _TS  # type: ignore[import]
                return _gsm().get_current_state() == _TS.LIVE_ACTIVE
            except Exception:
                return False  # fail-closed: block execution if state machine is unavailable

    def _runner():
        logger.info(
            "🚀 [Orchestrator] Single-broker trading thread started (%ds cadence)",
            cycle_secs,
        )
        cycle = 0
        while not stop_flag.is_set():
            try:
                cycle += 1
                logger.info("💓 CYCLE_HEARTBEAT mode=single cycle=%d", cycle)
                logger.info("🔁 [Orchestrator] Single-broker cycle #%d", cycle)
                # Guard: skip cycle if state machine is not yet LIVE_ACTIVE.
                # Uses a conditional check instead of assert to avoid raising
                # an exception on every startup cycle before activation.
                # The outer `while not stop_flag.is_set()` re-checks the flag
                # after stop_flag.wait() returns, so no inner break is needed.
                if not _is_live_active():
                    logger.warning(
                        "⏳ [Orchestrator] Single-broker cycle #%d waiting for LIVE_ACTIVE"
                        " — retrying in 10s",
                        cycle,
                    )
                    _try_recover_state_machine()
                    stop_flag.wait(10)
                    continue
                strategy.run_cycle()
                stop_flag.wait(cycle_secs)
            except Exception as _cycle_err:
                if stop_flag.is_set():
                    break
                logger.error(
                    "❌ [Orchestrator] Single-broker cycle #%d error: %s — retrying in 10s",
                    cycle,
                    _cycle_err,
                    exc_info=True,
                )
                stop_flag.wait(10)
        logger.info("🛑 [Orchestrator] Single-broker trading thread stopped")

    t = threading.Thread(target=_runner, daemon=True, name="Trader-SingleBroker")
    t.start()
    return t, stop_flag


def _is_truthy_env(var_name: str, default: str = "false") -> bool:
    """Return True when an env var is set to a truthy string."""
    return os.environ.get(var_name, default).strip().lower() in ("1", "true", "yes", "on")


_PRE_FLIGHT_PRINT_ONCE_LOCK = threading.Lock()
_PRE_FLIGHT_PRINTED = False


def _run_preflight_check() -> bool:
    """
    Synchronous pre-flight check — runs directly in main(), before any
    background threads are spawned.

    Prints a plain-English PASS / FAIL table to stdout so that regardless
    of the logging configuration the operator always sees the result.

    Returns
    -------
    bool
        True  — every critical requirement is satisfied; startup may proceed.
        False — at least one critical blocker was found; the caller should
                sys.exit(1) immediately.
    """
    import importlib.util as _iutil

    # ── Production pre-flight: Redis PING, lock logging, single-instance,
    #    stale-lock clearance, live-mode verification ─────────────────────
    # Honors NIJA_REDIS_STARTUP_CHECK=false for environments that intentionally
    # run without Redis startup enforcement.
    _redis_startup_check_enabled = _is_truthy_env("NIJA_REDIS_STARTUP_CHECK", "true")
    if _redis_startup_check_enabled:
        try:
            from bot.production_preflight import run_preflight as _run_production_preflight
            _run_production_preflight()
        except SystemExit:
            raise  # propagate hard failures (Redis down, wrong mode, etc.)
        except Exception as _pf_exc:
            print(f"⚠️  production_preflight raised unexpectedly: {_pf_exc}", flush=True)
            # Non-fatal: allow existing checks below to continue
    else:
        print(
            "ℹ️  NIJA_REDIS_STARTUP_CHECK=false — skipping production preflight Redis gate",
            flush=True,
        )
        _truthy = {"1", "true", "yes", "on", "enabled"}
        _single_instance_assumed = (
            os.environ.get("NIJA_ASSUME_SINGLE_INSTANCE", "").strip().lower() in _truthy
        )
        _multi_instance_possible = _is_multi_instance_deployment_possible()
        if _multi_instance_possible and not _single_instance_assumed:
            print(
                "❌ NIJA_REDIS_STARTUP_CHECK=false requires explicit single-instance mode "
                "or distributed locking. Set NIJA_ASSUME_SINGLE_INSTANCE=true for "
                "single-instance deployments, or re-enable Redis startup check.",
                flush=True,
            )
            return False
        if not _single_instance_assumed:
            os.environ["NIJA_ASSUME_SINGLE_INSTANCE"] = "true"
            print(
                "ℹ️  NIJA_REDIS_STARTUP_CHECK=false with singleton topology detected; "
                "auto-setting NIJA_ASSUME_SINGLE_INSTANCE=true",
                flush=True,
            )

    SEP = "═" * 70
    checks = []   # list of (label, passed: bool, detail: str)
    blockers = []  # human-readable reasons trading cannot start

    _debug_env_keys = sorted(os.environ.keys())
    _debug_presence = {
        "NIJA_REDIS_URL": bool(os.getenv("NIJA_REDIS_URL")),
        "REDIS_URL": bool(os.getenv("REDIS_URL")),
        "COINBASE_API_KEY": bool(os.getenv("COINBASE_API_KEY")),
        "COINBASE_API_SECRET": bool(os.getenv("COINBASE_API_SECRET")),
        "KRAKEN_PLATFORM_API_KEY": bool(os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY")),
        "KRAKEN_PLATFORM_API_SECRET": bool(os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET")),
        "LIVE_CAPITAL_VERIFIED": bool(os.getenv("LIVE_CAPITAL_VERIFIED")),
    }
    print("ENV CHECK:", _debug_env_keys, flush=True)
    print(
        "ENV PRESENCE:",
        ", ".join(f"{name}={'yes' if present else 'no'}" for name, present in _debug_presence.items()),
        flush=True,
    )

    # ── 1. Kraken credentials ────────────────────────────────────────────────
    kraken_key = (
        os.getenv("KRAKEN_PLATFORM_API_KEY")
        or os.getenv("KRAKEN_USER_TANIA_GILBERT_API_KEY")
        or os.getenv("KRAKEN_API_KEY")
    )
    kraken_secret = (
        os.getenv("KRAKEN_PLATFORM_API_SECRET")
        or os.getenv("KRAKEN_USER_TANIA_GILBERT_API_SECRET")
        or os.getenv("KRAKEN_API_SECRET")
    )
    kraken_creds_ok = bool(kraken_key and kraken_secret)
    if kraken_creds_ok:
        checks.append(("Kraken credentials", True, "key and secret present"))
    else:
        missing = []
        if not kraken_key:
            missing.append("key (KRAKEN_PLATFORM_API_KEY / KRAKEN_USER_TANIA_GILBERT_API_KEY / KRAKEN_API_KEY)")
        if not kraken_secret:
            missing.append("secret (KRAKEN_PLATFORM_API_SECRET / KRAKEN_USER_TANIA_GILBERT_API_SECRET / KRAKEN_API_SECRET)")
        detail = "Missing: " + " AND ".join(missing)
        checks.append(("Kraken credentials", False, detail))
        blockers.append(f"Kraken credentials absent — {detail}")

    # ── 2. Kraken SDK (krakenex + pykrakenapi) ───────────────────────────────
    krakenex_ok = _iutil.find_spec("krakenex") is not None
    pykrakenapi_ok = _iutil.find_spec("pykrakenapi") is not None
    kraken_sdk_ok = krakenex_ok and pykrakenapi_ok
    if kraken_sdk_ok:
        checks.append(("Kraken SDK (krakenex + pykrakenapi)", True, "both modules importable"))
    else:
        missing_mods = [m for m, ok in [("krakenex", krakenex_ok), ("pykrakenapi", pykrakenapi_ok)] if not ok]
        detail = f"Missing packages: {', '.join(missing_mods)}  →  pip install {' '.join(missing_mods)}"
        checks.append(("Kraken SDK (krakenex + pykrakenapi)", False, detail))
        if kraken_creds_ok:
            # Only a blocker when Kraken creds are configured and SDK is absent
            blockers.append(f"Kraken SDK unavailable — {detail}")

    # ── 3. Coinbase (optional unless explicitly primary) ────────────────────
    coinbase_disabled = _is_truthy_env("NIJA_DISABLE_COINBASE")
    coinbase_enabled_for_trading = os.environ.get("ENABLE_COINBASE_TRADING", "true").strip().lower() not in (
        "0", "false", "no", "off"
    )
    primary_execution_venue = os.environ.get("PRIMARY_EXECUTION_VENUE", "").strip().lower()
    coinbase_required = (not coinbase_disabled) and coinbase_enabled_for_trading and primary_execution_venue == "coinbase"

    if coinbase_disabled:
        checks.append(("Coinbase SDK", True, "disabled via NIJA_DISABLE_COINBASE — skipped"))
    else:
        # Guard against ModuleNotFoundError from nested find_spec("coinbase.rest")
        # when the parent package is not installed.
        cb_root_ok = _iutil.find_spec("coinbase") is not None
        if cb_root_ok:
            cb_rest_ok = _iutil.find_spec("coinbase.rest") is not None
        else:
            cb_rest_ok = False
        cb_sdk_ok = cb_root_ok or cb_rest_ok
        cb_key = os.getenv("COINBASE_API_KEY") or ""
        cb_secret = os.getenv("COINBASE_API_SECRET") or os.getenv("COINBASE_PEM_CONTENT") or ""
        cb_creds_ok = bool(cb_key and cb_secret)
        if cb_sdk_ok and cb_creds_ok:
            checks.append(("Coinbase SDK + credentials", True, "SDK present, key and secret present"))
        elif not cb_sdk_ok:
            detail = "coinbase-advanced-py not installed  →  pip install coinbase-advanced-py  OR set NIJA_DISABLE_COINBASE=true"
            checks.append(("Coinbase SDK + credentials", not coinbase_required, detail))
            if coinbase_required:
                blockers.append(f"Coinbase SDK missing — {detail}")
        else:
            detail = "SDK present but credentials missing (COINBASE_API_KEY + COINBASE_API_SECRET/COINBASE_PEM_CONTENT)"
            checks.append(("Coinbase SDK + credentials", not coinbase_required, detail))
            if coinbase_required:
                blockers.append(f"Coinbase credentials missing — {detail}")

    # ── 4. LIVE_CAPITAL_VERIFIED flag (advisory — not a hard blocker) ────────
    live_capital = _is_truthy_env("LIVE_CAPITAL_VERIFIED")
    checks.append((
        "LIVE_CAPITAL_VERIFIED",
        True,  # always informational — not a blocker
        "ENABLED — live trades will execute" if live_capital else "not set — dry-run / paper mode active",
    ))

    # ── 5. Data directory writable ───────────────────────────────────────────
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    try:
        os.makedirs(data_dir, exist_ok=True)
        _probe = os.path.join(data_dir, ".preflight_write_probe")
        with open(_probe, "w") as _f:
            _f.write("ok")
        os.remove(_probe)
        checks.append(("Data directory writable", True, data_dir))
    except Exception as _dir_err:
        detail = f"{data_dir} — {_dir_err}"
        checks.append(("Data directory writable", False, detail))
        blockers.append(f"Data directory not writable — {detail}")

    # ── Print results (once per process) ─────────────────────────────────────
    global _PRE_FLIGHT_PRINTED
    with _PRE_FLIGHT_PRINT_ONCE_LOCK:
        emit_full_report = not _PRE_FLIGHT_PRINTED
        if emit_full_report:
            _PRE_FLIGHT_PRINTED = True

    if emit_full_report:
        print("", flush=True)
        print(SEP, flush=True)
        print("  🔍  NIJA PRE-FLIGHT CHECK", flush=True)
        print(SEP, flush=True)
        for label, passed, detail in checks:
            icon = "  ✅" if passed else "  ❌"
            print(f"{icon}  {label}", flush=True)
            if detail:
                print(f"       {detail}", flush=True)
        print(SEP, flush=True)

        if blockers:
            print("CONFIG LOADED:", False, flush=True)
            print("CONFIG BLOCKERS:", blockers, flush=True)
            print("", flush=True)
            print("  🚫  TRADING CANNOT START — fix the following:", flush=True)
            for i, reason in enumerate(blockers, 1):
                print(f"       {i}. {reason}", flush=True)
            print("", flush=True)
            print(SEP, flush=True)
            print("", flush=True)
            return False

        print("", flush=True)
        print("CONFIG LOADED:", True, flush=True)
        print("  🚀  ALL CHECKS PASSED — proceeding to start trading", flush=True)
        print(SEP, flush=True)
        print("", flush=True)
        return True

    # Re-checks still execute, but avoid replaying the full pre-flight banner.
    if blockers:
        print("CONFIG LOADED:", False, flush=True)
        print("CONFIG BLOCKERS:", blockers, flush=True)
        print("🚫 NIJA pre-flight re-check failed — see blocker details below.", flush=True)
        for i, reason in enumerate(blockers, 1):
            print(f"   {i}. {reason}", flush=True)
        return False
    print("CONFIG LOADED:", True, flush=True)
    return True


def _coinbase_sdk_is_available() -> bool:
    """Return True if Coinbase SDK import path is available."""
    try:
        import importlib.util as _iutil
        return _iutil.find_spec("coinbase.rest") is not None
    except Exception:
        return False


def _resolve_kraken_startup_credentials() -> tuple:
    """Resolve Kraken startup credentials from supported sources in priority order.

    Returns:
        tuple[str | None, str | None]: (key, secret)
    """
    key = (
        os.getenv("KRAKEN_PLATFORM_API_KEY")
        or os.getenv("KRAKEN_USER_TANIA_GILBERT_API_KEY")
        or os.getenv("KRAKEN_API_KEY")
    )
    secret = (
        os.getenv("KRAKEN_PLATFORM_API_SECRET")
        or os.getenv("KRAKEN_USER_TANIA_GILBERT_API_SECRET")
        or os.getenv("KRAKEN_API_SECRET")
    )
    return key, secret


def _verify_startup_truth_conditions(
    strategy,
    active_threads: dict,
    *,
    kraken_credentials_valid: bool,
) -> None:
    """
    Enforce startup truth conditions before entering supervised loop.
    Raises RuntimeError when any required condition is not met.

    Kraken-specific checks (Condition A) are skipped when Kraken credentials
    are not configured so that Coinbase-only deployments are not blocked.
    """
    # Determine whether Kraken is actually configured for this deployment.
    _kraken_configured = bool(
        (os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY"))
        and (os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET"))
    )

    if _kraken_configured:
        # Condition A — Kraken credentials valid (loaded + structurally valid)
        if not kraken_credentials_valid:
            raise RuntimeError(
                "Condition A failed: Kraken credentials are not valid/loaded. "
                "Set valid KRAKEN_PLATFORM_API_KEY/KRAKEN_PLATFORM_API_SECRET (or legacy pair)."
            )

        # Condition A — Kraken operational (connection succeeded and no permission cache failure)
        _kraken_connected = False
        _mam = getattr(strategy, "multi_account_manager", None)
        if _mam and hasattr(_mam, "platform_brokers"):
            for _bt, _broker in (_mam.platform_brokers or {}).items():
                _name = getattr(_bt, "value", str(_bt)).lower()
                if _name == "kraken" and bool(getattr(_broker, "connected", False)):
                    _kraken_connected = True
                    break
        if not _kraken_connected:
            raise RuntimeError(
                "Condition A failed: Kraken broker is not operational. "
                "Verify API key permissions include query + trade."
            )

        try:
            from bot.broker_manager import KrakenBroker as _KB
            if "PLATFORM" in getattr(_KB, "_permission_failed_accounts", set()):
                raise RuntimeError(
                    "Condition A failed: Kraken PLATFORM permission check previously failed. "
                    "Fix API key permissions (query + trade)."
                )
        except RuntimeError:
            raise
        except Exception:
            pass

    # Required by new requirement: BrokerManager initialized
    if getattr(strategy, "broker_manager", None) is None:
        raise RuntimeError("Startup verification failed: BrokerManager did not initialize.")

    # Condition B — threads alive
    _dead_threads = [
        _key for _key, _entry in (active_threads or {}).items()
        if not (_entry.get("thread") is not None and _entry["thread"].is_alive())
    ]
    if _dead_threads:
        raise RuntimeError(
            f"Condition B failed: trader thread(s) not alive immediately after startup: {_dead_threads}"
        )

    # Condition B — FSM must be RUNNING_SUPERVISED (implies not in retry state)
    if _BOOTSTRAP_FSM_AVAILABLE:
        _state = _get_bootstrap_fsm().state
        if _state != _BootstrapState.RUNNING_SUPERVISED:
            raise RuntimeError(
                f"Condition B failed: bootstrap FSM state is {_state}, expected RUNNING_SUPERVISED."
            )

    # Diagnostic-only — relaxed market gates are checked but do not block startup.
    # Missing gate, probe errors, or IDLE responses emit warnings so external
    # feed timing and broker handshake noise cannot strand the bot pre-activation.
    _mrg = getattr(strategy, "market_readiness_gate", None)
    if _mrg is None:
        logger.warning("Startup market-readiness probe skipped: MarketReadinessGate not initialized")
    else:
        try:
            _mode, _conditions, _details = _mrg.check_market_readiness(
                atr=float(_mrg.AGGRESSIVE_ATR_MIN),
                current_price=_MARKET_GATE_PROBE_PRICE,
                adx=float(_mrg.AGGRESSIVE_ADX_MIN),
                volume_percentile=float(_mrg.AGGRESSIVE_VOLUME_PERCENTILE_MIN),
                spread_pct=float(_mrg.AGGRESSIVE_SPREAD_MAX),
                entry_score=float(getattr(_mrg, "CAUTIOUS_MIN_SCORE", 45.0)),
            )
            if getattr(_mode, "value", str(_mode)).lower() == "idle":
                logger.warning(
                    "Startup market-readiness probe returned IDLE — continuing startup without blocking activation (%s)",
                    _mode,
                )
        except Exception as _gate_err:
            logger.warning(
                "Startup market-readiness probe failed — continuing without blocking startup: %s",
                _gate_err,
            )


def _run_state_machine_loop() -> None:
    """Daemon thread: periodic trading state machine health check.

    Fires ``maybe_auto_activate()`` whenever the trading state machine reports
    it should activate.  Runs every 10 s independently of the supervisor loop
    so a supervisor stall can never mask a stuck state machine.

    Errors are swallowed; the thread must never die due to a transient SM error.
    """
    _sm = None
    _off_state = None
    # Retry the deferred import up to 5 times with exponential back-off.
    # This handles the common case where trading_state_machine is not yet on
    # sys.path when the thread is started early (before broker init adds the
    # bot/ package directory).  Without retries the thread exits immediately,
    # leaving _sm_loop_thread pointing at a dead object and blocking the
    # next _ensure_state_machine_loop_started() call until the supervisor
    # notices and recreates it.
    _MAX_IMPORT_ATTEMPTS = 5
    for _attempt in range(_MAX_IMPORT_ATTEMPTS):
        try:
            # Deferred import: trading_state_machine may not be on sys.path
            # until the bot/ package directory is added (happens during broker
            # init).  Importing here rather than at module level avoids an
            # ImportError at process startup before the path is configured.
            from bot.trading_state_machine import get_state_machine as _gsm, TradingState as _TS
            _sm = _gsm()
            _off_state = _TS.OFF
            break
        except Exception as _import_err:
            _wait = 2 ** _attempt  # 1, 2, 4, 8, 16 s
            logger.debug(
                "[SMLoop] trading_state_machine unavailable (attempt %d/%d): %s — retrying in %ds",
                _attempt + 1,
                _MAX_IMPORT_ATTEMPTS,
                _import_err,
                _wait,
            )
            if _attempt < _MAX_IMPORT_ATTEMPTS - 1:
                time.sleep(_wait)
    if _sm is None:
        logger.warning(
            "[SMLoop] Could not import trading_state_machine after %d attempts — thread exiting",
            _MAX_IMPORT_ATTEMPTS,
        )
        return
    logger.info("State machine loop thread running")

    while True:
        try:
            # Activation is now owned exclusively by the core trading loop
            # (nija_core_loop.run_trading_loop).  This thread no longer calls
            # maybe_auto_activate() — doing so outside the loop caused races.
            logger.debug("State machine loop heartbeat; activation owned by core loop")

            if not _sm.is_live_trading_active():
                if os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower() == "true":
                    logger.info("Recording activation intent for coordinator-owned commit path")
                    try:
                        try:
                            from bot.startup_coordinator import get_startup_coordinator as _get_startup_coordinator_sm_loop
                        except ImportError:
                            from startup_coordinator import get_startup_coordinator as _get_startup_coordinator_sm_loop  # type: ignore[import]
                        _get_startup_coordinator_sm_loop().record_activation_requested(
                            requested=True,
                            source="state_machine_loop",
                        )
                    except Exception as _coord_err:
                        logger.debug("State machine loop coordinator update failed: %s", _coord_err)

        except Exception:
            logger.exception("STATE_MACHINE_LOOP_ERROR")

        time.sleep(10)


def _ensure_state_machine_loop_started() -> None:
    """Start (or restart) the state machine loop daemon thread.

    Idempotent: safe to call on every supervisor entry and on every supervisor
    cycle.  A new thread is spawned whenever the existing one is None, was
    never started, or has already exited — so a dead or unstarted thread can
    never permanently block state-machine activation.

    Thread-start failures are logged and swallowed so a transient OS-level
    error (e.g. thread-limit exhaustion) never propagates to the caller.
    """
    global _sm_loop_thread

    with _sm_loop_lock:
        if not _is_balance_hydrated_ready():
            _hydration_diag = _balance_hydration_debug_status()
            logger.warning(
                "⚠️ FSM starting before balance hydration completes | diag=%s",
                _hydration_diag,
            )
            # Diagnostic only — do not block the FSM loop on hydration state.

        # Only skip if a thread exists AND is actually alive
        if _sm_loop_thread is not None and _sm_loop_thread.is_alive():
            logger.debug("State machine loop already running")
            return

        logger.info("State machine loop starting")

        _sm_loop_thread = threading.Thread(
            target=_run_state_machine_loop,
            name="StateMachineLoop",
            daemon=True,
        )
        try:
            _sm_loop_thread.start()
        except Exception as _start_err:
            logger.warning(
                "[SMLoop] Thread start failed: %s — state machine activation will rely on supervisor",
                _start_err,
            )
            _sm_loop_thread = None

        # Guard: if start() raised and cleared the reference, log and return
        # rather than crashing with AttributeError on .is_alive() / .ident.
        if _sm_loop_thread is None:
            logger.warning("[SMLoop] Thread reference is None after start attempt — skipping liveness check")
            return

        logger.info(
            "STATE_MACHINE_LOOP_STARTED alive=%s ident=%s",
            _sm_loop_thread.is_alive(),
            _sm_loop_thread.ident,
        )

        # Hard fail if thread did not actually come alive
        if not _sm_loop_thread.is_alive():
            raise RuntimeError("State machine loop failed to start")


def _rerun_supervisor_loop(state: dict) -> None:
    """
    Re-enter the supervisor loop using a previously initialised bot state.

    Called by ``_run_bot_startup_and_trading()`` when the module-level
    ``_initialized_state`` is already populated — i.e. on a *retry* after the
    supervisor loop crashed.  This avoids recreating ``TradingStrategy`` and
    re-connecting all brokers on every restart.

    Args:
        state: dict with keys ``strategy``, ``active_threads``,
               ``use_independent_trading``, and ``health_manager``.
    """
    from bot.health_check import get_health_manager

    strategy = state["strategy"]
    _active_threads = state["active_threads"]
    use_independent_trading = state["use_independent_trading"]
    health_manager = get_health_manager()

    if _is_live_trading_active_now():
        logger.info("LIVE mode active - skipping re-init, entering execution loop")
        if _start_trading_loop_from_initialized_state(reason="rerun-supervisor live-guard"):
            return
        logger.warning(
            "LIVE mode active during supervisor re-entry but trading loop start was skipped; continuing supervisor path"
        )

    logger.info(
        "♻️  Re-entering supervisor loop — init already completed "
        "(%d active thread(s))",
        len(_active_threads),
    )

    # Ensure the state machine loop thread is live before entering the
    # supervisor ``while True`` loop.  This guarantees the thread is started
    # after INIT and that the supervisor loop cannot early-return before the
    # state machine loop thread is alive.
    _ensure_state_machine_loop_started()

    # Cache the state machine once at loop entry so the per-cycle health check
    # does not repeat the import on every iteration.
    _supervisor_state_machine = None
    _supervisor_off_state = None
    try:
        from bot.trading_state_machine import get_state_machine as _gsm_sl, TradingState as _TS_sl
        _supervisor_state_machine = _gsm_sl()
        _supervisor_off_state = _TS_sl.OFF
    except Exception as _sl_import_err:
        logger.debug("_rerun_supervisor_loop: trading_state_machine unavailable (%s)", _sl_import_err)

    _orch_cycle = 0
    while True:
        try:
            _orch_cycle += 1
            health_manager.heartbeat()

            # ── State machine loop thread watchdog ───────────────────────────
            # Restart the SM loop thread if it has exited (e.g. due to an early
            # ImportError before bot/ was on sys.path, or any other uncaught
            # error).  This is idempotent: _ensure_state_machine_loop_started()
            # is a no-op while the thread is alive.  Without this guard a dead
            # or never-started SM loop thread would permanently block activation
            # because no other periodic mechanism recreates it mid-run.
            _ensure_state_machine_loop_started()

            # ── State machine health step ─────────────────────────────────────
            # Ensure OFF → LIVE_ACTIVE is never silently missed during the
            # supervisor loop lifetime.  If the state machine somehow falls back
            # to OFF (e.g. a concurrent reset between bootstrap and here), firing
            # maybe_auto_activate() here recovers it on the next supervision
            # cycle without waiting for an external trigger.  All errors are
            # swallowed so a failed step never stalls the supervisor loop.
            if _supervisor_state_machine is not None and _supervisor_off_state is not None:
                try:
                    if _supervisor_state_machine.get_current_state() == _supervisor_off_state:
                        # Activation is owned by the core trading loop — do NOT
                        # call maybe_auto_activate() from the supervisor.  Log
                        # the OFF state so operators can diagnose stalls, but
                        # let the core loop drive the transition.
                        logger.info(
                            "[Supervisor] State machine is OFF — waiting for core loop to activate"
                        )
                except Exception as _sl_step_err:
                    logger.debug("_rerun_supervisor_loop: state machine step failed (%s)", _sl_step_err)

            # ── Adopt threads started by the connection monitor ───────────────
            # The connection monitor in IndependentBrokerTrader can start new
            # platform threads after a broker that was offline at boot comes
            # back online.  Those threads live in independent_trader.broker_threads
            # but are not initially tracked here.  Adopt them so the supervisor
            # can restart them if they die.
            if use_independent_trading and strategy.independent_trader:
                _ibt = strategy.independent_trader
                for _cm_bname, _cm_t in list(_ibt.broker_threads.items()):
                    if _cm_bname not in _active_threads and _cm_t.is_alive():
                        _cm_bt = _ibt.broker_thread_types.get(_cm_bname)
                        _cm_broker = None
                        if _cm_bt is not None:
                            try:
                                _cm_broker = _ibt._get_platform_broker_source().get(_cm_bt)
                            except Exception:
                                pass
                        _active_threads[_cm_bname] = {
                            "thread": _cm_t,
                            "stop_flag": _ibt.stop_flags.get(_cm_bname, threading.Event()),
                            "broker_type": _cm_bt,
                            "broker": _cm_broker,
                            "mode": "platform",
                        }
                        logger.info(
                            "📌 [Orchestrator] Adopted connection-monitor thread '%s' into supervisor",
                            _cm_bname.upper(),
                        )

            for _bname, _entry in list(_active_threads.items()):
                _t = _entry["thread"]
                _sf = _entry["stop_flag"]
                if not _t.is_alive() and not _sf.is_set():
                    logger.warning(
                        "💥 [Orchestrator] Trader thread '%s' DIED — restarting…",
                        _bname.upper(),
                    )
                    if _entry["mode"] == "platform":
                        _new_t, _new_sf = _start_trader_thread(
                            strategy.independent_trader,
                            _entry["broker_type"],
                            _entry["broker"],
                        )
                    elif _entry["mode"] == "user":
                        _new_sf = threading.Event()
                        _new_t = threading.Thread(
                            target=strategy.independent_trader.run_user_broker_trading_loop,
                            args=(
                                _entry["user_id"],
                                _entry["broker_type"],
                                _entry["broker"],
                                _new_sf,
                            ),
                            name=f"Trader-{_bname}",
                            daemon=True,
                        )
                        _new_t.start()
                    else:
                        _hf_secs = (
                            _hf_bot.get_cycle_interval()
                            if _hf_bot is not None
                            else 150
                        )
                        _new_t, _new_sf = _start_single_broker_thread(strategy, _hf_secs)
                    _entry["thread"] = _new_t
                    _entry["stop_flag"] = _new_sf
                    logger.info(
                        "   ✅ [Orchestrator] Restarted trader for '%s'",
                        _bname.upper(),
                    )

            if _orch_cycle % 18 == 0:
                _alive = sum(
                    1 for _e in _active_threads.values() if _e["thread"].is_alive()
                )
                logger.info(
                    "💓 [Orchestrator] %d/%d threads alive (supervisor cycle %d)",
                    _alive,
                    len(_active_threads),
                    _orch_cycle,
                )
                if use_independent_trading and strategy.independent_trader:
                    strategy.log_multi_broker_status()

            # STRATEGY HEARTBEAT — emitted every supervisor cycle to prove the
            # trading loop is alive and actively running.
            _symbols_count = 0
            try:
                _symbols_count = len(getattr(strategy, "symbols", None) or [])
            except Exception:
                pass
            _runtime_s = _orch_cycle * 10.0
            logger.info(
                "STRATEGY HEARTBEAT | cycle=%d symbols=%d runtime=%.1fs",
                _orch_cycle,
                _symbols_count,
                _runtime_s,
            )

            time.sleep(10)

        except KeyboardInterrupt:
            for _entry in _active_threads.values():
                _entry["stop_flag"].set()
            for _entry in _active_threads.values():
                _entry["thread"].join(timeout=5)
            raise
        except Exception as _orch_err:
            logger.error(
                "❌ [Orchestrator] Supervisor loop error: %s — continuing",
                _orch_err,
                exc_info=True,
            )
            time.sleep(10)


def _run_bot_startup_and_trading_with_retry():
    """
    Bootstrap kernel entry point — retries on transient failures.

    Enforces the single-owner invariant: only one instance of this function
    may be executing at any time.  A concurrent call (e.g. a stale code path
    spawning a second BotStartup thread) is rejected immediately so it can
    never race through shared initialisation state.

    Claims FSM bootstrap ownership so that any other thread attempting to
    drive the FSM forward will produce an observable warning log.

    Retries indefinitely with exponential backoff (capped at 60 s) so that
    transient errors (Kraken nonce, network blip, etc.) never kill the thread
    permanently.  Only a clean KeyboardInterrupt stops the loop.
    """
    # ── ENTRY POINT TRACE ────────────────────────────────────────────────────
    _log_startup_trace("_run_bot_startup_and_trading_with_retry() entry")
    logger.info(
        "DIAG_BOOTSTRAP_BEGIN: entering _run_bot_startup_and_trading_with_retry "
        "pid=%d thread=%s thread_id=%d",
        os.getpid(),
        threading.current_thread().name,
        threading.get_ident(),
    )

    # ── Single-owner bootstrap kernel ────────────────────────────────────────
    if not _BOOTSTRAP_SINGLE_OWNER_LOCK.acquire(blocking=False):
        logger.error(
            "[Bootstrap] Concurrent bootstrap execution detected — "
            "another bootstrap kernel sequence is already running on this process. "
            "This indicates a bug: BotStartup should never be spawned twice. "
            "Rejecting this call."
        )
        return
    try:
        _set_bootstrap_owner_thread()
        # Claim FSM ownership: from this point forward, only this thread should
        # drive the bootstrap FSM forward.  Non-owner transitions will be
        # logged as warnings so races are immediately visible.
        if _BOOTSTRAP_FSM_AVAILABLE:
            _get_bootstrap_fsm().claim_bootstrap_ownership()

        import time

        _INITIAL_DELAY_SECONDS = 5
        _BACKOFF_MULTIPLIER = 2
        _MAX_BACKOFF_EXPONENT = 6   # caps delay at 5 * 2^6 = 320 → clamped to _MAX_DELAY
        _MAX_DELAY = 60             # seconds — keeps retries responsive
        _MAX_CONNECTION_ATTEMPTS = 3  # FIX 4: anti-loop kill switch
        _truthy = {"1", "true", "yes", "on", "enabled"}
        _fatal_nonce_restart_enabled = (
            os.environ.get("NIJA_FATAL_NONCE_EXTERNAL_RESTART", "0").strip().lower() in _truthy
        )
        try:
            _fatal_nonce_restart_threshold = max(
                1,
                int(os.environ.get("NIJA_FATAL_NONCE_RESTART_THRESHOLD", "3")),
            )
        except (TypeError, ValueError):
            _fatal_nonce_restart_threshold = 3

        attempt = 0
        connection_attempts = 0
        _fatal_nonce_error_streak = 0

        logger.info("Bootstrap start")
        while True:
            _next_attempt = attempt + 1
            logger.info(
                "🔁 [Startup] Bootstrap attempt #%d (%s, %s)",
                _next_attempt,
                _format_startup_attempt_reason(_next_attempt),
                _format_startup_phase_tag(),
            )
            try:
                _state_snap = _read_initialized_state_snapshot(context="fresh-attempt event reset")
                _init_done = (
                    _state_snap.get("strategy") is not None
                    and "active_threads" in _state_snap
                )
                if not _init_done:
                    _reset_startup_events_for_fresh_attempt(clear_initialized_state=True)

                # Attempt to start the bot
                logger.info(
                    "DIAG_STARTUP_DISPATCH: dispatching startup attempt=%d init_done=%s",
                    _next_attempt,
                    _init_done,
                )
                logger.info(
                    "DIAG_RETRY_WRAPPER_BEFORE: about to call _run_bot_startup_and_trading() "
                    "attempt=%d init_done=%s",
                    _next_attempt,
                    _init_done,
                )
                _run_bot_startup_and_trading()
                # Normal exit — supervisor loop inside returned cleanly
                _set_startup_last_error("")
                logger.info(
                    "DIAG_RETRY_WRAPPER: _run_bot_startup_and_trading() returned normally "
                    "attempt=%d",
                    _next_attempt,
                )
                logger.info("✅ Bootstrap success - setting event")
                return

            except KeyboardInterrupt:
                # Clean shutdown — do not retry
                logger.info("Received KeyboardInterrupt — stopping startup thread")
                raise

            except Exception as e:
                logger.error(
                    "DIAG_RETRY_WRAPPER: _run_bot_startup_and_trading() raised %s: %s "
                    "attempt=%d",
                    type(e).__name__,
                    e,
                    _next_attempt,
                    exc_info=True,
                )
                if _is_fatal_nonce_restart_error(e):
                    _fatal_nonce_error_streak += 1
                    logger.critical(
                        "🚨 Fatal nonce authorization/desync error detected: %s "
                        "(streak=%d/%d, external_restart=%s)",
                        e,
                        _fatal_nonce_error_streak,
                        _fatal_nonce_restart_threshold,
                        _fatal_nonce_restart_enabled,
                        exc_info=True,
                    )
                    if (
                        _fatal_nonce_restart_enabled
                        and _fatal_nonce_error_streak >= _fatal_nonce_restart_threshold
                    ):
                        logger.critical(
                            "🚨 Requesting clean process exit so external watchdog can restart service"
                        )
                        # Bootstrap FSM: fatal nonce → EXTERNAL_RESTART_REQUIRED (I9)
                        _bfsm_transition(
                            _BootstrapState.EXTERNAL_RESTART_REQUIRED,
                            f"fatal nonce error: {e}",
                        )
                        _request_external_watchdog_restart(str(e))
                        raise

                    logger.warning(
                        "↩️ Fatal nonce error treated as retryable to avoid crash loops. "
                        "Set NIJA_FATAL_NONCE_EXTERNAL_RESTART=1 to restore fail-fast restart behavior."
                    )
                else:
                    _fatal_nonce_error_streak = 0

                attempt += 1
                connection_attempts += 1  # FIX 4: track connection attempts

                # FIX 4: anti-loop kill switch — abort if connection keeps looping
                if connection_attempts > _MAX_CONNECTION_ATTEMPTS:
                    _set_startup_last_error(
                        f"connection_loop_detected_after_{connection_attempts}_attempts"
                    )
                    logger.error(
                        "🚨 CONNECTION LOOP DETECTED after %d attempts — keeping bootstrap thread alive "
                        "and continuing retries with capped backoff",
                        connection_attempts,
                    )
                    # Keep the kernel alive; do not exit the startup thread.
                    # This preserves supervisor continuity and allows transient
                    # broker/API conditions to recover without process death.
                    connection_attempts = _MAX_CONNECTION_ATTEMPTS

                # Bootstrap FSM: transient failure → BOOT_FAILED_RETRY so the next
                # attempt can enter PLATFORM_CONNECTING cleanly.  Skip reset when
                # full init already completed (fast-path supervisor restart scenario).
                if _BOOTSTRAP_FSM_AVAILABLE:
                    _state_snap = _read_initialized_state_snapshot(context="retry reset guard")
                    _init_done = (
                        _state_snap.get("strategy") is not None
                        and "active_threads" in _state_snap
                    )
                    if not _init_done:
                        _get_bootstrap_fsm().reset_for_retry(
                            f"attempt #{attempt} failed: {e}"
                        )

                delay = min(
                    _MAX_DELAY,
                    _INITIAL_DELAY_SECONDS * (_BACKOFF_MULTIPLIER ** min(attempt - 1, _MAX_BACKOFF_EXPONENT)),
                )
                logger.error(
                    "💥 [Startup] Attempt #%d failed: %s — retrying in %ds",
                    attempt, e, delay, exc_info=True,
                )
                _set_startup_last_error(
                    f"attempt_{attempt}_failed: {type(e).__name__}: {e}"
                )
                time.sleep(delay)

    finally:
        _clear_bootstrap_owner_thread()
        _BOOTSTRAP_SINGLE_OWNER_LOCK.release()
        if _bootstrap_complete_flag.is_set():
            _bootstrap_completed_event.set()
            logger.info("✅ Bootstrap completion event preserved after successful handoff")
        else:
            logger.warning("Bootstrap completion event left unset - startup did not reach supervisor handoff")


def _force_trade_readiness_handoff(
    *,
    context: str,
    transition_reason: str,
    completion_log: str,
    set_bootstrap_events: bool = True,
) -> None:
    """Log FORCE_TRADE bypass without mutating readiness or lifecycle state."""
    if _force_trade_handoff_complete_event.is_set():
        logger.debug("FORCE_TRADE handoff already complete — skipping duplicate readiness handoff")
        return
    logger.warning(
        "FORCE_TRADE active — readiness barrier remains enforced (context=%s)",
        context,
    )
    _force_trade_handoff_complete_event.set()
    return


def _try_finalize_running_supervised_handoff(
    *,
    reason: str,
    completion_log: str,
    set_bootstrap_events: bool,
) -> bool:
    """Finalize BootstrapFSM handoff legally; never force illegal transitions."""
    if not (_BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None):
        return False

    try:
        _bfsm = _get_bootstrap_fsm()
        _state = getattr(_bfsm, "state", None)

        if _state == _BootstrapState.RUNNING_SUPERVISED:
            logger.info(completion_log)
            try:
                try:
                    from bot.startup_coordinator import get_startup_coordinator as _get_startup_coordinator_handoff
                except ImportError:
                    from startup_coordinator import get_startup_coordinator as _get_startup_coordinator_handoff  # type: ignore[import]
                _get_startup_coordinator_handoff().record_bootstrap_state("RUNNING_SUPERVISED")
            except Exception as _coord_err:
                logger.debug("Startup coordinator RUNNING_SUPERVISED update skipped: %s", _coord_err)
            if set_bootstrap_events:
                _bootstrap_complete_flag.set()
                _bootstrap_completed_event.set()
            _force_trade_handoff_complete_event.set()
            return True

        # Walk only legal forward transitions from the current state to
        # THREADS_STARTING. This avoids backward/illegal hops (for example
        # HEALTH_BOUND -> LOCK_ACQUIRED) during FORCE_TRADE handoff.
        _state = getattr(_bfsm, "state", None)
        if hasattr(_bfsm, "transition"):
            _force_trade_happy_path = [
                _BootstrapState.BOOT_INIT,
                _BootstrapState.LOCK_ACQUIRED,
                _BootstrapState.HEALTH_BOUND,
                _BootstrapState.ENV_VERIFIED,
                _BootstrapState.MODE_GATED,
                _BootstrapState.PLATFORM_CONNECTING,
                _BootstrapState.PLATFORM_READY,
                _BootstrapState.BALANCE_HYDRATED,
                _BootstrapState.CAPABILITY_VERIFIED,
                _BootstrapState.STARTUP_VALIDATED,
                _BootstrapState.CAPITAL_REFRESHING,
                _BootstrapState.CAPITAL_READY,
                _BootstrapState.INIT_COMPLETE,
                _BootstrapState.THREADS_STARTING,
            ]

            if _state == _BootstrapState.BOOT_FAILED_RETRY:
                try:
                    _bfsm.transition(
                        _BootstrapState.PLATFORM_CONNECTING,
                        f"{reason}: force-trade retry re-entry",
                    )
                except Exception as _retry_reentry_err:
                    logger.debug("BootstrapFSM retry re-entry transition skipped: %s", _retry_reentry_err)
                _state = getattr(_bfsm, "state", None)

            try:
                _start_idx = _force_trade_happy_path.index(_state)
            except ValueError:
                _start_idx = -1

            if _start_idx >= 0:
                for _target in _force_trade_happy_path[_start_idx + 1:]:
                    _state = getattr(_bfsm, "state", None)
                    if _state == _BootstrapState.THREADS_STARTING:
                        break
                    try:
                        _ok = bool(
                            _bfsm.transition(
                                _target,
                                f"{reason}: force-trade pre-handoff",
                            )
                        )
                        if not _ok:
                            break
                    except Exception as _ff_err:
                        logger.debug(
                            "BootstrapFSM fast-forward transition to %s skipped: %s",
                            getattr(_target, "value", str(_target)),
                            _ff_err,
                        )
                        break

            _state = getattr(_bfsm, "state", None)

        if _state == _BootstrapState.THREADS_STARTING and hasattr(_bfsm, "finalize_boot"):
            _ok = bool(_bfsm.finalize_boot(reason))
            if _ok:
                logger.info(completion_log)
                try:
                    try:
                        from bot.startup_coordinator import get_startup_coordinator as _get_startup_coordinator_handoff
                    except ImportError:
                        from startup_coordinator import get_startup_coordinator as _get_startup_coordinator_handoff  # type: ignore[import]
                    _coord = _get_startup_coordinator_handoff()
                    _coord.record_bootstrap_state("RUNNING_SUPERVISED")
                    _coord.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
                except Exception as _coord_err:
                    logger.debug("Startup coordinator finalize_boot update skipped: %s", _coord_err)
                if set_bootstrap_events:
                    _bootstrap_complete_flag.set()
                    _bootstrap_completed_event.set()
                _force_trade_handoff_complete_event.set()

                return True

        logger.info(
            "Deferring RUNNING_SUPERVISED handoff (reason=%s): current_state=%s",
            reason,
            getattr(_state, "value", str(_state)),
        )
        return False
    except Exception as _handoff_err:
        logger.error("BootstrapFSM handoff error (%s): %s", reason, _handoff_err)
        return False


def _run_bot_startup_and_trading():  # type: ignore[reportGeneralTypeIssues]
    """
    Background thread: Initialize bot and run trading loops.
    
    This function runs in a background thread while the main thread
    keeps the health server responsive to Railway.
    
    Contains:
    - Kraken connection
    - User loading  
    - Balance fetching
    - Trading loop initialization

    On a retry after the supervisor loop crashes, the module-level
    ``_initialized_state`` singleton is used to skip re-initialisation and
    jump straight to ``_rerun_supervisor_loop()``.
    """
    global _initialized_state

    # ── ENTRY POINT TRACE ────────────────────────────────────────────────────
    _log_startup_trace("_run_bot_startup_and_trading() entry")

    # ── DIAGNOSTIC: function entry ────────────────────────────────────────────
    import threading as _diag_threading
    _diag_ts = datetime.now(timezone.utc).isoformat()
    _diag_thread = _diag_threading.current_thread()
    _diag_pid = os.getpid()
    _diag_state_keys = list(_initialized_state.keys()) if isinstance(_initialized_state, dict) else repr(_initialized_state)
    _diag_state_has_strategy = isinstance(_initialized_state, dict) and _initialized_state.get("strategy") is not None
    _diag_state_has_threads = isinstance(_initialized_state, dict) and "active_threads" in _initialized_state
    logger.info(
        "DIAG_ENTRY: _run_bot_startup_and_trading() called "
        "ts=%s pid=%d thread_name=%s thread_id=%d "
        "_initialized_state_keys=%s has_strategy=%s has_active_threads=%s",
        _diag_ts,
        _diag_pid,
        _diag_thread.name,
        _diag_thread.ident or -1,
        _diag_state_keys,
        _diag_state_has_strategy,
        _diag_state_has_threads,
    )

    _live_capital_verified = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower() in ("true", "1", "yes", "enabled")
    if _live_capital_verified:
        logger.warning(
            "LIVE_CAPITAL_VERIFIED startup bypass disabled — continuing through strict bootstrap flow"
        )

    # FORCE_TRADE/FORCE_TRADE_MODE: bypass readiness enforcement only
    if _is_truthy_env("FORCE_TRADE") or _is_truthy_env("FORCE_TRADE_MODE"):
        logger.warning(
            "FORCE_TRADE active — startup readiness barrier remains enforced (startup)",
        )

    elif _is_live_trading_active_now():
        logger.warning(
            "LIVE mode detected before bootstrap completion; startup bypass disabled until "
            "RUNNING_SUPERVISED is reached"
        )

    # ── FAST PATH: init already done — skip straight to supervisor loop ────
    # Requires full state (strategy + active_threads) to be present so that a
    # retry after a partial-init failure falls through and finishes setup instead
    # of calling _rerun_supervisor_loop with an incomplete state dict.
    logger.info(
        "DIAG_FASTPATH_CHECK: reading _initialized_state snapshot "
        "raw_state_keys=%s",
        list(_initialized_state.keys()) if isinstance(_initialized_state, dict) else repr(_initialized_state),
    )
    _state_copy = _read_initialized_state_snapshot(context="fast-path check")
    logger.info(
        "DIAG_FASTPATH_CHECK: snapshot acquired "
        "state_copy_keys=%s has_strategy=%s has_active_threads=%s — "
        "fast-path will be taken=%s",
        list(_state_copy.keys()),
        _state_copy.get("strategy") is not None,
        "active_threads" in _state_copy,
        (_state_copy.get("strategy") is not None and "active_threads" in _state_copy),
    )
    logger.debug("Init lock acquired; continuing to preflight")
    # Force state machine loop alive immediately after INIT lock is released —
    # before any potentially blocking broker I/O.  This guarantees the loop is
    # running in both the fast-path (retry) and the slow-path (first boot) so a
    # stall in broker initialization can never prevent state machine activation.
    # _ensure_state_machine_loop_started() is idempotent; a second call on the
    # fast-path (which also calls it at line ~1536) is a safe no-op.
    _ensure_state_machine_loop_started()
    # ── Authority heartbeat monitor ───────────────────────────────────────────
    # IMPORTANT: Start the authority heartbeat monitor BEFORE the fast-path
    # early return so it runs on both first boot AND restarts/retries.
    # The monitor is a singleton (idempotent start) so calling it here is safe
    # even if it was already started by a previous code path.
    # This verifies Redis connectivity and fencing token validity every 30 s.
    # On success it sets NIJA_WRITER_HEARTBEAT_ACTIVE=1, updates
    # NIJA_WRITER_HEARTBEAT_ALIVE_TS, and writes the heartbeat marker file so
    # the activation gate's HEARTBEAT_VERIFICATION check passes.
    logger.info(
        "DIAG_HEARTBEAT_START: about to call start_authority_heartbeat() "
        "fencing_token_present=%s fallback=%s",
        bool(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()),
        os.environ.get("NIJA_WRITER_FENCING_TOKEN_FALLBACK", ""),
    )
    logger.info(
        "AUTHORITY_HEARTBEAT: pre-startup check — about to call start_authority_heartbeat() "
        "fencing_token_present=%s fallback=%s",
        bool(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()),
        os.environ.get("NIJA_WRITER_FENCING_TOKEN_FALLBACK", ""),
    )
    try:
        from bot.authority_heartbeat import start_authority_heartbeat as _start_ahb
        _ahb_monitor = _start_ahb()
        logger.info(
            "AUTHORITY_HEARTBEAT: monitor started successfully monitor=%r "
            "interval_s=%.1f timeout_s=%.1f max_failures=%d "
            "thread_name=%s thread_alive=%s thread_daemon=%s",
            _ahb_monitor,
            _ahb_monitor._interval_s,
            _ahb_monitor._timeout_s,
            _ahb_monitor._max_failures,
            _ahb_monitor._thread.name if _ahb_monitor._thread else "None",
            _ahb_monitor._thread.is_alive() if _ahb_monitor._thread else False,
            _ahb_monitor._thread.daemon if _ahb_monitor._thread else False,
        )
    except Exception as _ahb_exc:
        logger.error(
            "AUTHORITY_HEARTBEAT: monitor could not be started: %s",
            _ahb_exc,
            exc_info=True,
        )

    if _state_copy.get("strategy") is not None and "active_threads" in _state_copy:
        logger.warning("⚠️ Bypassing init - forcing run loop")
        logger.info(
            "♻️  Startup already completed — skipping re-init, "
            "re-entering supervisor loop"
        )
        # When bootstrap was previously completed and the system is re-entering
        # the supervisor loop after a transient failure, bootstrap is already done.
        # Ensure the completion flag is set so the outer supervisor correctly
        # treats any future thread exit as a hand-off, not a crash.
        _bootstrap_completed_event.set()
        # Guarantee the state machine loop is alive before entering the supervisor
        # so a late-start or missed activation cannot silently skip runtime execution.
        _ensure_state_machine_loop_started()
        _rerun_supervisor_loop(_state_copy)
        logger.info("DIAG_EXIT: fast-path return — _rerun_supervisor_loop completed")
        return

    logger.info(
        "DIAG_SLOWPATH: fast-path NOT taken — proceeding to slow-path (first boot) "
        "state_copy_keys=%s",
        list(_state_copy.keys()),
    )

    lock_acquired = acquire_writer_lock()
    if not lock_acquired:
        logger.critical(
            "STARTUP_OBSERVER_STANDBY: distributed writer authority denied"
        )
        if is_live_trading():
            logger.critical(
                "DIAG_EXIT: raising RuntimeError — lock not acquired and live trading active"
            )
            raise RuntimeError(
                "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: another instance owns writer authority"
            )
        logger.critical(
            "DIAG_EXIT: returning False — lock not acquired (non-live mode)"
        )
        return False

    logger.info(
        "AUTHORITY_HEARTBEAT: slow-path (first boot) — heartbeat monitor already started above "
        "lock_acquired=%s fencing_token_present=%s",
        lock_acquired,
        bool(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()),
    )

    # Coinbase is enabled by default. Set NIJA_DISABLE_COINBASE=true to disable.

    # ── Bootstrap FSM: acknowledge ENV_VERIFIED on first run ─────────────────
    # Environment variables were verified at module import; health server was
    # bound in main().  Advance the FSM to ENV_VERIFIED so the startup thread
    # can drive subsequent transitions.  On retry the FSM is already in
    # If a previous attempt completed the connection/credential-check phase,
    # skip it entirely on retry so we never loop back through broker init.
    _state_copy = _read_initialized_state_snapshot(context="connection phase guard")
    _connection_already_complete = _state_copy.get("connection_complete", False)
    _resolved_kraken_key, _resolved_kraken_secret = _resolve_kraken_startup_credentials()
    _kraken_credentials_valid = bool(_resolved_kraken_key and _resolved_kraken_secret)
    _coinbase_sdk_available = _coinbase_sdk_is_available()
    try:
        # Import here to ensure logging is set up
        from bot.health_check import get_health_manager
        health_manager = get_health_manager()

        # FIX 3: Hard guard — connection/credential phase runs at most once.
        # If a previous attempt already completed this phase, skip it entirely.
        if _connection_already_complete:
            logger.info("♻️  Connection phase already complete — skipping credential checks")
            # Restore the credential flags stored during the first run so that
            # later sections (broker connection diagnostics at ~line 1226) still work.
            _cred_snap = _read_initialized_state_snapshot(context="restore credential flags")
            kraken_platform_configured = _cred_snap.get("kraken_platform_configured", False)
            coinbase_configured = _cred_snap.get("coinbase_configured", False)
            exchanges_configured = _cred_snap.get("exchanges_configured", 0)
            _kraken_credentials_valid = _cred_snap.get("kraken_credentials_valid", False)
            _coinbase_sdk_available = _cred_snap.get("coinbase_sdk_available", _coinbase_sdk_available)
        else:
            logger.info("=" * 70)
            logger.info("🧵 STARTUP THREAD: Beginning bot initialization")
            logger.info("=" * 70)
            logger.info("While this thread initializes, health server remains responsive")
            
            # Get git metadata: prefer Railway runtime vars, then baked vars,
            # then local git as final fallback.
            git_branch = os.getenv("RAILWAY_GIT_BRANCH", "") or os.getenv("GIT_BRANCH", "")
            git_commit = os.getenv("RAILWAY_GIT_COMMIT_SHA", "") or os.getenv("GIT_COMMIT", "")
            if len(git_commit) > 7:
                git_commit = git_commit[:7]

            # Fallback to git commands if env vars not set
            if not git_branch:
                try:
                    git_branch = subprocess.check_output(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=os.path.dirname(__file__),
                        stderr=subprocess.DEVNULL,
                        timeout=5
                    ).decode().strip()
                except Exception:
                    git_branch = "unknown"

            if not git_commit:
                try:
                    git_commit = subprocess.check_output(
                        ["git", "rev-parse", "--short", "HEAD"],
                        cwd=os.path.dirname(__file__),
                        stderr=subprocess.DEVNULL,
                        timeout=5
                    ).decode().strip()
                except Exception:
                    git_commit = "unknown"

            logger.info("=" * 70)
            logger.info("NIJA TRADING BOT - APEX v7.2.0")
            logger.info("NIJA TRADING BOT - APEX v7.2")
            logger.info("🏷 Version: 7.2.0 — Independent Trading Only")
            logger.info("Branch:          %s", git_branch)
            logger.info("Commit:          %s", git_commit)

            # Build timestamp: prefer env var injected by CI/Docker, else record startup time
            build_timestamp = os.getenv("BUILD_TIMESTAMP") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            logger.info("Build timestamp: %s", build_timestamp)

            # Risk mode: derive human-readable label from RISK_PROFILE env var
            _risk_profile = os.getenv("RISK_PROFILE", "AUTO").upper()
            _risk_label_map = {
                "STARTER":  "small-account / STARTER ($50–$99)",
                "SAVER":    "small-account / SAVER ($100–$249)",
                "INVESTOR": "INVESTOR ($250–$999)",
                "INCOME":   "1K mode / INCOME ($1k–$4.9k)",
                "LIVABLE":  "LIVABLE ($5k–$24.9k)",
                "BALLER":   "BALLER ($25k+)",
                "AUTO":     "AUTO (balance-based tier selection)",
            }
            risk_mode_label = _risk_label_map.get(_risk_profile, _risk_profile)
            logger.info("Risk mode:       %s", risk_mode_label)

            # Max positions and allocation % from env vars
            try:
                _max_positions = int(os.getenv("MAX_CONCURRENT_POSITIONS", "5"))
            except ValueError:
                _max_positions = 5
            # MAX_TRADE_PERCENT is a decimal fraction (e.g., 0.10 = 10%)
            _alloc_pct = float(os.getenv("MAX_TRADE_PERCENT", "0.10")) * 100
            logger.info("Max positions:   %d", _max_positions)
            logger.info(f"Allocation %:    {_alloc_pct:.0f}%")

            logger.info("=" * 70)
            logger.info(f"Python version: {sys.version.split()[0]}")
            logger.info(f"Log file: {LOG_FILE}")
            logger.info(f"Working directory: {os.getcwd()}")
            if _startup_buffer:
                _startup_buffer.flush_phase("INIT")

            # ═══════════════════════════════════════════════════════════════════════
            # CRITICAL: Startup Validation (addresses subtle risks)
            # ═══════════════════════════════════════════════════════════════════════
            # Validates:
            # 1. Git metadata (branch/commit must be known)
            # 2. Exchange configuration (warns about disabled exchanges)
            # 3. Trading mode (testing vs. live must be explicit)
            _validation_critical_failure = False
            _validation_failure_reason = ""
            try:
                from bot.startup_validation import run_all_validations, display_validation_results
                validation_result = run_all_validations(git_branch, git_commit)
                display_validation_results(validation_result)
                # ✅ FIXED GATING LOGIC: Allow any "PASSED*" status (including "PASSED WITH RISKS")
                # Only block on critical_failure = True, not on risks/warnings
                # This allows soft warnings while preventing hard blocks
                if validation_result.critical_failure:
                    _validation_critical_failure = True
                    _validation_failure_reason = validation_result.failure_reason
            except Exception as e:
                logger.error(f"⚠️  Startup validation failed to run: {e}", exc_info=True)
                logger.warning("   Continuing startup without validation (NOT RECOMMENDED)")

            # Raise OUTSIDE the try/except so the retry wrapper catches it, not this handler
            if _validation_critical_failure:
                logger.error("=" * 70)
                logger.error("❌ STARTUP VALIDATION FAILED - will retry")
                logger.error("=" * 70)
                health_manager.mark_configuration_error(_validation_failure_reason)
                _log_exit_point("Startup validation failed", exit_code=1)
                raise RuntimeError(f"Critical startup validation failure (will retry): {_validation_failure_reason}")

            # Validation passed — advance bootstrap FSM.
            # Retry path must move BOOT_FAILED_RETRY -> PLATFORM_CONNECTING.
            if _BOOTSTRAP_FSM_AVAILABLE:
                _bfsm_state_now = _get_bootstrap_fsm().state
                if _bfsm_state_now == _BootstrapState.BOOT_FAILED_RETRY:
                    _bfsm_transition(
                        _BootstrapState.PLATFORM_CONNECTING,
                        "startup_validation passed during retry; re-enter platform connecting",
                    )
                elif _bfsm_state_now == _BootstrapState.ENV_VERIFIED:
                    logger.debug(
                        "[BootstrapFSM] startup validation complete; deferring CAPABILITY_VERIFIED/"
                        "STARTUP_VALIDATED until post-hydration (state=%s)",
                        getattr(_bfsm_state_now, "value", str(_bfsm_state_now)),
                    )
                elif _bfsm_state_now in {
                    _BootstrapState.BOOT_INIT,
                    _BootstrapState.LOCK_ACQUIRED,
                    _BootstrapState.HEALTH_BOUND,
                }:
                    # Must pass through ENV_VERIFIED before broker startup.
                    _bfsm_transition(
                        _BootstrapState.ENV_VERIFIED,
                        "startup_validation: env verified (intermediate step)",
                    )
                else:
                    logger.info(
                        "[BootstrapFSM] startup_validation transition skipped (already advanced, state=%s)",
                        getattr(_bfsm_state_now, "value", str(_bfsm_state_now)),
                    )

            # Display financial disclaimers (App Store compliance)
            try:
                from bot.financial_disclaimers import display_startup_disclaimers, log_compliance_notice
                display_startup_disclaimers()
                log_compliance_notice()
            except ImportError:
                # Fallback if disclaimers module not available
                logger.warning("=" * 70)
                logger.warning("⚠️  RISK WARNING: Trading involves substantial risk of loss")
                logger.warning("   Only trade with money you can afford to lose")
                logger.warning("=" * 70)
            
            # Display feature flag banner
            try:
                from bot.startup_diagnostics import display_feature_flag_banner
                display_feature_flag_banner()
            except Exception as e:
                logger.warning(f"⚠️  Could not display feature flag banner: {e}")
            
            # Verify trading capability
            try:
                from bot.startup_diagnostics import verify_trading_capability
                capability_ok, issues = verify_trading_capability()
                if not capability_ok:
                    logger.warning("⚠️  Trading capability verification found issues")
                    logger.warning("   Bot may not function correctly")
                else:
                    logger.info(
                        "✅ Trading capability checks passed — continuing bootstrap "
                        "(startup readiness gate still applies)"
                    )

                    _ft_state_snapshot = _read_initialized_state_snapshot(context="post-capability-verification")
                    (
                        _ft_system_ready,
                        _ft_broker_ready,
                        _ft_risk_ready,
                        _ft_strategy_ready,
                        _ft_capital_ready,
                        _ft_execution_ready,
                    ) = _compute_system_ready(_ft_state_snapshot)

                    _readiness_banner = (
                        "🚀 SYSTEM READY STATE:\n"
                        if _ft_system_ready
                        else "🧭 STARTUP PRE-INIT READINESS SNAPSHOT:\n"
                    )
                    _readiness_log = logger.critical if _ft_system_ready else logger.info
                    _readiness_log(
                        _readiness_banner
                        + "  broker_ready=%s\n"
                        + "  risk_ready=%s\n"
                        + "  strategy_ready=%s\n"
                        + "  capital_ready=%s\n"
                        + "  execution_ready=%s",
                        _ft_broker_ready,
                        _ft_risk_ready,
                        _ft_strategy_ready,
                        _ft_capital_ready,
                        _ft_execution_ready,
                    )

                    # Activation must occur in the bootstrap owner thread.
                    try:
                        from bot.trading_state_machine import get_state_machine as _get_tsm_startup

                        if bool(_rt_snapshot().get("strategy_ready", False)):
                            _tsm_startup = _get_tsm_startup()
                            _startup_state = _tsm_startup.get_current_state()
                            logger.info(
                                "Startup-thread activation bypass disabled: state=%s; waiting for "
                                "BootstrapFSM READY -> RUNNING handoff",
                                getattr(_startup_state, "value", str(_startup_state)),
                            )
                        else:
                            logger.info(
                                "Startup-thread activation bypass disabled: strategy not fully ready yet"
                            )
                    except Exception as _startup_activation_err:
                        logger.warning("Startup-thread activation status probe failed: %s", _startup_activation_err)

                    # Do NOT release bootstrap events here — the startup thread must not
                    # signal completion before the full system_ready barrier is satisfied
                    # (strategy_ready + broker_ready + risk_ready + capital_ready +
                    # execution_ready).  Bootstrap events are set by the normal boot path
                    # once the FSM reaches RUNNING_SUPERVISED (see finalize_boot / B1→B2).
                    logger.info(
                        "Startup-thread capability verification complete — "
                        "deferring bootstrap event release to RUNNING_SUPERVISED gate"
                    )

                    if _is_truthy_env("FORCE_TRADE") or _is_truthy_env("FORCE_TRADE_MODE"):
                        logger.warning(
                            "FORCE_TRADE active — capability checks bypassed where applicable; "
                            "startup readiness barrier remains enforced (post-capability)"
                        )
            except Exception as e:
                logger.warning(f"⚠️  Could not verify trading capability: {e}")

            # ── B: Phase 0 → 1 (ENV_VALIDATION complete; broker registry may begin) ─
            _advance_phase(_Phase.BROKER_REGISTRY, reason="startup validation and feature-flag checks passed")
            if _startup_buffer:
                _startup_buffer.flush_phase("ENV_VALIDATION")

            # ═══════════════════════════════════════════════════════════════════════
            # CREDENTIAL VALIDATION — run before any broker connection attempt
            # ═══════════════════════════════════════════════════════════════════════
            # Validates that all configured broker credentials are present, non-empty,
            # and structurally correct.  Logs actionable errors for any issues found
            # so operators can fix them before the bot wastes time on failed connections.
            # ═══════════════════════════════════════════════════════════════════════
            logger.info("=" * 70)
            logger.info("🔐 CREDENTIAL VALIDATION")
            logger.info("=" * 70)
            
            # Check if credentials validator exists
            import importlib.util as _iutil
            _cv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate_broker_credentials.py")
            _live_capital_verified = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower() in ('true', '1', 'yes')
            
            if not os.path.isfile(_cv_path):
                if _live_capital_verified:
                    # HARD FAIL: Do not allow live capital mode without credential validation
                    logger.critical(
                        "❌ FATAL: credential validation unavailable in live-capital mode "
                        "(validate_broker_credentials.py missing)"
                    )
                    logger.error(
                        "LIVE_CAPITAL_VERIFIED=true but validate_broker_credentials.py is missing"
                    )
                    logger.error(
                        "Critical safety violation: silent credential skipping in live mode can create false-ready states"
                    )
                    logger.error("Action required:")
                    logger.error("  1. Restore validate_broker_credentials.py to bot/ directory")
                    logger.error("  2. OR set LIVE_CAPITAL_VERIFIED=false to disable live trading")
                    logger.error("  3. Re-run bot startup")
                    sys.exit(1)
                else:
                    logger.info("ℹ️  validate_broker_credentials.py not found — skipping external validation")
            
            try:
                if os.path.isfile(_cv_path):
                    _cv_spec = _iutil.spec_from_file_location(
                        "validate_broker_credentials",
                        _cv_path,
                    )
                    if _cv_spec and _cv_spec.loader:
                        _cv_mod = _iutil.module_from_spec(_cv_spec)
                        _cv_spec.loader.exec_module(_cv_mod)

                        _cv_results = [v() for v in [
                            _cv_mod._validate_kraken_platform,
                            _cv_mod._validate_coinbase,
                            _cv_mod._validate_alpaca,
                            _cv_mod._validate_binance,
                            _cv_mod._validate_okx,
                        ]]

                        _cv_configured = sum(1 for r in _cv_results if r["configured"])
                        _cv_errors     = sum(1 for r in _cv_results if r["configured"] and not r["valid"])
                        _cv_by_broker = {r.get("broker", "").lower(): r for r in _cv_results}
                        _kraken_credentials_valid = _kraken_credentials_valid and bool(
                            (_cv_by_broker.get("kraken (platform)") or {}).get("valid", False)
                        )

                        for _r in _cv_results:
                            if not _r["configured"]:
                                logger.info("   ⚪ %-22s not configured (skipped)", _r["broker"])
                                continue
                            if _r["valid"]:
                                logger.info("   ✅ %-22s credentials look valid", _r["broker"])
                            else:
                                logger.error("   ❌ %-22s CREDENTIAL ERRORS:", _r["broker"])
                                for _issue in _r["issues"]:
                                    logger.error("      → %s", _issue)
                            for _warn in _r.get("warnings", []):
                                logger.warning("      ⚠️  %s", _warn)

                        if _cv_configured == 0:
                            logger.error("=" * 70)
                            logger.error("❌ CREDENTIAL VALIDATION: No broker credentials configured")
                            logger.error("   The bot cannot trade without at least one broker.")
                            logger.error("   See CREDENTIAL_SETUP.md for step-by-step instructions.")
                            logger.error("=" * 70)
                        elif _cv_errors > 0:
                            logger.warning("=" * 70)
                            logger.warning(
                                "⚠️  CREDENTIAL VALIDATION: %d broker(s) have credential errors",
                                _cv_errors,
                            )
                            logger.warning("   These brokers will likely fail to connect.")
                            logger.warning("   Common fixes:")
                            logger.warning("     • Kraken 'EAPI:Invalid nonce'  → run reset_kraken_nonce.py")
                            logger.warning("     • Coinbase 401 Unauthorized    → check PEM newlines in secret")
                            logger.warning("     • Missing credentials          → see CREDENTIAL_SETUP.md")
                            logger.warning("=" * 70)
                        else:
                            logger.info("✅ CREDENTIAL VALIDATION: All configured brokers passed")
            except Exception as _cv_err:
                logger.warning("⚠️  Credential validation error (non-fatal): %s", _cv_err)

            if _startup_buffer:
                _startup_buffer.flush_phase("CREDENTIALS")

            _startup_blockers = []
            _resolved_kraken_key, _resolved_kraken_secret = _resolve_kraken_startup_credentials()
            if not _resolved_kraken_key or not _resolved_kraken_secret:
                _startup_blockers.append(
                    "Missing Kraken credentials (all sources exhausted): "
                    "set one valid key/secret pair from "
                    "KRAKEN_PLATFORM_API_KEY/KRAKEN_PLATFORM_API_SECRET, "
                    "KRAKEN_USER_TANIA_GILBERT_API_KEY/KRAKEN_USER_TANIA_GILBERT_API_SECRET, "
                    "or KRAKEN_API_KEY/KRAKEN_API_SECRET."
                )

            import importlib.util as _iutil
            _kraken_sdk_missing = (
                _iutil.find_spec("krakenex") is None or _iutil.find_spec("pykrakenapi") is None
            )
            if _kraken_credentials_valid and _kraken_sdk_missing:
                _startup_blockers.append(
                    "Missing modules: Kraken SDK not installed (requires krakenex + pykrakenapi)."
                )

            _coinbase_disabled = _is_truthy_env("NIJA_DISABLE_COINBASE", "false")
            _coinbase_enabled_for_trading = os.environ.get(
                "ENABLE_COINBASE_TRADING", "true"
            ).strip().lower() not in ("0", "false", "no", "off")
            _primary_execution_venue = os.environ.get(
                "PRIMARY_EXECUTION_VENUE", ""
            ).strip().lower()
            _coinbase_required = (
                not _coinbase_disabled
                and _coinbase_enabled_for_trading
                and _primary_execution_venue == "coinbase"
            )
            if _coinbase_required and not _coinbase_sdk_available:
                _startup_blockers.append(
                    "Missing modules: Coinbase SDK not installed while Coinbase is enabled "
                    "(install coinbase-advanced-py or set NIJA_DISABLE_COINBASE=true)."
                )

            if _startup_blockers:
                raise RuntimeError("Hard startup blockers detected: " + " | ".join(_startup_blockers))

            # Sentinel A is observer-only: no lifecycle transitions, no lock
            # ownership, no nonce manager initialization. Bootstrap-owned nonce
            # reset runs later in the post-INIT handoff stage.
            logger.debug(
                "Sentinel A observer: preflight complete; lifecycle ownership remains with BootstrapFSM"
            )

            logger.debug("Preflight anchor reached: entered post-nonce execution path")
            try:
                logger.debug("Preflight: entering next stage after nonce")

                # Portfolio override visibility at startup
                portfolio_id = resolve_coinbase_retail_portfolio_id()
                if portfolio_id:
                    logger.info("🔧 Portfolio override in use: %s", portfolio_id)
                else:
                    logger.info("🔧 Portfolio override in use: <none>")

                # Pre-flight check: Verify at least one exchange is configured
                logger.info("=" * 70)
                logger.info("🔍 PRE-FLIGHT: Checking Exchange Credentials")
                logger.info("=" * 70)

                exchanges_configured = 0
                exchange_status = []

                # Check Coinbase
                coinbase_configured = bool(
                    os.getenv("COINBASE_API_KEY")
                    and (os.getenv("COINBASE_API_SECRET") or os.getenv("COINBASE_PEM_CONTENT"))
                )
                if coinbase_configured:
                    exchanges_configured += 1
                    exchange_status.append("✅ Coinbase")
                else:
                    exchange_status.append("❌ Coinbase")

                # Check Kraken Platform
                # Prefer platform keys; legacy KRAKEN_API_* pair remains supported for backward compatibility.
                kraken_platform_configured = bool(
                    (os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY"))
                    and (os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET"))
                )
                if kraken_platform_configured:
                    exchanges_configured += 1
                    exchange_status.append("✅ Kraken (Platform)")
                else:
                    exchange_status.append("❌ Kraken (Platform)")

                # Check OKX
                if os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET") and os.getenv("OKX_PASSPHRASE"):
                    exchanges_configured += 1
                    exchange_status.append("✅ OKX")
                else:
                    exchange_status.append("❌ OKX")

                # Check Binance
                if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
                    exchanges_configured += 1
                    exchange_status.append("✅ Binance")
                else:
                    exchange_status.append("❌ Binance")

                # Check Alpaca Platform
                if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"):
                    exchanges_configured += 1
                    exchange_status.append("✅ Alpaca (Platform)")
                else:
                    exchange_status.append("❌ Alpaca (Platform)")

                # D: single structured snapshot instead of N per-exchange log lines
                try:
                    from bot.startup_event_buffer import StartupSnapshot as _ExSnap
                    _ex_snap = _ExSnap("Exchange Credentials")
                    _ex_snap.record("coinbase", coinbase_configured)
                    _ex_snap.record("kraken_platform", kraken_platform_configured)
                    _ex_snap.record("okx", bool(os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET")))
                    _ex_snap.record("binance", bool(os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET")))
                    _ex_snap.record("alpaca", bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET")))
                    _ex_snap.emit(logger)
                except ImportError:
                    for status in exchange_status:
                        logger.info(f"   {status}")
                if exchanges_configured == 0:
                    logger.warning("⚠️  No exchange credentials configured")
                logger.info("Total exchanges configured: %d", exchanges_configured)
                logger.info("=" * 70)

                if exchanges_configured == 0:
                    logger.error("=" * 70)
                    logger.error("❌ FATAL: NO EXCHANGE CREDENTIALS CONFIGURED")
                    logger.error("=" * 70)
                    logger.error("")
                    logger.error("At least one exchange must be configured to run the bot.")
                    logger.error("Configure credentials for at least ONE of:")
                    logger.error("  • Coinbase")
                    logger.error("  • Kraken")
                    logger.error("  • OKX")
                    logger.error("  • Binance")
                    logger.error("  • Alpaca")
                    logger.error("")
                    logger.error("How to configure:")
                    logger.error("1. Edit .env file and add your credentials")
                    logger.error("2. Or set environment variables in your deployment platform:")
                    logger.error("")
                    logger.error("Railway: Settings → Variables → Add")
                    logger.error("Render:  Dashboard → Service → 'Manual Deploy' → 'Deploy latest commit'")
                    logger.error("")
                    logger.error("For detailed help, see:")
                    logger.error("  • SOLUTION_ENABLE_EXCHANGES.md")
                    logger.error("  • RESTART_DEPLOYMENT.md")
                    logger.error("  • Run: python3 diagnose_env_vars.py")
                    logger.error("=" * 70)
                    logger.error("Exiting - No trading possible without credentials")
                
                    # Mark as configuration error for health checks
                    health_manager.mark_configuration_error("No exchange credentials configured")

                    # Bootstrap FSM: no credentials → CONFIG_ERROR_KEEPALIVE terminal state
                    _bfsm_transition(
                        _BootstrapState.CONFIG_ERROR_KEEPALIVE,
                        "no exchange credentials configured",
                    )

                    # Health server already started at beginning of main()
                    logger.info("Health server already running - will report configuration error status")
                
                    _log_lifecycle_banner(
                        "⚠️  ENTERING CONFIG ERROR KEEP-ALIVE MODE",
                        [
                            "No exchange credentials configured - cannot trade",
                            "Process will stay alive for health monitoring",
                            "Container will NOT restart automatically",
                            f"Heartbeat interval: {CONFIG_ERROR_HEARTBEAT_INTERVAL}s",
                            "Configure credentials and manually restart deployment",
                            *_get_thread_status()
                        ]
                    )
                
                    try:
                        loop_count = 0
                        while True:
                            time.sleep(CONFIG_ERROR_HEARTBEAT_INTERVAL)
                            health_manager.heartbeat()
                            loop_count += 1
                        
                            # Log status every 10 iterations (10 minutes at 60s interval)
                            if loop_count % 10 == 0:
                                logger.info(f"⏱️  Config error keep-alive: {loop_count * CONFIG_ERROR_HEARTBEAT_INTERVAL}s elapsed")
                    except KeyboardInterrupt:
                        _log_exit_point(
                            "Configuration error keep-alive interrupted",
                            exit_code=0,
                            details=[
                                "KeyboardInterrupt in config error keep-alive loop",
                                "No exchange credentials were configured",
                                *_get_thread_status()
                            ]
                        )
                        sys.exit(0)
                elif exchanges_configured < 2:
                    # Can be suppressed by setting SUPPRESS_SINGLE_EXCHANGE_WARNING=true
                    suppress_warning = os.getenv("SUPPRESS_SINGLE_EXCHANGE_WARNING", "false").lower() in ("true", "1", "yes")
                    if not suppress_warning:
                        logger.warning("=" * 70)
                        logger.warning("⚠️  SINGLE EXCHANGE TRADING")
                        logger.warning("=" * 70)
                        logger.warning(f"Only {exchanges_configured} exchange configured. Consider enabling more for:")
                        logger.warning("  • Better diversification")
                        logger.warning("  • Reduced API rate limiting")
                        logger.warning("  • More resilient trading")
                        logger.warning("")
                        logger.warning("See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
                        logger.warning("To suppress this warning, set SUPPRESS_SINGLE_EXCHANGE_WARNING=true")
                        logger.warning("=" * 70)
                    logger.warning(f"⚠️  Single exchange trading ({exchanges_configured} exchange configured). Consider enabling more exchanges for better diversification and resilience.")
                    logger.info("📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")

                # Save credential flags in bootstrap-owner thread before INIT handoff.
                # Sentinel A remains lock-free observer only.
                _initialized_state["connection_complete"] = True
                _initialized_state["kraken_platform_configured"] = kraken_platform_configured
                _initialized_state["coinbase_configured"] = coinbase_configured
                _initialized_state["exchanges_configured"] = exchanges_configured
                _initialized_state["kraken_credentials_valid"] = _kraken_credentials_valid
                _initialized_state["coinbase_sdk_available"] = _coinbase_sdk_available

            except Exception as _preflight_crash:
                logger.critical("❌ PREFLIGHT CRASH: %s", _preflight_crash, exc_info=True)
                raise

            logger.info("✅ Connection phase complete - moving to init")
            logger.debug("Sentinel A observer: entered init section")
            if _startup_buffer:
                _startup_buffer.flush_phase("PREFLIGHT")
            logger.info("Bootstrap preflight complete - entering final init")

        # ═══════════════════════════════════════════════════════════════════════
        # BOT INITIALIZATION - This is where Kraken connection happens
        # ═══════════════════════════════════════════════════════════════════════
        
        logger.debug("Entered preflight_continue bot init section")

        try:
            logger.info("🧵 STARTUP THREAD: Initializing trading strategy...")
            logger.info("   This is where Kraken connection will be established")
            logger.info("   Main thread health server remains responsive during this")
            logger.info("PORT env: %s", os.getenv("PORT") or "<unset>")

            # ── Bootstrap FSM invariant guards + MODE_GATED + PLATFORM_CONNECTING ─
            if _BOOTSTRAP_FSM_AVAILABLE:
                _boot_fsm = _get_bootstrap_fsm()
                # I1: process lock must be held
                try:
                    _boot_fsm.assert_invariant_i1_single_writer()
                except Exception as _inv_err:
                    logger.warning("⚠️  Bootstrap invariant I1 violation: %s", _inv_err)
                # I2: health server must be bound before blocking I/O
                try:
                    _boot_fsm.assert_invariant_i2_liveness_first()
                except Exception as _inv_err:
                    logger.warning("⚠️  Bootstrap invariant I2 violation: %s", _inv_err)
                # Advance FSM: ENV_VERIFIED → MODE_GATED → PLATFORM_CONNECTING
                # On retry the FSM is already in BOOT_FAILED_RETRY; skip MODE_GATED.
                _cur = _boot_fsm.state
                if _cur == _BootstrapState.ENV_VERIFIED:
                    _bfsm_transition(
                        _BootstrapState.MODE_GATED,
                        "trading state machine mode confirmed",
                    )
                _bfsm_transition(
                    _BootstrapState.PLATFORM_CONNECTING,
                    "TradingStrategy broker connection starting",
                )

            logger.debug("Init stage A2: after Bootstrap FSM, before initialized_state_lock")
            # STEP 2 — initialize strategy ONCE.
            # If a previous attempt created TradingStrategy but crashed before
            # the full state (including active_threads) was stored, reuse the
            # existing instance rather than reconnecting all brokers again.
            # TradingStrategy holds broker connections but does not retain
            # partially-executed trades or corrupt state on init failure, so
            # reusing it is safe — thread setup simply picks up where it left off.
            _state_snap = _read_initialized_state_snapshot(context="existing strategy probe")
            _existing_strategy = _state_snap.get("strategy")
            logger.debug("Init stage A3: after initialized_state_lock, before phase gate")
            if _existing_strategy is not None:
                logger.info("♻️  Reusing existing TradingStrategy instance from previous attempt")
                strategy = _existing_strategy
                # Re-publish strategy/risk/execution readiness that was cleared by
                # _reset_startup_events_for_fresh_attempt() on this retry.  Without
                # this, strategy_ready, risk_ready, and execution_ready remain False
                # after the reset and system_ready never becomes True in the main-thread
                # wait loop — the root cause of the "stuck at readiness gating" bug.
                if not bool(_rt_snapshot().get("strategy_ready", False)):
                    logger.info(
                        "♻️  Re-publishing strategy readiness after retry reset "
                        "(strategy_ready was False after readiness table reset)"
                    )
                    _reuse_lock_acquired = _initialized_state_lock.acquire(
                        timeout=_INIT_LOCK_PUBLISH_TIMEOUT_S
                    )
                    if _reuse_lock_acquired:
                        try:
                            if not _publish_strategy_runtime_readiness(
                                strategy,
                                context="startup-retry-reuse-existing",
                            ):
                                raise RuntimeError(
                                    "startup retry strategy readiness blocked pending execution authority"
                                )
                        finally:
                            _initialized_state_lock.release()
                    else:
                        raise RuntimeError(
                            "Reuse-path readiness re-publish requires INIT lock; "
                            "direct mark_ready fallback disabled"
                        )
            else:
                # ── B: enforce ordering — env must be validated before broker init ──
                # Non-blocking observable check: warn and continue with degraded
                # readiness rather than hard-raising.  The phase may not have
                # propagated yet when a retry reuses the same singleton, or when
                # the advance() fired before this listener was attached.
                if _PHASE_GATE_AVAILABLE:
                    from bot.startup_phase_gate import get_phase_gate as _get_pg, Phase as _PhaseCheck
                    if not _get_pg().is_at_least(_PhaseCheck.BROKER_REGISTRY):
                        logger.warning(
                            "[PhaseGate] BROKER_REGISTRY phase not reached yet — "
                            "continuing with degraded readiness"
                        )
                # ── C: guard against duplicate TradingStrategy creation ─────────────
                if not _check_init_once("trading_strategy"):
                    raise RuntimeError(
                        "init_once_guard: TradingStrategy creation attempted more than once — "
                        "likely a retry-loop bug."
                    )
                logger.debug("Init stage A4: before TradingStrategy()")
                logger.info("🚀 Creating TradingStrategy instance")
                logger.debug("B2 before TradingStrategy()")

                # ── Option C: bootstrap connects brokers BEFORE strategy is created ──
                # Broker connectivity is the bootstrap layer's responsibility.
                # TradingStrategy receives already-connected brokers and performs
                # strategy-level wiring only (no blocking network I/O in __init__).
                _boot_broker_results: dict = {}
                _boot_connected_users: dict = {}
                try:
                    from bot.multi_account_broker_manager import multi_account_broker_manager as _boot_mabm
                    logger.info("🔌 [bootstrap] Connecting platform brokers...")
                    run_bootstrap()  # single initialization entry point (InitRegistry)
                    # Pre-connection startup delay (bootstrap-owned)
                    _boot_raw_delay = os.environ.get("NIJA_STARTUP_DELAY_S", "")
                    _boot_startup_delay = float(_boot_raw_delay) if _boot_raw_delay else 2.0
                    if _boot_startup_delay > 0:
                        logger.info(
                            "⏱️  [bootstrap] Startup delay: %.1fs before broker connections...",
                            _boot_startup_delay,
                        )
                        time.sleep(_boot_startup_delay)
                    logger.info("Preflight: Kraken session init start")
                    _boot_broker_results = _boot_mabm.initialize_platform_brokers()
                    # Inter-account delay before user connections (bootstrap-owned)
                    _boot_raw_user_delay = os.environ.get("NIJA_USER_CONNECT_DELAY_S", "")
                    _boot_user_delay = float(_boot_raw_user_delay) if _boot_raw_user_delay else 0.5
                    if _boot_user_delay > 0:
                        time.sleep(_boot_user_delay)
                    _boot_connected_users = _boot_mabm.connect_users_from_config()

                    # ── NIJA_FORCE_NONCE_RESYNC: one-shot startup nonce resync ──────────
                    # If NIJA_FORCE_NONCE_RESYNC=true, call probe_server_sync() for every
                    # Kraken API key (platform + all users) before trading starts.
                    # This resets stuck nonces to a fresh server-time floor so that
                    # EAPI:Invalid nonce errors are cleared on the next request.
                    # Only runs once at startup; does NOT affect Coinbase or other brokers.
                    if os.environ.get("NIJA_FORCE_NONCE_RESYNC", "").strip().lower() in ("1", "true", "yes", "on"):
                        logger.warning(
                            "NIJA_FORCE_NONCE_RESYNC=true — running one-shot Kraken nonce resync "
                            "for all configured API keys before trading starts"
                        )
                        try:
                            from bot.distributed_nonce_manager import (
                                get_distributed_nonce_manager as _resync_get_dnm,
                                make_api_key_id as _resync_make_key_id,
                            )
                            _resync_dnm = _resync_get_dnm()
                            # Collect all Kraken API keys: platform + all configured users
                            _resync_keys: list = []
                            # Platform key
                            _platform_raw_key = (
                                os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
                                or os.environ.get("KRAKEN_API_KEY", "").strip()
                            )
                            if _platform_raw_key:
                                _resync_keys.append(("platform", _platform_raw_key))
                            # User keys: scan known user_ids from connected users config
                            _resync_user_ids = []
                            try:
                                from config.user_loader import get_user_config_loader as _resync_ucl
                                for _u in _resync_ucl().get_all_enabled_users():
                                    if _u.broker_type.upper() == "KRAKEN":
                                        _resync_user_ids.append(_u.user_id)
                            except Exception as _resync_ucl_err:
                                logger.debug("NONCE_RESYNC: user config load error: %s", _resync_ucl_err)
                            for _resync_uid in _resync_user_ids:
                                _short, _full = _resync_uid.upper().split("_")[0], _resync_uid.upper().replace("-", "_")
                                for _env_suffix in (_short, _full):
                                    _ukey = os.environ.get(f"KRAKEN_USER_{_env_suffix}_API_KEY", "").strip()
                                    if _ukey:
                                        _resync_keys.append((_resync_uid, _ukey))
                                        break
                            # Call probe_server_sync for each unique key
                            _resync_seen: set = set()
                            for _resync_label, _resync_raw in _resync_keys:
                                _resync_kid = _resync_make_key_id(_resync_raw)
                                if _resync_kid in _resync_seen:
                                    continue
                                _resync_seen.add(_resync_kid)
                                try:
                                    _resync_dnm.probe_server_sync(_resync_kid)
                                    logger.warning(
                                        "NONCE_RESYNC: probe_server_sync complete for %s key_id=%s",
                                        _resync_label, _resync_kid,
                                    )
                                except Exception as _resync_key_err:
                                    logger.warning(
                                        "NONCE_RESYNC: probe_server_sync failed for %s key_id=%s: %s",
                                        _resync_label, _resync_kid, _resync_key_err,
                                    )
                            logger.warning(
                                "NONCE_RESYNC: complete — resynced %d key(s). "
                                "Remove NIJA_FORCE_NONCE_RESYNC after nonces are stable.",
                                len(_resync_seen),
                            )
                        except Exception as _resync_err:
                            logger.error("NONCE_RESYNC: unexpected error during force resync: %s", _resync_err)
                    # ── END NIJA_FORCE_NONCE_RESYNC ────────────────────────────────────

                    try:
                        try:
                            from bot.capital_flow_state_machine import (
                                CapitalBootstrapState as _CapitalBootstrapState,
                                get_capital_bootstrap_fsm as _get_capital_bootstrap_fsm,
                            )
                        except ImportError:
                            from capital_flow_state_machine import (  # type: ignore[import]
                                CapitalBootstrapState as _CapitalBootstrapState,
                                get_capital_bootstrap_fsm as _get_capital_bootstrap_fsm,
                            )
                        _get_capital_bootstrap_fsm().transition(
                            _CapitalBootstrapState.INIT_COMPLETE,
                            "bootstrap_broker_init_complete",
                        )
                    except Exception as _cap_init_complete_err:
                        logger.warning(
                            "[Bootstrap] Capital INIT_COMPLETE transition failed: %s",
                            _cap_init_complete_err,
                        )

                    logger.info(
                        "[Bootstrap] post-INIT_COMPLETE activation bypass disabled — "
                        "continuing strict startup sequence"
                    )

                    logger.debug("Preflight: Kraken session init end")
                    logger.info(
                        "✅ [bootstrap] Broker connections complete — handing off to TradingStrategy"
                    )
                except Exception as _boot_conn_err:
                    logger.error(
                        "❌ [bootstrap] Broker connection phase raised: %s — "
                        "TradingStrategy will attempt legacy connection path",
                        _boot_conn_err,
                    )
                    _boot_broker_results = {}
                    _boot_connected_users = {}

                logger.info("Strategy initialization begin")
                _ts_init_start = time.time()
                try:
                    logger.debug(
                        "Constructor stage=pre_constructor broker_bootstrap_done=%s",
                        bool(_boot_broker_results),
                    )
                    logger.debug("Strategy constructor enter")
                    logger.debug("Preflight: FSM build start")
                    strategy = TradingStrategy(
                        broker_results=_boot_broker_results if _boot_broker_results else None,
                        connected_user_brokers=_boot_connected_users if _boot_connected_users else None,
                    )
                    logger.debug("Preflight: FSM build end")
                    logger.debug("Strategy constructor exit")
                    _ts_init_elapsed = time.time() - _ts_init_start
                    logger.info("Constructor stage=post_constructor elapsed=%.2fs", _ts_init_elapsed)
                    if _ts_init_elapsed > 5:
                        logger.warning(
                            "Trading strategy init exceeded 5s threshold; forcing continue "
                            "(elapsed=%.2fs > 5s threshold)", _ts_init_elapsed
                        )
                    else:
                        logger.debug("Strategy initialized (elapsed=%.2fs)", _ts_init_elapsed)
                    if strategy is None:
                        raise RuntimeError(
                            "FATAL: TradingStrategy() returned None — "
                            "strategy failed to initialize.  Check broker credentials "
                            "and apex strategy import."
                        )
                    _acquired = _acquire_init_lock_bootstrap_only(
                        context="store strategy singleton",
                        timeout_s=5.0,
                    )
                    if not _acquired:
                        raise RuntimeError(
                            "INIT_LOCK_TIMEOUT context=store strategy singleton — "
                            "cannot persist strategy safely"
                        )
                    else:
                        try:
                            if not _publish_strategy_runtime_readiness(
                                strategy,
                                context="startup constructor path",
                            ):
                                raise RuntimeError(
                                    "startup constructor strategy readiness blocked pending execution authority"
                                )
                            logger.debug("Constructor stage=strategy_cached")
                        finally:
                            _initialized_state_lock.release()
                except Exception as e:
                    logger.exception("STRATEGY_INIT_FAILED: %s", e)
                    raise
                logger.debug("Init stage A5: after TradingStrategy()")
                logger.info("🧠 State stored - entering supervisor mode")
                logger.debug("TradingStrategy created after broker connection bootstrap")

            # Bootstrap FSM: broker(s) connected → PLATFORM_READY
            _bfsm_transition(
                _BootstrapState.PLATFORM_READY,
                "TradingStrategy initialized; platform broker(s) connected",
            )

            _total_balance = _hydrate_startup_balances(strategy)
            if _BOOTSTRAP_FSM_AVAILABLE:
                _bfsm_transition(
                    _BootstrapState.BALANCE_HYDRATED,
                    f"startup balance hydration complete: ${_total_balance:.2f}",
                )
                _bfsm_transition(
                    _BootstrapState.CAPABILITY_VERIFIED,
                    "startup capability checks passed after hydration",
                )
                _bfsm_transition(
                    _BootstrapState.STARTUP_VALIDATED,
                    "startup_validation passed all pre-flight checks",
                )
            logger.info(
                "LIFECYCLE: balance hydration complete - FSM state=%s",
                getattr(_get_bootstrap_fsm().state, "value", "UNAVAILABLE")
                if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None
                else "UNAVAILABLE",
            )

            _minimum_trading_balance = float(os.getenv("MINIMUM_TRADING_BALANCE", "1"))
            logger.info(
                "\n🧠 FINAL PRE-TRADE CHECK\n"
                "   Total Balance: $%.2f\n"
                "   Min Required:  %.2f\n"
                "   Eligible:      %s\n",
                _total_balance,
                _minimum_trading_balance,
                _total_balance >= _minimum_trading_balance,
            )
            # ── B: Phase 1 → 2 (brokers registered; capital brain may begin) ────────
            _advance_phase(_Phase.CAPITAL_BRAIN, reason="TradingStrategy initialised; platform brokers connected")

            # ── MICRO_PLATFORM tier floor validation ─────────────────────────
            # Confirm that the sizing module's MICRO_PLATFORM minimum position
            # floor is set to 40 %.  A mismatch here causes under-sized positions
            # that cannot clear execution fees on small accounts.
            try:
                from bot.risk.sizing import MICRO_PLATFORM_MIN_POSITION_PCT as _mp_pct
                _expected_mp = 0.40
                if abs(_mp_pct - _expected_mp) > 1e-6:
                    logger.error(
                        "❌ TIER FLOOR MISMATCH: MICRO_PLATFORM_MIN_POSITION_PCT=%.2f "
                        "(expected %.2f) — update bot/risk/sizing.py",
                        _mp_pct, _expected_mp,
                    )
                else:
                    logger.info(
                        "✅ MICRO_PLATFORM tier floor: %.0f%% (correct)", _mp_pct * 100
                    )
            except ImportError:
                logger.warning("⚠️  Could not verify MICRO_PLATFORM tier floor — bot/risk/sizing.py not found")

            # AUDIT USER BALANCES - Show all user balances regardless of trading status
            # This runs BEFORE trading starts to ensure visibility even if users aren't actively trading
            logger.info("=" * 70)
            logger.info("🔍 AUDITING USER ACCOUNT BALANCES")
            logger.info("=" * 70)
            if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
                logger.debug("Preflight: account sync start")
                strategy.multi_account_manager.audit_user_accounts()
                logger.debug("Preflight: account sync end")
            else:
                logger.warning("   ⚠️  Multi-account manager not available - skipping balance audit")

            # STARTUP BALANCE CONFIRMATION - Display live capital for legal/operational protection
            logger.info("")
            logger.info("=" * 70)
            logger.info("💰 LIVE CAPITAL CONFIRMED:")
            logger.info("=" * 70)
            if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
                try:
                    manager = strategy.multi_account_manager

                    # Get all balances
                    all_balances = manager.get_all_balances()

                    # Platform account total
                    platform_total = sum(all_balances.get('platform', {}).values())
                    logger.info(f"   Platform: ${platform_total:,.2f}")

                    # User accounts - specifically Daivon and Tania
                    users_balances = all_balances.get('users', {})

                    # Find Daivon's balance
                    daivon_total = 0.0
                    for user_id, balances in users_balances.items():
                        if 'daivon' in user_id.lower():
                            daivon_total = sum(balances.values())
                            break
                    logger.info(f"   Daivon: ${daivon_total:,.2f}")

                    # Find Tania's balance
                    tania_total = 0.0
                    for user_id, balances in users_balances.items():
                        if 'tania' in user_id.lower():
                            tania_total = sum(balances.values())
                            break
                    logger.info(f"   Tania: ${tania_total:,.2f}")

                    # Show grand total
                    grand_total = platform_total + daivon_total + tania_total
                    logger.info("")
                    logger.info(f"   🏦 TOTAL CAPITAL UNDER MANAGEMENT: ${grand_total:,.2f}")
                except Exception as e:
                    logger.error(f"   ⚠️  Error fetching balances: {e}")
                    logger.error("   ⚠️  Continuing with startup - balances will be shown in trade logs")
            else:
                logger.warning("   ⚠️  Multi-account manager not available - cannot confirm balances")
            logger.info("=" * 70)

            # Independent trading mode - all accounts trade using same logic
            logger.info("=" * 70)
            logger.info("🔄 INDEPENDENT TRADING MODE ENABLED (NO COPY TRADING)")
            logger.info("=" * 70)
            logger.info("   ✅ Each account trades INDEPENDENTLY using NIJA strategy")
            logger.info("   ✅ Same strategy logic, but executed independently per account")
            logger.info("   ✅ Same risk management rules for all accounts")
            logger.info("   ✅ Position sizing scaled by account balance")
            logger.info("   ❌ NO trade copying or mirroring between accounts")
            logger.info("   ℹ️  All accounts evaluate signals and execute independently")
            logger.info("=" * 70)

            # Log clear trading readiness status
            logger.info("=" * 70)
            logger.info("📊 TRADING READINESS STATUS")
            logger.info("=" * 70)

            # Check which master brokers are connected
            connected_platform_brokers = []
            failed_platform_brokers = []

            if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
                for broker_type, broker in strategy.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        broker_name = broker_type.value
                        logger.info(f"✅ BROKER CONNECTED: {broker_name}")
                        connected_platform_brokers.append(broker_type.value.upper())

            # CRITICAL FIX: Check for brokers with credentials configured but failed to connect
            # This catches cases where credentials are set but connection failed due to:
            # - SDK not installed (krakenex/pykrakenapi missing)
            # - Permission errors (API key lacks required permissions)
            # - Nonce errors (timing issues)
            # - Network errors
            # Check if Kraken was expected but didn't connect
            if kraken_platform_configured and 'KRAKEN' not in connected_platform_brokers:
                failed_platform_brokers.append('KRAKEN')

            # Check if Coinbase was expected but didn't connect
            if (
                coinbase_configured
                and not _is_truthy_env("NIJA_DISABLE_COINBASE", "false")
                and 'COINBASE' not in connected_platform_brokers
            ):
                failed_platform_brokers.append('COINBASE')

            # Track if Kraken credentials were not configured at all
            kraken_not_configured = not kraken_platform_configured

            if connected_platform_brokers:
                logger.info("✅ Connected Platform Exchanges:")
                for exchange in connected_platform_brokers:
                    logger.info(f"   ✅ {exchange}")
                logger.info("")
                
                # Show failures if any
                if failed_platform_brokers:
                    logger.info("")
                    logger.warning("⚠️  Expected but NOT Connected:")
                    for exchange in failed_platform_brokers:
                        logger.warning(f"   ❌ {exchange}")
                        if exchange == 'KRAKEN':
                            # Try to get the specific error from the failed broker instance
                            error_msg = None
                            if hasattr(strategy, 'failed_brokers') and BrokerType.KRAKEN in strategy.failed_brokers:
                                failed_broker = strategy.failed_brokers[BrokerType.KRAKEN]
                                if hasattr(failed_broker, 'last_connection_error') and failed_broker.last_connection_error:
                                    error_msg = failed_broker.last_connection_error

                            if error_msg:
                                _log_kraken_connection_error_header(error_msg)
                                # Check for SDK import errors
                                is_sdk_error = any(pattern in error_msg.lower() for pattern in [
                                    "sdk import error",
                                    "modulenotfounderror",
                                    "no module named 'krakenex'",
                                    "no module named 'pykrakenapi'",
                                ])
                                if is_sdk_error:
                                    logger.error("")
                                    logger.error("      ❌ KRAKEN SDK NOT INSTALLED")
                                    logger.error("      The Kraken libraries (krakenex/pykrakenapi) are missing!")
                                    logger.error("")
                                    logger.error("      🔧 IMMEDIATE FIX REQUIRED:")
                                    logger.error("      1. Verify your deployment platform is using the Dockerfile")
                                    logger.error("")
                                elif "permission" in error_msg.lower():
                                    logger.error("      → Fix: Enable required permissions at https://www.kraken.com/u/security/api")
                                elif "nonce" in error_msg.lower():
                                    logger.error("      → Fix: Wait 1-2 minutes and restart the bot")
                                else:
                                    logger.error("      → Verify credentials at https://www.kraken.com/u/security/api")
                        elif exchange == 'COINBASE':
                            logger.warning("      Coinbase credentials are set but connection failed.")
                            logger.warning("      Common causes:")
                            logger.warning("        • Invalid API key or secret format")
                            logger.warning("        • API key lacks required permissions")
                            logger.warning("        • Account balance check failed (see logs above)")
                            logger.warning("      → Run: python test_v2_balance.py for a detailed diagnosis")
                            logger.warning("      → See README.md → '🔐 Coinbase API Setup' for help")

                logger.info("")
                logger.info(f"📈 Trading will occur on {len(connected_platform_brokers)} exchange(s)")
                logger.info("💡 Each exchange operates independently")
                logger.info("🛡️  Failures on one exchange won't affect others")
            else:
                logger.warning("⚠️  NO PLATFORM EXCHANGES CONNECTED")
                logger.warning("Bot is running in MONITOR MODE (no trades will execute)")
                logger.warning("")
                logger.warning("To enable trading:")
                logger.warning("   1. Run: python3 validate_all_env_vars.py")
                logger.warning("   2. Configure at least one platform exchange")
                logger.warning("   3. Restart the bot")
                
                # Update health status - exchanges configured but none connected
                health_manager.update_exchange_status(connected=0, expected=exchanges_configured)

            logger.info("=" * 70)
            logger.info("⛔ STARTUP INVARIANT: BLOCK TRADING UNTIL TOTAL CAPITAL > $0")
            logger.info("=" * 70)
            CAPITAL_GATE_INTERVAL_S = 15
            CAPITAL_GATE_LOG_EVERY_N_CHECKS = 4
            capital_gate_checks = 0

            # Bootstrap FSM: entering capital gate → CAPITAL_REFRESHING
            _bfsm_transition(
                _BootstrapState.CAPITAL_REFRESHING,
                "waiting for startup capital > $0",
            )

            # ── BOOTSTRAP MASTER SEQUENCE (single authority) ──────────────────
            # Explicitly drive the single-authority capital refresh so that the
            # CapitalAuthority singleton is hydrated before the capital gate
            # polling loop begins.  This eliminates the race condition where
            # dependent systems see INITIALIZING state because no coordinator
            # call has fired yet.
            #
            #   mabm.refresh_capital_authority(trigger="BOOTSTRAP_START")
            #   while not ca.is_hydrated:
            #       time.sleep(0.1)
            #   startup_lock.clear()   ← finalize_bootstrap_ready() equivalent
            _bms_mabm = getattr(strategy, "multi_account_manager", None)
            logger.debug("Bootstrap stage A3: before CapitalAuthority fetch")
            _bms_ca = None
            try:
                from bot.capital_authority import get_capital_authority as _get_ca_bms
                _bms_ca = _get_ca_bms()
            except Exception as _bms_import_err:
                logger.warning("[Bootstrap] Failed to import bot.capital_authority: %s", _bms_import_err)
                try:
                    from capital_authority import get_capital_authority as _get_ca_bms  # type: ignore[assignment]
                    _bms_ca = _get_ca_bms()
                except Exception as _bms_import_err2:
                    logger.warning("[Bootstrap] Failed to import capital_authority: %s", _bms_import_err2)
            _bms_refresh_ok = False
            if _bms_mabm is not None:
                # ── Broker-registration gates ──────────────────────────────────
                # Never call refresh_capital_authority() until real brokers exist.
                # Without these gates the seed path publishes a snapshot whose only
                # entry is the "__bootstrap_seed__" phantom, hydrating the Brain
                # before any real broker is present — the root cause of the bug.
                _bms_gate_start = time.monotonic()
                _bms_gate_timeout = 30.0
                while not _bms_mabm.has_registered_brokers():
                    if time.monotonic() - _bms_gate_start >= _bms_gate_timeout:
                        logger.warning(
                            "[Bootstrap] Timeout waiting for broker registration (%.0fs) — proceeding",
                            _bms_gate_timeout,
                        )
                        break
                    time.sleep(0.1)
                while not _bms_mabm.has_attempted_connections():
                    if time.monotonic() - _bms_gate_start >= _bms_gate_timeout:
                        logger.warning(
                            "[Bootstrap] Timeout waiting for connection attempts (%.0fs) — proceeding",
                            _bms_gate_timeout,
                        )
                        break
                    time.sleep(0.1)
                # ── END broker-registration gates ──────────────────────────────
                # ── B: enforce ordering — capital brain requires brokers registered ─
                # Non-blocking observable check: warn and continue with degraded
                # readiness rather than hard-raising.  The phase may not have
                # propagated yet when a retry reuses the same singleton, or when
                # the advance() fired before this listener was attached.
                if _PHASE_GATE_AVAILABLE:
                    from bot.startup_phase_gate import get_phase_gate as _get_pg2, Phase as _PhaseCheck2
                    if not _get_pg2().is_at_least(_PhaseCheck2.CAPITAL_BRAIN):
                        logger.warning(
                            "[PhaseGate] CAPITAL_BRAIN phase not reached yet — "
                            "continuing with degraded readiness"
                        )
                try:
                    logger.debug("Bootstrap stage A4: before capital refresh call")
                    _bms_mabm.refresh_capital_authority(trigger="BOOTSTRAP_START")
                    logger.info("[Bootstrap] BOOTSTRAP_START capital refresh triggered")
                    logger.debug("Bootstrap stage B4: refresh_capital_authority returned")
                    _bms_refresh_ok = True
                except Exception as _bms_err:
                    logger.warning("[Bootstrap] BOOTSTRAP_START refresh error: %s", _bms_err)
            skip_balance_polling_loop = False
            if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
                try:
                    _bootstrap_fsm = _get_bootstrap_fsm()
                    skip_balance_polling_loop = _bootstrap_fsm.balance_polling_disabled
                    if skip_balance_polling_loop and not _bootstrap_fsm.balance_polling_skip_logged:
                        logger.info(
                            "[Bootstrap] Skipping balance polling loop — bootstrap FSM state=%s",
                            _bootstrap_fsm.state.value,
                        )
                        _bootstrap_fsm.mark_balance_polling_skip_logged()
                except Exception as _skip_err:
                    logger.debug(
                        "[Bootstrap] Unable to read bootstrap FSM state for balance polling skip: %s",
                        _skip_err,
                    )
            if _bms_ca is not None and _bms_refresh_ok:
                # 60 s covers typical cold-start broker API latency; the capital gate
                # polling loop below handles the case where we proceed without hydration.
                _bms_hydrate_start = time.monotonic()
                _bms_hydrate_timeout = 60.0
                _shutdown_event = None
                try:
                    from bot.bootstrap_utils import get_shutdown_event as _get_shutdown_event
                    _shutdown_event = _get_shutdown_event()
                except ImportError:
                    try:
                        from bootstrap_utils import get_shutdown_event as _get_shutdown_event  # type: ignore[import]
                        _shutdown_event = _get_shutdown_event()
                    except ImportError:
                        _shutdown_event = None
                if not skip_balance_polling_loop:
                    while not _bms_ca.is_hydrated and (
                        _shutdown_event is None or not _shutdown_event.is_set()
                    ):
                        if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
                            try:
                                _bootstrap_fsm = _get_bootstrap_fsm()
                                if (
                                    hasattr(_bootstrap_fsm, "is_balance_hydrated")
                                    and _bootstrap_fsm.is_balance_hydrated()
                                ):
                                    logger.info("Stopping startup balance loop")
                                    logger.debug(
                                        "[Bootstrap] bootstrap FSM reports BALANCE_HYDRATED — exiting hydration loop"
                                    )
                                    break
                            except Exception as _fsm_probe_err:
                                logger.debug(
                                    "[Bootstrap] balance loop FSM probe failed: %s",
                                    _fsm_probe_err,
                                )
                        if time.monotonic() - _bms_hydrate_start >= _bms_hydrate_timeout:
                            logger.warning(
                                "[Bootstrap] Capital hydration timeout (%.0fs) — proceeding",
                                _bms_hydrate_timeout,
                            )
                            break
                        # Gate: exit polling loop early if bootstrap FSM already
                        # reports balance hydration complete (avoids infinite loop).
                        if _is_balance_hydrated_ready():
                            logger.info("Lifecycle: bootstrap complete - exiting balance polling loop")
                            break
                        time.sleep(0.1)
                if _bms_ca.is_hydrated:
                    logger.info("[Bootstrap] CapitalAuthority hydrated — releasing startup lock")
                    if _bms_mabm is not None:
                        try:
                            _bms_mabm.finalize_bootstrap_ready()
                        except Exception as _bms_fbr_err:
                            logger.warning("[Bootstrap] finalize_bootstrap_ready error: %s", _bms_fbr_err)
            # ── END BOOTSTRAP MASTER SEQUENCE ─────────────────────────────────
            # ── B: Phase 2 → 3 (capital brain hydrated; strategy engine ready) ──
            logger.info("Lifecycle: entering strategy scheduler")
            _advance_phase(_Phase.STRATEGY_ENGINE, reason="CapitalAuthority hydrated; capital data available")
            if _startup_buffer:
                _startup_buffer.flush_phase("BROKER_REGISTRY")

            def _get_startup_total_capital() -> float:
                _mam = getattr(strategy, "multi_account_manager", None)
                if _mam and hasattr(_mam, "get_all_balances"):
                    _all_balances = _mam.get_all_balances()
                    _platform_raw = _all_balances.get("platform") or {}
                    _users_raw = _all_balances.get("users") or {}
                    _platform_total = sum(_platform_raw.values())
                    _users_total = sum(
                        sum((_user_balances or {}).values())
                        for _user_balances in _users_raw.values()
                    )
                    logger.debug(
                        "[CapGate] path=MAM  platform=%s platform_total=%.4f  "
                        "users=%s users_total=%.4f",
                        _platform_raw,
                        _platform_total,
                        {u: dict(v or {}) for u, v in _users_raw.items()},
                        _users_total,
                    )
                    return float(_platform_total + _users_total)
                _bm = getattr(strategy, "broker_manager", None)
                if _bm and hasattr(_bm, "get_total_balance"):
                    _bm_total = float(_bm.get_total_balance())
                    logger.debug(
                        "[CapGate] path=BM  broker_manager=%s  total=%.4f",
                        type(_bm).__name__,
                        _bm_total,
                    )
                    return _bm_total
                logger.debug(
                    "[CapGate] path=NONE  multi_account_manager=%s  broker_manager=%s",
                    type(getattr(strategy, "multi_account_manager", None)).__name__,
                    type(getattr(strategy, "broker_manager", None)).__name__,
                )
                return 0.0

            logger.debug("Bootstrap stage A5: before capital gate")
            logger.debug("Capital gate entry")
            logger.info("Lifecycle: entering market scanner")
            _capital_gate_deadline = time.time() + 60
            while True:
                logger.debug("Capital gate loop iteration")
                try:
                    _total_capital = _get_startup_total_capital()
                except Exception as _cap_gate_err:
                    logger.warning(
                        "⚠️ Startup capital invariant check failed: %s",
                        _cap_gate_err,
                    )
                    _total_capital = 0.0

                ca = _bms_ca
                # Per-pass diagnostic — tells exactly which field is stuck
                if ca is not None:
                    logger.warning(
                        "[CapGate] hydrated=%s state=%s total=%s ready=%s",
                        ca.is_hydrated,
                        ca.state,
                        ca.total_capital,
                        ca.is_ready(),
                    )

                # ── Blocker-2 self-heal: retry capital refresh if CA is not yet
                # hydrated.  The initial BOOTSTRAP_START call may have returned
                # "pending" when broker_map was still empty (brokers registered
                # but no balance payload yet).  Without retrying here the CA
                # never hydrates and the gate always times out after 60 s.
                if ca is not None and not ca.is_hydrated and _bms_mabm is not None:
                    try:
                        _bms_mabm.refresh_capital_authority(trigger="BOOTSTRAP_START")
                        logger.info("[CapGate] Retried BOOTSTRAP_START capital refresh")
                    except Exception as _retry_err:
                        logger.debug("[CapGate] BOOTSTRAP_START retry error (non-fatal): %s", _retry_err)

                # Gate exit requires BOTH is_ready() (broker balances registered)
                # AND is_hydrated (publish_snapshot/refresh committed data) so that
                # maybe_auto_activate() — which checks is_hydrated via
                # _capital_readiness_gate() — never fails immediately after this
                # loop exits.  Exiting on is_ready() alone when is_hydrated=False
                # is the root cause of the PREFLIGHT→SUPERVISOR stuck loop.
                _ca_gate_ready = ca and ca.is_ready()
                _ca_gate_hydrated = ca and ca.is_hydrated
                _ca_gate_core_systems = ca is not None and hasattr(ca, 'is_hydrated')
                
                # FIX 3: Decouple system_ready from balance
                # System is ready when CORE SYSTEMS initialized, not when balance > 0
                if _ca_gate_core_systems and _ca_gate_hydrated:
                    logger.info(
                        "✅ CAPITAL GATE PASSED — CA hydrated with registered broker balances"
                    )
                    logger.info("🚀 SYSTEM READY — TRADING ENABLED")
                    logger.info("💰 Startup total capital: $%.2f", _total_capital)
                    try:
                        _startup_execution_authority_status(
                            context="capital_gate: capital_ready",
                            force_refresh=True,
                        )
                    except Exception as _gate_signal_err:
                        logger.warning(
                            "Authority status probe failed during capital_ready signal: %s",
                            _gate_signal_err,
                        )
                    try:
                        _rt_mark_ready("capital_ready")
                    except Exception as _gate_signal_err:
                        raise RuntimeError(
                            f"Startup readiness signal failed (capital_ready): {_gate_signal_err}"
                        ) from _gate_signal_err

                    # Capital gate owns only the CAPITAL_READY handoff.
                    # INIT_COMPLETE/THREADS_STARTING/RUNNING_SUPERVISED are owned by
                    # the canonical startup orchestration path below.
                    logger.critical("LIFECYCLE: Capital ready - FSM state before transitions = %s", _bootstrap_state_value())
                    _bfsm_transition(
                        _BootstrapState.CAPITAL_READY,
                        f"startup capital confirmed: ${_total_capital:.2f}",
                    )
                    logger.critical("LIFECYCLE: FSM state after CAPITAL_READY = %s", _bootstrap_state_value())
                    break


                if time.time() > _capital_gate_deadline:
                    logger.warning(
                        "⚠️ CAPITAL GATE TIMEOUT (%.0fs) — forcing system to proceed in degraded mode",
                        time.time() - (_capital_gate_deadline - 60),
                    )
                    logger.warning(
                        "✅ CAPITAL GATE FORCED (DEGRADED) — core systems initialized"
                    )
                    logger.warning("🚀 SYSTEM READY — proceeding with zero or partial balance")
                    try:
                        _startup_execution_authority_status(
                            context="capital_gate: degraded capital_ready",
                            force_refresh=True,
                        )
                    except Exception as _gate_signal_err:
                        logger.warning(
                            "Authority status probe failed during degraded capital_ready signal: %s",
                            _gate_signal_err,
                        )
                    try:
                        _rt_mark_ready("capital_ready")
                    except Exception as _gate_signal_err:
                        raise RuntimeError(
                            f"Startup readiness signal failed (capital_ready): {_gate_signal_err}"
                        ) from _gate_signal_err

                    # Degraded capital gate owns only the CAPITAL_READY handoff.
                    logger.critical("LIFECYCLE: Capital ready (degraded) - FSM state before transitions = %s", _bootstrap_state_value())
                    _bfsm_transition(
                        _BootstrapState.CAPITAL_READY,
                        "capital gate timeout — proceeding in degraded mode",
                    )
                    logger.critical("LIFECYCLE: FSM state after CAPITAL_READY = %s", _bootstrap_state_value())
                    break



                capital_gate_checks += 1
                _should_log_gate = (
                    capital_gate_checks == 1
                    or capital_gate_checks % CAPITAL_GATE_LOG_EVERY_N_CHECKS == 0
                )
                if _should_log_gate:
                    logger.warning(
                        "⏳ Trading loop blocked: waiting for total capital > $0 "
                        "(current=$%.2f, check=#%d, next check in %ds)",
                        _total_capital,
                        capital_gate_checks,
                        CAPITAL_GATE_INTERVAL_S,
                    )
                    # ── Diagnostic: report the exact execution path that returned $0 ──
                    _diag_mam = getattr(strategy, "multi_account_manager", None)
                    _diag_bm = getattr(strategy, "broker_manager", None)
                    logger.warning(
                        "[CapGate-Diag] multi_account_manager=%s  broker_manager=%s",
                        type(_diag_mam).__name__ if _diag_mam is not None else "None",
                        type(_diag_bm).__name__ if _diag_bm is not None else "None",
                    )
                    if _diag_mam is not None:
                        try:
                            _diag_balances = _diag_mam.get_all_balances()
                            logger.warning(
                                "[CapGate-Diag] MAM.get_all_balances()=%s",
                                _diag_balances,
                            )
                        except Exception as _diag_bal_err:
                            logger.warning(
                                "[CapGate-Diag] MAM.get_all_balances() raised: %s",
                                _diag_bal_err,
                            )
                        _diag_has_reg = getattr(_diag_mam, "has_registered_brokers", None)
                        _diag_has_conn = getattr(_diag_mam, "has_attempted_connections", None)
                        logger.warning(
                            "[CapGate-Diag] MAM.has_registered_brokers=%s  "
                            "MAM.has_attempted_connections=%s",
                            _diag_has_reg() if callable(_diag_has_reg) else _diag_has_reg,
                            _diag_has_conn() if callable(_diag_has_conn) else _diag_has_conn,
                        )
                    if _diag_bm is not None:
                        try:
                            logger.warning(
                                "[CapGate-Diag] BM.get_total_balance()=%.4f",
                                float(_diag_bm.get_total_balance()),
                            )
                        except Exception as _diag_bm_err:
                            logger.warning(
                                "[CapGate-Diag] BM.get_total_balance() raised: %s",
                                _diag_bm_err,
                            )
                    # ── Diagnostic: CapitalAuthority hydration state ──────────────
                    if _bms_ca is not None:
                        try:
                            logger.warning(
                                "[CapGate-Diag] CapitalAuthority.is_hydrated=%s  "
                                "state=%s  total_capital=%.4f",
                                _bms_ca.is_hydrated,
                                getattr(_bms_ca, "state", "N/A"),
                                float(getattr(_bms_ca, "total_capital", 0) or 0),
                            )
                        except Exception as _diag_ca_err:
                            logger.warning(
                                "[CapGate-Diag] CapitalAuthority probe raised: %s",
                                _diag_ca_err,
                            )
                    # ── Diagnostic: trading state machine current state ───────────
                    try:
                        from bot.trading_state_machine import get_state_machine as _get_tsm_diag
                        _tsm_diag = _get_tsm_diag()
                        logger.warning(
                            "[CapGate-Diag] TradingStateMachine.state=%s",
                            _tsm_diag.get_current_state().value,
                        )
                    except Exception as _diag_tsm_err:
                        logger.warning(
                            "[CapGate-Diag] TradingStateMachine probe raised: %s",
                            _diag_tsm_err,
                        )
                time.sleep(3)
            logger.info("=" * 70)
            # ── B: Phase 3 → 4 (strategy engine ready; execution layer may begin) ──
            logger.info("Lifecycle: entering signal generation")
            if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm is not None:
                logger.info(
                    "Execution enablement deferred until final bootstrap unlock "
                    "(state=%s)",
                    getattr(_get_bootstrap_fsm().state, "value", "unknown"),
                )
            logger.info("Lifecycle: entering order execution coordinator")
            _advance_phase(_Phase.EXECUTION_LAYER, reason="startup capital confirmed; strategy engine ready")
            if _startup_buffer:
                _startup_buffer.flush_phase("CAPITAL_BRAIN")

            logger.info("B1 reached - bootstrap complete; activation delegated to core loop")

            # ── B1 PRE-FLIGHT GUARD ────────────────────────────────────────────────
            # Deterministic forward-movement contract: B1 MUST exit via one of two
            # paths — B2 (proceed to thread launch) or B1_BLOCKED (halt with error).
            # A silent return here (check passes but no transition is made) causes
            # FSM freeze: the trading state machine stalls in OFF with no thread,
            # no loop, and no observable error.
            #
            # Single-execution contract: _b1_executed is set True the first time
            # B1 runs so the HARD STARTUP BARRIER below can detect the case and
            # skip straight to B2.  Only the bootstrap kernel thread (BotStartup)
            # should reach this point; the BootstrapStateMachine ownership guard
            # enforces this at the FSM level.
            logger.info("B1 preflight guard entered")
            with _b1_executed_lock:
                _b1_already_ran = _b1_executed

            if _b1_already_ran:
                logger.info("B1 preflight guard skipped: already executed; proceeding to B2")
            else:
                # Probe each condition fail-closed: absent optional modules → True
                # (feature not required); present module with a failed probe → False.
                # Never default to True on exception — the FSM must not lie to itself.
                _b1_brokers_ready = False
                try:
                    if _bms_mabm is None:
                        _b1_brokers_ready = True  # no MABM → not a requirement in this deployment
                    elif hasattr(_bms_mabm, "all_brokers_fully_ready"):
                        # Poll so that async broker initialisation (e.g. Coinbase balance-payload
                        # fetch) can complete before B1 runs.  A single-shot check at B1 time is
                        # too early: initialize_platform_brokers() may still be delivering the
                        # first balance snapshot.  If brokers are still not ready after the poll,
                        # mark N/A when no platform brokers are registered at all.
                        _b1_br_deadline = time.monotonic() + _B1_BROKER_READY_POLL_TIMEOUT_S
                        while time.monotonic() < _b1_br_deadline:
                            if bool(_bms_mabm.all_brokers_fully_ready()):
                                _b1_brokers_ready = True
                                break
                            time.sleep(_B1_BROKER_READY_POLL_INTERVAL_S)
                        if not _b1_brokers_ready:
                            # Use the public has_registered_brokers() method to check
                            # whether any platform brokers are registered at all.
                            _b1_has_brokers = bool(
                                _bms_mabm.has_registered_brokers()
                                if hasattr(_bms_mabm, "has_registered_brokers")
                                else True  # assume present if method missing
                            )
                            if not _b1_has_brokers:
                                _b1_brokers_ready = True
                                logger.info(
                                    "[B1-Guard] No platform brokers registered — treating brokers_ready as N/A"
                                )
                            else:
                                logger.warning(
                                    "[B1-Guard] Brokers not fully ready after %.0f s poll — B1 will be marked failed",
                                    _B1_BROKER_READY_POLL_TIMEOUT_S,
                                )
                except Exception as _b1_br_err:
                    logger.warning("[B1-Guard] brokers_ready probe failed (fail-closed False): %s", _b1_br_err)

                _b1_capital_hydrated = False
                try:
                    if _bms_ca is None:
                        _b1_capital_hydrated = False  # CA absent: hydration cannot be confirmed
                    else:
                        _b1_capital_hydrated = bool(_bms_ca.is_hydrated)
                except Exception as _b1_ch_err:
                    logger.warning("[B1-Guard] capital_hydrated probe failed (fail-closed False): %s", _b1_ch_err)

                _b1_aggregation_normalized = True  # True when capital FSM module is absent
                try:
                    from bot.capital_flow_state_machine import get_capital_bootstrap_fsm as _get_cbfsm_b1
                    _cbfsm_b1 = _get_cbfsm_b1()
                    _b1_aggregation_normalized = bool(_cbfsm_b1.is_ready)
                except ImportError:
                    pass  # capital FSM not present → no aggregation requirement
                except Exception as _b1_an_err:
                    _b1_aggregation_normalized = False  # probe failed on present module
                    logger.warning("[B1-Guard] aggregation_normalized probe failed (fail-closed False): %s", _b1_an_err)

                _b1_nonce_ready = True
                if _nonce_readiness_required_for_startup():
                    try:
                        from bot.broker_manager import _KRAKEN_STARTUP_FSM as _kfsm_b1
                        _b1_nonce_ready = bool(_kfsm_b1.is_nonce_ready())
                    except ImportError:
                        _b1_nonce_ready = False
                        logger.warning(
                            "[B1-Guard] nonce_ready required but Kraken startup FSM import failed"
                        )
                    except Exception as _b1_nr_err:
                        _b1_nonce_ready = False  # probe failed on present module
                        logger.warning("[B1-Guard] nonce_ready probe failed (fail-closed False): %s", _b1_nr_err)

                logger.info("B1 preflight conditions: %s", {
                    "brokers_ready": _b1_brokers_ready,
                    "aggregation_normalized": _b1_aggregation_normalized,
                    "capital_hydrated": _b1_capital_hydrated,
                    "nonce_ready": _b1_nonce_ready,
                })

                _b1_preflight_ready = (
                    _b1_brokers_ready
                    and _b1_aggregation_normalized
                    and _b1_capital_hydrated
                    and _b1_nonce_ready
                )

                if not _b1_preflight_ready:
                    logger.critical("CRITICAL B1 RESULT: FAIL")
                    logger.critical("❌ B1 BLOCKED — PRE-FLIGHT INCOMPLETE")
                    with _b1_executed_lock:
                        # Mark executed even on failure so the barrier below does not re-run
                        globals()["_b1_executed"] = True
                    try:
                        from bot.exceptions import CapitalIntegrityError as _CIE_b1
                    except ImportError:
                        from exceptions import CapitalIntegrityError as _CIE_b1  # type: ignore[import]
                    raise _CIE_b1("B1 PRE-FLIGHT INCOMPLETE")

                logger.info("B1 preflight result: PASS")
                logger.info("✅ B1 passed - transitioning to B2")
                with _b1_executed_lock:
                    globals()["_b1_executed"] = True
                logger.debug("B1 exit guarantee reached")
            # ── END B1 PRE-FLIGHT GUARD ───────────────────────────────────────────

            # ── CONNECTION → INIT HANDOFF ──────────────────────────────────────────
            # Activation is now owned exclusively by the core trading loop
            # (nija_core_loop.run_trading_loop).  maybe_auto_activate() is NOT
            # called here — the core loop calls it on every cycle until the
            # state machine transitions to LIVE_ACTIVE.  Calling it here caused
            # race conditions when CA hydration happened after bootstrap but
            # before the loop first ran.
            from bot.trading_state_machine import get_state_machine as _get_tsm_init
            _tsm_init = _get_tsm_init()
            logger.info(
                "BOOTSTRAP SM STATE: %s (LIVE_CAPITAL_VERIFIED=%r) — core loop will activate",
                _tsm_init.get_current_state().value,
                os.environ.get("LIVE_CAPITAL_VERIFIED", ""),
            )

            logger.info(
                "Execution handoff deferred until BootstrapFSM reaches RUNNING_SUPERVISED"
            )

            # Do not synthesize core-loop readiness here; startup readiness must
            # be driven by real state transitions only.
            logger.debug("READINESS_MUTATION_REMOVED marker=post_handoff_loop_trigger")
            # ── END CONNECTION → INIT HANDOFF ────────────────────────────────────

            # ═══════════════════════════════════════════════════════════════════════
            # BULLETPROOF TRADING ORCHESTRATOR
            # ═══════════════════════════════════════════════════════════════════════
            # Architecture:
            #   1. Detect funded platform + user brokers.
            #   2. Start a self-healing daemon thread per broker via
            #      _start_trader_thread / _start_single_broker_thread.
            #   3. Supervisor loop checks thread health every 10 s and restarts
            #      any thread that dies unexpectedly.
            #   4. NEVER exits silently — process stays alive until SIGTERM/SIGINT.
            #
            # Bug fixed: previously, when strategy.independent_trader was None
            # (init failure) but MULTI_BROKER_INDEPENDENT=true (the default),
            # NEITHER the independent loop NOR the single-broker fallback would
            # run — sending the bot directly to the keep-alive loop with zero
            # trading activity.
            # ═══════════════════════════════════════════════════════════════════════

            # ── Bootstrap FSM invariant guards before launching trading threads ──
            if _BOOTSTRAP_FSM_AVAILABLE:
                _boot_fsm = _get_bootstrap_fsm()
                # I4: capital bootstrap must be READY
                try:
                    _boot_fsm.assert_invariant_i4_capital_gate()
                except Exception as _inv_err:
                    logger.warning("⚠️  Bootstrap invariant I4 violation: %s", _inv_err)
                # I7: EMERGENCY_STOP blocks thread launch
                try:
                    _boot_fsm.assert_invariant_i7_emergency_safety()
                except Exception as _inv_err:
                    logger.warning("⚠️  Bootstrap invariant I7 violation: %s", _inv_err)

            # ── Bootstrap FSM advance to THREADS_STARTING ────────────────────────
            # Activation is now owned by the core trading loop, so we no longer
            # block thread launch on LIVE_ACTIVE state here.  The core loop will
            # only run trade cycles once activation is committed.  Log current
            # state for diagnostics and advance the bootstrap FSM.
            from bot.trading_state_machine import get_state_machine as _get_tsm, TradingState as _TradingState
            _tsm = _get_tsm()
            logger.info(
                "[Bootstrap] SM state before thread launch: %s — core loop owns activation",
                _tsm.get_current_state().value,
            )

            # Maintain a single canonical INIT_COMPLETE transition marker in this
            # startup orchestration path. The helper is best-effort/non-fatal and
            # preserves ordering invariants even when earlier gate logic already
            # advanced state in degraded or resumed paths.
            _bfsm_transition(
                _BootstrapState.INIT_COMPLETE,
                "startup orchestration: initialization complete before bootstrap readiness signal",
            )
            logger.critical("LIFECYCLE: FSM state at thread-launch boundary = %s", _bootstrap_state_value())
            _rt_mark_ready("bootstrap_ready")

            # Bootstrap-owned NONCE phase: execute after INIT_COMPLETE boundary
            # and before RUN loop thread launch.
            _bootstrap_nonce_reset_once()

            # Publish readiness-table signals that are validated by B1 probes.
            # This keeps the truth-table gate aligned with actual startup checks
            # before THREADS_STARTING.
            try:
                if _bms_mabm is None:
                    _rt_mark_not_applicable(
                        "broker_connected",
                        reason="MABM unavailable in this deployment",
                    )
                elif hasattr(_bms_mabm, "all_brokers_fully_ready"):
                    # Wait up to _BROKER_CONNECTED_READY_TIMEOUT_S for platform
                    # brokers to finish their initial connection handshake and
                    # receive a balance payload.  Without this wait the check
                    # races against async broker initialisation and permanently
                    # blocks the main-thread system_ready gate.
                    _bc_deadline = time.monotonic() + _BROKER_CONNECTED_READY_TIMEOUT_S
                    while (
                        not bool(_bms_mabm.all_brokers_fully_ready())
                        and time.monotonic() < _bc_deadline
                    ):
                        time.sleep(0.5)
                    if bool(_bms_mabm.all_brokers_fully_ready()):
                        _rt_mark_ready("broker_connected")
                        logger.info("Startup readiness broker gate passed — broker_connected set")
                    else:
                        logger.warning(
                            "Startup broker readiness timed out after %.0f s — "
                            "leaving broker_connected=False for policy evaluation; "
                            "broker may still connect asynchronously table=%s",
                            _BROKER_CONNECTED_READY_TIMEOUT_S,
                            _rt_snapshot(),
                        )
                else:
                    logger.warning(
                        "Startup readiness probe missing all_brokers_fully_ready; "
                        "leaving broker_connected=False for policy evaluation"
                    )
            except Exception as _gate_broker_err:
                logger.warning("Startup readiness signal failed (broker_connected): %s", _gate_broker_err)

            try:
                if not _nonce_readiness_required_for_startup():
                    _rt_mark_not_applicable(
                        "nonce_ready",
                        reason="Kraken nonce readiness not required in this startup mode",
                    )
                else:
                    try:
                        from bot.broker_manager import _KRAKEN_STARTUP_FSM as _gate_kraken_fsm
                    except ImportError:
                        _gate_kraken_fsm = None
                    if _gate_kraken_fsm is None:
                        logger.warning(
                            "Startup nonce readiness required but Kraken startup FSM is unavailable; "
                            "leaving nonce_ready=False for policy evaluation"
                        )
                    elif bool(_gate_kraken_fsm.is_nonce_ready()):
                        _rt_mark_ready("nonce_ready")
                    else:
                        logger.warning(
                            "Startup readiness nonce gate pending at INIT_COMPLETE boundary; "
                            "leaving nonce_ready=False for policy evaluation"
                        )
            except Exception as _gate_nonce_err:
                logger.warning("Startup readiness signal failed (nonce_ready): %s", _gate_nonce_err)

            logger.info("READINESS TABLE before THREADS_STARTING gate (diagnostic): %s", _rt_snapshot())
            _criteria, _required_missing, _optional_missing, _policy_deadline = _evaluate_startup_readiness_policy(
                context="init_complete->threads_starting",
                timeout_s=_STARTUP_POLICY_EVAL_TIMEOUT_S,
            )
            if _required_missing:
                logger.critical(
                    "STARTUP_POLICY_BLOCKED context=init_complete->threads_starting state=%s "
                    "required_missing=%s optional_missing=%s criteria=%s deadline=%.2f next=BOOT_FAILED_RETRY",
                    _bootstrap_state_value(),
                    _required_missing,
                    _optional_missing,
                    _criteria,
                    max(0.0, _policy_deadline - time.monotonic()),
                )
                if _BOOTSTRAP_FSM_AVAILABLE:
                    _bfsm_transition(
                        _BootstrapState.BOOT_FAILED_RETRY,
                        f"required startup criteria missing before THREADS_STARTING: {_required_missing}",
                    )
                raise RuntimeError(
                    "STARTUP_POLICY_BLOCKED before THREADS_STARTING: "
                    f"required_missing={_required_missing} criteria={_criteria}"
                )
            if _optional_missing and _BOOTSTRAP_FSM_AVAILABLE:
                logger.warning(
                    "STARTUP_POLICY_DEGRADED context=init_complete->threads_starting state=%s "
                    "optional_missing=%s criteria=%s deadline=%.2f next=DEGRADED_READY",
                    _bootstrap_state_value(),
                    _optional_missing,
                    _criteria,
                    max(0.0, _policy_deadline - time.monotonic()),
                )
                _bfsm_transition(
                    _BootstrapState.DEGRADED_READY,
                    f"optional startup criteria timed out before THREADS_STARTING: {_optional_missing}",
                )

            # Advance bootstrap FSM to THREADS_STARTING only after all readiness
            # conditions are confirmed so that any failure above leaves the FSM at
            # INIT_COMPLETE (from which reset_for_retry can reach BOOT_FAILED_RETRY).
            if _BOOTSTRAP_FSM_AVAILABLE:
                _bfsm_transition(
                    _BootstrapState.THREADS_STARTING,
                    "spawning trading worker threads",
                )

            logger.critical(
                "LIFECYCLE: FSM state=%s",
                _bootstrap_state_value(),
            )
            logger.info("Lifecycle: entering cycle scheduler")

            use_independent_trading = (
                os.getenv("MULTI_BROKER_INDEPENDENT", "true").lower() in ["true", "1", "yes"]
                and strategy.independent_trader is not None
            )

            # _active_threads: broker_key → {thread, stop_flag, broker_type, broker, mode, ...}
            _active_threads, use_independent_trading = _launch_trading_threads(
                strategy, use_independent_trading, _hf_bot
            )
            logger.info("B4 execution loop started")
            logger.critical(
                "LIFECYCLE: FSM state=%s",
                _bootstrap_state_value(),
            )
            logger.info("Lifecycle: entering live trading runtime")

            # ── FIX 2: RUNTIME START CONFIRMATION ──────────────────────────────────
            # Emit the definitive "RUNTIME MODE ACTIVE" log ONLY when all three
            # conditions are met: LIVE_ACTIVE state, CA_READY, and execution engine
            # initialized.  This provides an unambiguous proof that the trading loop
            # has actually begun; its absence in logs means a stall occurred.
            try:
                from bot.trading_state_machine import get_state_machine as _gsm, TradingState as _TS
                _sm_state = _gsm().get_current_state()
            except Exception:
                try:
                    from trading_state_machine import get_state_machine as _gsm, TradingState as _TS
                    _sm_state = _gsm().get_current_state()
                except Exception:
                    _sm_state = None
                    _TS = None

            _ca_ready_flag = False
            try:
                from bot.capital_authority import get_capital_authority as _gca
                _ca_ready_flag = _gca().is_ready()
            except Exception:
                try:
                    from capital_authority import get_capital_authority as _gca  # type: ignore[import]
                    _ca_ready_flag = _gca().is_ready()
                except Exception:
                    _ca_ready_flag = False  # fail-closed: block confirmation if CA unavailable

            _exec_engine_ready = (
                hasattr(strategy, "execution_engine")
                and strategy.execution_engine is not None
            )

            if (
                _sm_state is not None
                and _TS is not None
                and _sm_state == _TS.LIVE_ACTIVE
                and _ca_ready_flag
                and _exec_engine_ready
            ):
                logger.info(
                    "✅ RUNTIME MODE ACTIVE — market loop starting "
                    "(CA_READY=True, LIVE_ACTIVE=True, execution_engine=initialized)"
                )
            else:
                logger.warning(
                    "⚠️ RUNTIME START: one or more readiness conditions not met — "
                    "LIVE_ACTIVE=%s CA_READY=%s execution_engine=%s",
                    _sm_state == _TS.LIVE_ACTIVE if (_sm_state and _TS) else "unknown",
                    _ca_ready_flag,
                    _exec_engine_ready,
                )

            # ═══════════════════════════════════════════════════════════════════════
            # SUPERVISOR LOOP — monitors every 10 s, restarts dead threads
            # ═══════════════════════════════════════════════════════════════════════

            # Persist initialised state (thread-safe) so a supervisor-loop crash
            # can be retried WITHOUT recreating TradingStrategy or reconnecting brokers.
            _acquired = _acquire_init_lock_bootstrap_only(
                context="persist initialized state",
                timeout_s=5.0,
            )
            if not _acquired:
                raise RuntimeError(
                    "INIT_LOCK_TIMEOUT context=persist initialized state — "
                    "runtime cache persistence blocked"
                )
            else:
                try:
                    _initialized_state = {
                        "strategy": strategy,
                        "active_threads": _active_threads,
                        "use_independent_trading": use_independent_trading,
                        "health_manager": health_manager,
                    }
                finally:
                    _initialized_state_lock.release()
            # Signal that strategy initialization is complete — set before
            # _rerun_supervisor_loop so the supervisor never starts with a
            # partially initialised state.  This is the single authoritative
            # "strategy ready" gate used by the supervisor, core loop, and
            # BootstrapFSM (FIX A + FIX C from architecture spec).
            logger.info("🚀 System ready - entering trading loop")
            logger.debug(
                "State check keys: %s",
                sorted(list(_initialized_state.keys())),
            )
            logger.info("🧠 State stored - entering supervisor mode")

            _log_lifecycle_banner(
                "🔒 ORCHESTRATOR ACTIVE",
                [
                    f"{len(_active_threads)} trader thread(s) running",
                    "Supervisor checks thread health every 10s",
                    "Dead threads are restarted automatically",
                    "Process will never exit silently",
                    *_get_thread_status(),
                ],
            )

            logger.critical(
                "LIFECYCLE: entering strategy scheduler"
            )
            logger.critical("LIFECYCLE: entering market scanner")
            _ensure_running_supervised(_active_threads, context="threads live (pre-handoff)")
            if not _enable_execution_after_bootstrap_supervised(
                context="threads live (pre-handoff)"
            ):
                raise RuntimeError(
                    "Startup blocked: final bootstrap unlock did not complete before enabling execution"
                )
            _verify_runtime_transition_states(context="threads live (pre-handoff)")
            logger.critical("LIFECYCLE: FSM state=%s", _bootstrap_state_value())

            # STEP 3 — ALWAYS run trading loop via the shared supervisor.
            # Delegates to _rerun_supervisor_loop so the supervisor logic lives
            # in exactly one place and retries (fast-path) use the same code.
            _acquired = _acquire_init_lock_bootstrap_only(
                context="supervisor handoff snapshot",
                timeout_s=5.0,
            )
            if not _acquired:
                raise RuntimeError(
                    "INIT_LOCK_TIMEOUT context=supervisor handoff snapshot — "
                    "cannot hand off supervisor state safely"
                )
            else:
                try:
                    _state_for_supervisor = dict(_initialized_state)
                finally:
                    _initialized_state_lock.release()

            try:
                _barrier_state = _rt_snapshot()
                logger.info("Barrier state: %s", _barrier_state)
                if not _rt_is_ready():
                    _required_missing = sorted(k for k, v in _barrier_state.items() if not v)
                    logger.error("❌ Barrier still blocking execution loop")
                    raise RuntimeError(
                        "Startup readiness barrier blocked at bootstrap completion: "
                        f"required_missing={_required_missing} state={_barrier_state}"
                    )
            except Exception as _gate_signal_err:
                logger.warning("⚠️ readiness table signal failed at bootstrap completion: %s", _gate_signal_err)
            _emit_startup_orchestration_snapshot("bootstrap_complete")
            logger.debug("READINESS_MUTATION_REMOVED marker=bootstrap_core_loop_signal")
            logger.info("✅ [Bootstrap] Core-loop signal mutation removed — awaiting final supervisor handoff")
            # ── HARD STARTUP BARRIER ─────────────────────────────────────────────
            # Enforce the startup invariant: _bootstrap_completed_event must only
            # be set AFTER all six conditions hold simultaneously (B1 preflight):
            #   1. brokers_ready          — all platform brokers fully connected
            #   2. first_snap             — first live-exchange capital snapshot accepted
            #   3. capital_fsm_ready      — CapitalBootstrapFSM has reached READY
            #   4. capital_hydrated       — CapitalAuthority is hydrated (is_hydrated=True)
            #   5. aggregation_normalized — CA registered broker count matches MABM viable count
            #   6. nonce_ready            — Kraken nonce FSM has authorized nonce issuance
            #
            # Without this gate the core loop (which calls maybe_auto_activate)
            # could start before the system is truly ready, causing phantom vetoes.
            # We wait up to 30 s for conditions already expected to be true from
            # earlier in the bootstrap sequence; if they still are not met we log
            # B1 BLOCKED and proceed as a fail-safe to avoid a deadlock.
            #
            # Single-execution contract: if _b1_executed is already True the early
            # B1 PRE-FLIGHT GUARD already validated and passed these conditions.
            # Skip the polling loop and proceed directly to B2 so B1 runs exactly once.
            with _b1_executed_lock:
                _barrier_b1_skip = _b1_executed
            if _barrier_b1_skip:
                logger.info("B1 preflight guard skipped: already executed by bootstrap kernel; advancing to B2")
            else:
                logger.info("B1 preflight barrier entered")
                _bce_first_snap = False
                _bce_brokers_ready = False
                _bce_capital_fsm_ready = False
                _bce_capital_hydrated = False
                _bce_aggregation_normalized = False  # fail-closed: False until aggregation is proven normalized or not applicable
                _bce_nonce_ready = False
                # Resolve module references once, outside the polling loop.
                try:
                    from bot.trading_state_machine import get_state_machine as _get_tsm_bce
                except Exception as _bce_import_err:
                    logger.warning("[Bootstrap-Barrier] could not import trading_state_machine: %s", _bce_import_err)
                    _get_tsm_bce = None  # type: ignore[assignment]
                try:
                    from bot.multi_account_broker_manager import (
                        multi_account_broker_manager as _mabm_bce,
                    )
                except Exception as _bce_import_err:
                    logger.warning("[Bootstrap-Barrier] could not import multi_account_broker_manager: %s", _bce_import_err)
                    _mabm_bce = None  # type: ignore[assignment]
                try:
                    from bot.capital_flow_state_machine import (
                        get_capital_bootstrap_fsm as _get_cbfsm_bce,
                    )
                except Exception as _bce_import_err:
                    logger.warning("[Bootstrap-Barrier] could not import capital_flow_state_machine: %s", _bce_import_err)
                    _get_cbfsm_bce = None  # type: ignore[assignment]
                try:
                    from bot.broker_manager import _KRAKEN_STARTUP_FSM as _kraken_fsm_bce
                except Exception as _bce_import_err:
                    logger.warning("[Bootstrap-Barrier] could not import _KRAKEN_STARTUP_FSM: %s", _bce_import_err)
                    _kraken_fsm_bce = None  # type: ignore[assignment]
                
                # FIX 2: Probe loop must not block startup
                _bce_deadline = time.monotonic() + 15  # 15-second probe timeout
                _bce_start = time.monotonic()
                
                while True:
                    try:
                        _bce_first_snap = _get_tsm_bce().get_first_snap_accepted() if _get_tsm_bce is not None else False
                    except Exception as _bce_err:
                        logger.debug("[Bootstrap-Barrier] first_snap probe failed: %s", _bce_err)
                        _bce_first_snap = False
                    try:
                        # Absent MABM → not required (not a Kraken multi-account deployment)
                        _bce_brokers_ready = bool(_mabm_bce.all_brokers_fully_ready()) if _mabm_bce is not None else True
                    except Exception as _bce_err:
                        logger.debug("[Bootstrap-Barrier] brokers_ready probe failed (fail-closed): %s", _bce_err)
                        _bce_brokers_ready = False
                    try:
                        # Absent capital FSM → not required
                        _bce_capital_fsm_ready = _get_cbfsm_bce().is_ready if _get_cbfsm_bce is not None else True
                    except Exception as _bce_err:
                        logger.debug("[Bootstrap-Barrier] capital_fsm probe failed (fail-closed): %s", _bce_err)
                        _bce_capital_fsm_ready = False
                    try:
                        _bce_capital_hydrated = bool(_bms_ca.is_hydrated) if _bms_ca is not None else False
                    except Exception as _bce_err:
                        logger.debug("[Bootstrap-Barrier] capital_hydrated probe failed: %s", _bce_err)
                        _bce_capital_hydrated = False
                    try:
                        if _mabm_bce is not None and _bms_ca is not None:
                            _bce_ca_registered = int(getattr(_bms_ca, "registered_broker_count", 0) or 0)
                            _bce_mabm_last_vb = int(getattr(_mabm_bce, "_capital_last_valid_brokers", 0) or 0)
                            if _bce_mabm_last_vb > 0 and _bce_ca_registered < _bce_mabm_last_vb:
                                _bce_aggregation_normalized = False
                            else:
                                _bce_aggregation_normalized = True
                        else:
                            _bce_aggregation_normalized = True  # MABM or CA absent → not applicable
                    except Exception as _bce_err:
                        logger.debug("[Bootstrap-Barrier] aggregation_normalized probe failed (fail-closed): %s", _bce_err)
                        _bce_aggregation_normalized = False
                    try:
                        # Absent Kraken FSM → nonce not required (Coinbase-only deployment)
                        _bce_nonce_ready = bool(_kraken_fsm_bce.is_nonce_ready()) if _kraken_fsm_bce is not None else True
                    except Exception as _bce_err:
                        logger.debug("[Bootstrap-Barrier] nonce_ready probe failed (fail-closed): %s", _bce_err)
                        _bce_nonce_ready = False

                    _bce_preflight_ready = (
                        _bce_first_snap
                        and _bce_brokers_ready
                        and _bce_capital_fsm_ready
                        and _bce_capital_hydrated
                        and _bce_aggregation_normalized
                        and _bce_nonce_ready
                    )
                    logger.info(
                        "B1 barrier conditions: %s",
                        {
                            "brokers_ready": _bce_brokers_ready,
                            "first_snap": _bce_first_snap,
                            "capital_fsm_ready": _bce_capital_fsm_ready,
                            "capital_hydrated": _bce_capital_hydrated,
                            "aggregation_normalized": _bce_aggregation_normalized,
                            "nonce_ready": _bce_nonce_ready,
                        },
                    )
                    if _bce_preflight_ready:
                        logger.info(
                            "B1 barrier result: PASS — "
                            "first_snap=%s brokers_ready=%s capital_fsm_ready=%s "
                            "capital_hydrated=%s aggregation_normalized=%s nonce_ready=%s",
                            _bce_first_snap, _bce_brokers_ready, _bce_capital_fsm_ready,
                            _bce_capital_hydrated, _bce_aggregation_normalized, _bce_nonce_ready,
                        )
                        logger.info(
                            "✅ [Bootstrap] B1 PREFLIGHT PASSED — advancing to B2 — "
                            "first_snap=%s brokers_ready=%s capital_fsm_ready=%s "
                            "capital_hydrated=%s aggregation_normalized=%s nonce_ready=%s",
                            _bce_first_snap, _bce_brokers_ready, _bce_capital_fsm_ready,
                            _bce_capital_hydrated, _bce_aggregation_normalized, _bce_nonce_ready,
                        )
                        break
                    if time.monotonic() >= _bce_deadline:
                        logger.warning(
                            "B1 barrier timeout converted to diagnostics-only gate — "
                            "first_snap=%s brokers_ready=%s capital_fsm_ready=%s "
                            "capital_hydrated=%s aggregation_normalized=%s nonce_ready=%s "
                            "next=continue_startup_degraded",
                            _bce_first_snap,
                            _bce_brokers_ready,
                            _bce_capital_fsm_ready,
                            _bce_capital_hydrated,
                            _bce_aggregation_normalized,
                            _bce_nonce_ready,
                        )
                        if _BOOTSTRAP_FSM_AVAILABLE:
                            _bfsm_transition(
                                _BootstrapState.DEGRADED_READY,
                                "B1 diagnostics barrier timeout — continuing degraded",
                            )
                        break
                    logger.warning(
                        "⏳ [Bootstrap] Waiting for B1 preflight — "
                        "first_snap=%s brokers_ready=%s capital_fsm_ready=%s "
                        "capital_hydrated=%s aggregation_normalized=%s nonce_ready=%s",
                        _bce_first_snap, _bce_brokers_ready, _bce_capital_fsm_ready,
                        _bce_capital_hydrated, _bce_aggregation_normalized, _bce_nonce_ready,
                    )
                    time.sleep(1)
                # Mark B1 executed so any future code path that reaches a B1
                # block skips directly to B2 (single-execution contract).
                with _b1_executed_lock:
                    globals()["_b1_executed"] = True
            # Signal bootstrap completion so the supervisor loop knows trader
            # threads are running independently.  From this point forward a
            # thread exit means "hand off to supervisor" not "crash".
            if strategy is None:
                logger.critical("❌ FATAL: Bootstrap completing WITHOUT strategy")
                raise RuntimeError("Strategy not initialized at bootstrap completion")
            _bootstrap_complete_flag.set()
            _bootstrap_completed_event.set()
            logger.info("✅ B1 -> B2: bootstrap_completed_event set; system handed to supervisor loop")

            # Activation is owned exclusively by run_trading_loop().
            # main() spawns that thread once after this event is set.

            # Enforce startup truth conditions before supervised execution.
            _verify_startup_truth_conditions(
                strategy,
                _active_threads,
                kraken_credentials_valid=_kraken_credentials_valid,
            )

            # ── B: Phase 4 → 5 (execution layer live; live trading enabled) ─────────
            _advance_phase(_Phase.LIVE_ENABLE, reason="trading threads running; supervisor loop starting")
            # ── A: flush remaining startup output; restore per-line console logging ──
            if _startup_buffer:
                _startup_buffer.flush_phase("EXECUTION_LAYER")
                _startup_buffer.uninstall()

            logger.info("Bootstrap completing - setting state and exiting startup thread")
            _rerun_supervisor_loop(_state_for_supervisor)

        except RuntimeError as e:
            if "Broker connection failed" in str(e):
                _log_exit_point(
                    "Broker Connection Failed",
                    exit_code=1,
                    details=[
                        "RuntimeError: Broker connection failed",
                        "Credentials not found or invalid",
                        *_get_thread_status()
                    ]
                )
                raise
            else:
                _log_exit_point(
                    "Fatal Initialization Error",
                    exit_code=1,
                    details=[
                        f"RuntimeError: {str(e)}",
                        "Bot initialization failed",
                        *_get_thread_status()
                    ]
                )
                logger.error(f"Fatal error initializing bot: {e}", exc_info=True)
                raise
        except Exception as e:
            _log_exit_point(
                "Unhandled Fatal Error in Startup Thread",
                exit_code=1,
                details=[
                    f"Exception Type: {type(e).__name__}",
                    f"Error: {str(e)}",
                    "An unexpected error occurred in startup thread",
                    *_get_thread_status()
                ]
            )
            logger.exception(f"❌ Startup thread crashed: {e}")
            raise
            
    except Exception as e:
        logger.exception(f"🧵 ❌ Fatal error in startup thread outer handler: {e}")
        raise
    finally:
        # A: Guarantee the startup buffer is uninstalled on every exit path
        # (success, error, KeyboardInterrupt) so no records are silently lost
        # after startup completes or fails.  uninstall() is idempotent.
        if _startup_buffer:
            _startup_buffer.uninstall()
        # B: Preserve bootstrap completion only for the real success path.
        # The supervisor distinguishes a successful handoff from a failed
        # startup by reading _bootstrap_completed_event, so do not set it on
        # exception paths.
        if _bootstrap_complete_flag.is_set():
            _bootstrap_completed_event.set()


def main():
    """Main entry point for NIJA trading bot - Railway optimized"""
    _emit_boot_trace("BOOT 1", "main() entered")
    # ── ENTRY POINT TRACE ────────────────────────────────────────────────────
    # Log the call stack immediately so we can confirm which code path reached
    # main() and whether it was called from __main__, runpy, or elsewhere.
    _log_startup_trace("main() entry")
    logger.info(
        "DIAG_MAIN_ENTRY: main() called in bot.py "
        "pid=%d thread=%s thread_id=%d "
        "__name__=%r __file__=%r",
        os.getpid(),
        threading.current_thread().name,
        threading.get_ident(),
        __name__,
        __file__,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # CRITICAL: BOOTSTRAP GUARD — Prevent duplicate instances
    # ═══════════════════════════════════════════════════════════════════════
    # Hard-stop if another bot instance is already running.
    # This runs FIRST before any other initialization.
    if _BOOTSTRAP_GUARD_AVAILABLE and _acquire_bootstrap_guard:
        _acquire_bootstrap_guard()  # 💥 HARD STOP if duplicated
    
    logger.info("🧭 Main startup path entered")

    # ═══════════════════════════════════════════════════════════════════════
    # CRITICAL: START HEALTH SERVER FIRST (Railway requirement)
    # ═══════════════════════════════════════════════════════════════════════
    # Health server MUST bind BEFORE:
    # - Kraken connections
    # - User loading  
    # - Any sleeps or loops
    # - Even logging setup
    #
    # This prevents Railway from killing the container during startup.
    # The /health endpoint ALWAYS returns 200 OK regardless of bot state.
    logger.info("=" * 70)
    logger.info("🌐 Starting health server (Railway requirement)")
    logger.info("=" * 70)
    _start_health_server()
    logger.info("✅ Health server started - Railway will not kill this container")
    logger.info("=" * 70)
    logger.info("")
    _emit_boot_trace("BOOT 2", "health server started")

    # Advance bootstrap FSM: BOOT_INIT → LOCK_ACQUIRED → HEALTH_BOUND
    # (process lock was acquired at module import; health server is now bound)
    # Guard transitions so re-entrant starts do not attempt illegal backward moves.
    if _BOOTSTRAP_FSM_AVAILABLE:
        try:
            _bfsm_current = _get_bootstrap_fsm().state
            if _bfsm_current == _BootstrapState.BOOT_INIT:
                _bfsm_transition(_BootstrapState.LOCK_ACQUIRED, "process lock acquired at module load")
                _bfsm_transition(_BootstrapState.HEALTH_BOUND, "health server bound")
            elif _bfsm_current == _BootstrapState.LOCK_ACQUIRED:
                _bfsm_transition(_BootstrapState.HEALTH_BOUND, "health server bound")
            else:
                logger.info(
                    "[BootstrapFSM] Startup pre-health transitions already satisfied (state=%s)",
                    getattr(_bfsm_current, "value", _bfsm_current),
                )
        except Exception as _bfsm_state_err:
            logger.debug("[BootstrapFSM] startup transition guard skipped: %s", _bfsm_state_err)

    # Small delay to ensure health server is fully bound
    time.sleep(0.2)

    # ═══════════════════════════════════════════════════════════════════════
    # SYNCHRONOUS PRE-FLIGHT CHECK — runs here, not in a thread, not behind
    # any conditional logic.  This is the first thing that executes after the
    # health server binds.  If every check passes the bot proceeds to start
    # trading.  If any critical requirement is missing the bot prints exactly
    # what is wrong and exits immediately.
    # ═══════════════════════════════════════════════════════════════════════
    _emit_boot_trace("BOOT 3", "running synchronous preflight checks")
    if not _run_preflight_check():
        _release_process_lock()
        sys.exit(1)
    _emit_boot_trace("BOOT 4", "preflight passed; launching startup pipeline")

    # Now setup logging (after health server is running)
    # Log process startup
    _log_lifecycle_banner(
        "🚀 NIJA TRADING BOT STARTUP",
        [
            f"Process ID: {os.getpid()}",
            f"Python Version: {sys.version.split()[0]}",
            f"Working Directory: {os.getcwd()}",
            "Health server: ✅ RUNNING (started before initialization)",
            "Initializing lifecycle management..."
        ]
    )
    
    # Log memory usage at startup (lightweight - single line)
    _log_memory_usage()
    
    # Graceful shutdown handlers to avoid non-zero exits on platform terminations
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    logger.info("✅ Signal handlers registered (SIGTERM, SIGINT)")

    # Initialize health check manager early
    from bot.health_check import get_health_manager
    health_manager = get_health_manager()
    logger.info("✅ Health check manager initialized")

    _writer_lock_status = {}
    try:
        try:
            from bot.execution_authority_context import get_distributed_writer_authority_status
        except ImportError:
            from execution_authority_context import get_distributed_writer_authority_status  # type: ignore[import]

        _writer_lock_status = get_distributed_writer_authority_status(force_refresh=True)
        logger.info(
            "🔐 WRITER LOCK SELF-TEST | ok=%s strict_required=%s effective_strict_required=%s "
            "degraded_override=%s unsafe_bypass=%s live_mode=%s redis_configured=%s token_present=%s",
            _writer_lock_status.get("ok"),
            _writer_lock_status.get("strict_required"),
            _writer_lock_status.get("effective_strict_required"),
            _writer_lock_status.get("degraded_override_enabled"),
            _writer_lock_status.get("unsafe_bypass_enabled"),
            _writer_lock_status.get("live_mode"),
            _writer_lock_status.get("redis_configured"),
            _writer_lock_status.get("token_present"),
        )
        _holder_inspection = _writer_lock_status.get("holder_inspection") or {}
        _current_holder = (_writer_lock_status.get("current_holder") or {}).get("display", "<unknown>")
        logger.info(
            "🔐 WRITER LOCK HOLDER | relationship=%s holder=%s",
            _holder_inspection.get("relationship", "unknown"),
            _current_holder,
        )
        if _writer_lock_status.get("error"):
            logger.error("🔐 WRITER LOCK SELF-TEST ERROR: %s", _writer_lock_status.get("error"))
    except Exception as _writer_lock_status_err:
        logger.warning("⚠️ Writer lock self-test unavailable: %s", _writer_lock_status_err)

    _runtime_role = os.getenv("NIJA_RUNTIME_ROLE", "").strip() or (
        "writer" if bool(_writer_lock_status.get("ok")) else "observer"
    )
    logger.info(
        "DIAG_RUNTIME_ROLE: runtime_role=%s writer_lock_ok=%s strict_required=%s holder_relationship=%s",
        _runtime_role,
        _writer_lock_status.get("ok"),
        _writer_lock_status.get("strict_required"),
        (_writer_lock_status.get("holder_inspection") or {}).get("relationship", "unknown"),
    )
    
    # Start dedicated heartbeat thread for Railway health checks
    # This ensures heartbeat is updated frequently (every 10 seconds)
    # regardless of trading loop timing (150 seconds)
    # Critical for Railway health check responsiveness (~30 second intervals)
    def heartbeat_worker():
        """Background thread that updates heartbeat at regular intervals"""
        thread_id = threading.get_ident()
        logger.info(f"🧵 Heartbeat thread started (ID: {thread_id}, Interval: {HEARTBEAT_INTERVAL_SECONDS}s)")
        
        heartbeat_count = 0
        while True:
            try:
                health_manager.heartbeat()
                heartbeat_count += 1
                
                # Log every 60 heartbeats (10 minutes at 10s interval) for visibility
                if heartbeat_count % 60 == 0:
                    logger.debug(f"🧵 Heartbeat thread alive - {heartbeat_count} heartbeats sent")
                
                time.sleep(HEARTBEAT_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"🧵 ❌ Error in heartbeat worker thread (ID: {thread_id}): {e}", exc_info=True)
                time.sleep(HEARTBEAT_INTERVAL_SECONDS)
    
    heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True, name="HeartbeatWorker")
    heartbeat_thread.start()
    
    # Wait briefly to ensure thread actually starts
    time.sleep(0.1)
    
    _log_lifecycle_banner(
        "✅ BACKGROUND THREADS STARTED",
        [
            f"HeartbeatWorker: Thread ID {heartbeat_thread.ident}",
            f"Update Interval: {HEARTBEAT_INTERVAL_SECONDS} seconds",
            f"Thread is alive: {heartbeat_thread.is_alive()}",
            "Health checks will be responsive to Railway (~30s check interval)"
        ]
    )

    # ═══════════════════════════════════════════════════════════════════════
    # RAILWAY PATTERN: Spawn startup thread, main thread supervises
    # ═══════════════════════════════════════════════════════════════════════
    # Main thread stays in idle loop to keep health server responsive
    # Startup thread handles all bot initialization:
    # - Kraken connection
    # - User loading
    # - Balance fetching
    # - Trading loop
    
    _reset_startup_events_for_fresh_attempt(clear_initialized_state=True)

    logger.info("=" * 70)
    logger.info("🚀 SPAWNING STARTUP THREAD")
    logger.info("=" * 70)
    logger.info("Main thread will supervise while startup thread initializes bot")
    logger.info("Health server remains responsive during initialization")
    logger.info("=" * 70)
    
    logger.info("Step 4: initializing broker and spawning startup thread")
    logger.info(
        "DIAG_THREAD_SPAWN: spawning BotStartup thread "
        "target=_run_bot_startup_and_trading_with_retry "
        "pid=%d caller_thread=%s caller_thread_id=%d",
        os.getpid(),
        threading.current_thread().name,
        threading.get_ident(),
    )
    startup_thread = threading.Thread(
        target=_run_bot_startup_and_trading_with_retry,  # single-owner kernel, always with retry
        daemon=False,  # NOT daemon - we want this to keep running
        name="BotStartup"
    )
    startup_thread.start()
    logger.info(
        "DIAG_THREAD_SPAWNED: BotStartup thread started "
        "thread_id=%s thread_alive=%s",
        startup_thread.ident,
        startup_thread.is_alive(),
    )
    
    # Wait briefly to ensure thread starts
    time.sleep(0.2)
    
    _log_lifecycle_banner(
        "✅ STARTUP THREAD SPAWNED",
        [
            f"BotStartup: Thread ID {startup_thread.ident}",
            f"Thread is alive: {startup_thread.is_alive()}",
            "Bot initialization is now running in background",
            "Main thread entering supervisor mode..."
        ]
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # SUPERVISOR LOOP - Main thread stays here forever
    # ═══════════════════════════════════════════════════════════════════════
    # This keeps the process alive and health server responsive
    # while the startup thread does all the work
    
    _log_lifecycle_banner(
        "🔒 ENTERING SUPERVISOR MODE (observer-only)",
        [
            "Main thread observes background threads — does NOT restart them",
            "Bootstrap kernel (BotStartup) owns all retry logic internally",
            "Health server: ✅ Running (always responds to Railway)",
            "Heartbeat thread: ✅ Running (updates every 10s)",
            "Startup thread: ✅ Running (bootstrap kernel active)",
            f"Status logging every {KEEP_ALIVE_SLEEP_INTERVAL_SECONDS}s",
            "To shutdown: Use SIGTERM or SIGINT (handled by signal handlers)"
        ]
    )
    
    # ── BOOTSTRAP OBSERVER BARRIER ────────────────────────────────────────────
    # Single authoritative wait: main thread observes BootstrapFSM progression
    # with a bounded timeout and explicit failure state handling.
    logger.info("🧭 Before bootstrap observer wait")
    if _is_truthy_env("FORCE_TRADE") or _is_truthy_env("FORCE_TRADE_MODE"):
        logger.warning("FORCE_TRADE active — startup readiness barrier remains enforced")

    # READINESS DEBUG: snapshot flag state immediately before entering the
    # system_ready wait loop so the log shows which subsystem is blocked even
    # on the very first poll.
    try:
        _pre_snap = _read_initialized_state_snapshot(context="pre-system-ready-wait debug")
        _pre_ready_tuple = _compute_system_ready(_pre_snap)
        # _pre_ready_tuple: (system_ready, broker, risk, strategy, capital, execution)
        _dbg_broker   = _pre_ready_tuple[1]
        _dbg_risk     = _pre_ready_tuple[2]
        _dbg_strategy = _pre_ready_tuple[3]
        _dbg_capital  = _pre_ready_tuple[4]
        _dbg_exec     = _pre_ready_tuple[5]
        logger.info(
            "READINESS DEBUG | broker=%s risk=%s strategy=%s capital=%s execution=%s",
            _dbg_broker,
            _dbg_risk,
            _dbg_strategy,
            _dbg_capital,
            _dbg_exec,
        )
    except Exception as _pre_snap_err:
        logger.debug("READINESS DEBUG snapshot failed (non-fatal): %s", _pre_snap_err)

    strategy = None
    _observer_ok, _observer_state = _wait_for_bootstrap_observer_ready(
        context="main startup observer wait",
    )
    if not _observer_ok:
        dump_startup_state("BOOTSTRAP_OBSERVER_FAILED")
        raise RuntimeError(
            f"Startup blocked: bootstrap observer timed out/failed (state={_observer_state})"
        )
    _state_snapshot = _read_initialized_state_snapshot(context="supervisor system_ready probe")
    strategy = _state_snapshot.get("strategy")
    system_ready, broker_ready, risk_ready, strategy_ready, capital_ready, execution_ready = \
        _compute_system_ready(_state_snapshot)
    logger.info(
        "✅ BOOTSTRAP OBSERVER READY: state=%s broker_ready=%s risk_ready=%s strategy_ready=%s "
        "capital_ready=%s execution_ready=%s",
        _observer_state,
        broker_ready,
        risk_ready,
        strategy_ready,
        capital_ready,
        execution_ready,
    )

    # ── HARD GUARD: never enter trading loop without a valid strategy ─────────
    if strategy is None:
        logger.warning(
            "⏳ strategy not yet initialized; waiting until startup thread publishes strategy"
        )
        _last_strategy_wait_log = 0.0
        _strategy_wait_started = time.monotonic()
        _strategy_wait_deadline = _strategy_wait_started + _STRATEGY_PUBLICATION_TIMEOUT_S
        _fallback_attempted = False
        while strategy is None:
            _state_snapshot = _read_initialized_state_snapshot(context="degraded_strategy_wait")
            strategy = _state_snapshot.get("strategy")
            if strategy is not None:
                logger.info("✅ strategy became available - continuing startup")
                break

            _now = time.monotonic()
            if _now >= _strategy_wait_deadline:
                # ── DEGRADED-MODE FALLBACK ────────────────────────────────────
                # Strategy publication timed out — most commonly caused by Redis
                # SSL connection failures blocking the distributed writer lock.
                # When degraded mode is permitted (NIJA_ASSUME_SINGLE_INSTANCE
                # or explicit unsafe/local fallback flags), attempt one final fallback
                # strategy construction and proceed in local-only mode rather
                # than crashing the process.
                _degraded_allowed = (
                    os.environ.get("NIJA_ASSUME_SINGLE_INSTANCE", "").strip().lower() in _TRUTHY_ENV_VALUES
                    or os.environ.get("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", "").strip().lower() in _TRUTHY_ENV_VALUES
                    or os.environ.get("NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK", "").strip().lower() in _TRUTHY_ENV_VALUES
                )
                if _degraded_allowed:
                    logger.warning(
                        "⚠️  Strategy publication timed out after %.1fs — "
                        "proceeding in local-only mode (Redis unavailable). "
                        "Distributed locking remains strictly enforced where required.",
                        _STRATEGY_PUBLICATION_TIMEOUT_S,
                    )
                    # One final attempt to construct a fallback strategy before
                    # entering the trading loop without a published strategy.
                    if not _fallback_attempted:
                        _ensure_strategy_fallback_published(
                            context="supervisor degraded timeout fallback"
                        )
                        _state_snapshot = _read_initialized_state_snapshot(
                            context="degraded_timeout_fallback"
                        )
                        strategy = _state_snapshot.get("strategy")
                    if strategy is not None:
                        logger.warning(
                            "✅ Degraded fallback strategy constructed — entering trading loop "
                            "in local-only mode (no distributed lock)"
                        )
                        break
                    # Strategy construction also failed — log and break out so
                    # the trading loop can handle a None strategy gracefully
                    # rather than blocking the process indefinitely.
                    logger.error(
                        "❌ Degraded fallback strategy construction failed — "
                        "entering trading loop with no strategy object. "
                        "Bot will operate in safe/no-trade mode until strategy recovers."
                    )
                    break
                raise RuntimeError(
                    "Startup blocked: strategy publication timed out after bootstrap observer readiness"
                )
            if (
                not _fallback_attempted
                and (_now - _strategy_wait_started) >= _STRATEGY_FALLBACK_GRACE_PERIOD_S
            ):
                _fallback_attempted = True
                _ensure_strategy_fallback_published(context="supervisor degraded strategy wait")
                _state_snapshot = _read_initialized_state_snapshot(context="degraded_strategy_wait_post_fallback")
                strategy = _state_snapshot.get("strategy")
                if strategy is not None:
                    logger.info("✅ strategy fallback published - continuing startup")
                    break

            if _now - _last_strategy_wait_log >= 60.0:
                logger.warning(
                    "⏳ still waiting for strategy publication (process stays alive; health server remains ready)"
                )
                _last_strategy_wait_log = _now
            time.sleep(2.0)

    logger.info("🚀 Entering main trading loop")
    logger.info("Step 6: entering main trading loop")
    from bot.nija_core_loop import start_trading_engine
    logger.info("STRATEGY_LOOP_ENTRY marker=main_supervisor_handoff")
    _trading_thread = start_trading_engine(strategy)
    if _trading_thread is None or not _trading_thread.is_alive():
        raise RuntimeError("TradingLoop thread failed to start")
    logger.info("✅ TradingLoop started via start_trading_engine()")

    _trading_loop_alive = any(
        _t.name == "TradingLoop" and _t.is_alive() for _t in threading.enumerate()
    )
    logger.info(
        "SUPERVISOR ENTRY ASSERT: live_active=%s tradingloop_alive=%s strategy_present=%s",
        _is_live_trading_active_now(),
        _trading_loop_alive,
        strategy is not None,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # ✅ STARTUP COMPLETION - PRINT DISTINCTIVE MARKER
    # ═══════════════════════════════════════════════════════════════════════
    # This message marks that the bot is FULLY INITIALIZED and entering
    # the main supervised loop. Critical for:
    # - Railway startup detection (can detect hard exits after this marker)
    # - Operator visibility (when is the bot ready?)
    # - Debugging (can distinguish startup phase from live trading phase)
    # ═══════════════════════════════════════════════════════════════════════
    logger.info("\n" + "=" * 70)
    logger.info("🚀 Bot fully started - entering main loop")
    logger.info("=" * 70)
    logger.info("✅ All bootstrap phases complete")
    logger.info("✅ Health server responsive")
    logger.info("✅ Trading engine initialized")
    logger.info("✅ Supervisor loop ready to manage threads")
    logger.info("=" * 70 + "\n")

    logger.info("🧠 Entering supervisor loop")
    supervisor_cycle = 0
    _bootstrap_handoff_logged = False  # Log the bootstrap hand-off message only once
    while True:
        try:
            supervisor_cycle += 1

            restart_reason = _consume_external_watchdog_restart_reason()
            if restart_reason:
                # Bootstrap FSM: fatal condition requiring external restart
                _bfsm_transition(
                    _BootstrapState.EXTERNAL_RESTART_REQUIRED,
                    f"external watchdog restart: {restart_reason}",
                )
                _bfsm_transition(_BootstrapState.SHUTDOWN, "process exiting for external restart")
                _log_exit_point(
                    "External Watchdog Restart Requested",
                    exit_code=1,
                    details=[
                        "Fatal nonce condition requires clean external restart",
                        f"Reason: {restart_reason}",
                        *_get_thread_status(),
                    ],
                )
                raise RuntimeError(f"External watchdog restart requested: {restart_reason}")

            # Observer-only: BotStartup owns its own retry loop via the single-
            # owner kernel.  If the thread exits it means the kernel itself
            # terminated.  We distinguish two cases:
            #
            #   BOOTSTRAP_COMPLETE  – _bootstrap_complete_flag is set, meaning
            #     the bot reached RUNNING_SUPERVISED and handed control to the
            #     trader threads.  The thread exiting here is expected; the outer
            #     supervisor keeps the process alive so those threads continue.
            #
            #   BOOTSTRAP_FAILED    – _bootstrap_complete_flag is NOT set,
            #     meaning startup never succeeded.  Exit so an external watchdog
            #     (Railway / Docker / systemd) can restart with a clean slate.
            # Distinguish between successful bootstrap completion and bootstrap failure.
            # Thread lifecycle is independent of system lifecycle: trader threads
            # continue running after the bootstrap thread hands off control.
            #
            #   Bootstrap completed (_bootstrap_completed_event set):
            #     Trader threads are live and running independently.  Keep the
            #     process alive so the health server and trader threads can operate.
            #
            #   Bootstrap failed (_bootstrap_completed_event not set):
            #     The kernel exited before any trader threads were started.
            #     Exit so an external watchdog (Railway, systemd, Docker) can
            #     restart the process with a clean slate.
            if not startup_thread.is_alive():
                if _bootstrap_completed_event.is_set():
                    # Bootstrap completed — the thread handed off to the supervisor.
                    # Log this transition only once to avoid filling logs each cycle.
                    if not _bootstrap_handoff_logged:
                        logger.info(
                            "✅ [Supervisor] Bootstrap kernel (BotStartup) thread exited after "
                            "successful bootstrap (RUNNING_SUPERVISED reached). "
                            "Handing control to supervisor loop — system continues operating. "
                            "Trader threads remain active."
                        )
                        _bootstrap_handoff_logged = True
                    continue  # DO NOT SHUTDOWN — keep the process alive
                else:
                    # Bootstrap failed: kernel exited before completing.
                    _startup_err = _get_startup_last_error()
                    logger.critical(
                        "💥 [Supervisor] Bootstrap kernel (BotStartup) thread exited before "
                        "bootstrap completed (RUNNING_SUPERVISED never reached) — "
                        "terminating process so an external process manager (Railway, systemd, "
                        "Docker restart policy) can restart with a clean state. "
                        "If no external watchdog is configured the process will stay stopped."
                    )
                    if _startup_err:
                        logger.error(
                            "💥 [Supervisor] Last startup error before thread exit: %s",
                            _startup_err,
                        )
                    if _BOOTSTRAP_FSM_AVAILABLE:
                        _bfsm_transition(
                            _BootstrapState.SHUTDOWN,
                            "bootstrap kernel thread exited before completing bootstrap",
                        )
                    _release_process_lock()
                    sys.exit(1)
            
            # Log periodic status
            if supervisor_cycle % 12 == 0:  # Every hour at 300s intervals
                logger.info(f"💓 Supervisor status check #{supervisor_cycle // 12}")
                logger.info("🧵 Thread Status Report:")
                logger.info(f"   Health server: ✅ Running")
                logger.info(f"   Heartbeat thread: {'✅ Alive' if heartbeat_thread.is_alive() else '❌ Dead'}")
                logger.info(f"   Startup thread: {'✅ Alive' if startup_thread.is_alive() else '❌ Dead'}")
                for status_line in _get_thread_status():
                    logger.info(f"   {status_line}")
            
            time.sleep(KEEP_ALIVE_SLEEP_INTERVAL_SECONDS)
            
        except KeyboardInterrupt:
            _log_lifecycle_banner(
                "⚠️  SUPERVISOR INTERRUPTED",
                [
                    "KeyboardInterrupt received in supervisor loop",
                    "Shutting down gracefully...",
                    *_get_thread_status()
                ]
            )
            logger.info("Waiting for startup thread to finish...")
            startup_thread.join(timeout=10)
            break
        except RuntimeError as e:
            if "External watchdog restart requested:" in str(e):
                logger.warning("Exiting main supervisor for external watchdog restart")
                raise
            logger.error(f"❌ RuntimeError in supervisor loop: {e}", exc_info=True)
            logger.warning("Recovering from supervisor loop runtime error...")
            time.sleep(10)
        except Exception as e:
            logger.error(f"❌ Error in supervisor loop: {e}", exc_info=True)
            logger.warning("Recovering from supervisor loop error...")
            time.sleep(10)
    
    logger.info("✅ Main supervisor exiting gracefully")
    sys.exit(0)


# ── MODULE-LEVEL MAIN() CALL ──────────────────────────────────────────────────
# Call main() unconditionally at module level so the bot starts whether bot.py
# is executed directly (python bot.py), via runpy.run_path(), or any other
# loader that does not set __name__ == "__main__".
# The if __name__ == "__main__" guard below is kept for compatibility but the
# authoritative entry point is this unconditional call.
print(
    "DIAG_MODULE_LEVEL_MAIN: calling main() at module level "
    f"pid={os.getpid()} __name__={__name__!r}",
    flush=True,
)
logger.info(
    "MODULE_LEVEL_MAIN: calling main() at module level pid=%d __name__=%r",
    os.getpid(),
    __name__,
)
try:
    main()
except Exception as _module_main_exc:
    traceback.print_exc()
    logger.critical("💥 FATAL ERROR — BOT CRASHED (module-level main): %s", _module_main_exc, exc_info=True)
    sys.exit(1)


if __name__ == "__main__":
    # ── ENTRY POINT DIAGNOSTICS ───────────────────────────────────────────────
    # These fire immediately when bot.py is executed as __main__ (via runpy or
    # direct invocation).  They confirm which code path reached this block and
    # capture the full call stack so we can trace the actual entry point.
    print(
        f"DIAG_BOT_DUNDER_MAIN: bot.py __name__=='__main__' block executing "
        f"pid={os.getpid()} "
        f"python={sys.version.split()[0]} "
        f"thread={threading.current_thread().name} "
        f"thread_id={threading.get_ident()} "
        f"__file__={__file__!r}",
        flush=True,
    )
    import traceback as _entry_tb
    _entry_stack = "".join(_entry_tb.format_stack()).strip()
    print(
        f"DIAG_BOT_DUNDER_MAIN_STACK: call stack at __main__ entry:\n{_entry_stack}",
        flush=True,
    )
    print(
        f"DIAG_BOT_DUNDER_MAIN_THREADS: active threads at __main__ entry: "
        + ", ".join(
            f"{t.name}(id={t.ident},daemon={t.daemon})"
            for t in threading.enumerate()
        ),
        flush=True,
    )
    # NOTE: main() was already called unconditionally at module level above.
    # This block is retained for compatibility but main() is NOT called again
    # here to prevent a double-invocation when __name__ == "__main__".
    print(
        "DIAG_BOT_DUNDER_MAIN: __main__ block reached but main() already called "
        "at module level — skipping duplicate invocation",
        flush=True,
    )
    logger.info(
        "DUNDER_MAIN_BLOCK: __name__=='__main__' block reached; "
        "main() was already invoked at module level — no duplicate call needed"
    )
