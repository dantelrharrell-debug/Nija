"""
NIJA Core Loop  (rebuilt)
=========================

Single-pass, clean trading loop that coordinates:

    Phase 1 — Safety Gate
        Drawdown circuit breaker + daily loss limit check.
        Returns (can_trade: bool, balance: float).

    Phase 2 — Position Management
        For every open position: check exits, update trailing stops.
        Operates even when entries are blocked.

    Phase 3 — Market Scan & Ranked Entry
        Score every candidate symbol via NijaAIEngine.
        Rank all candidates.
        Take the top-N that fit open position slots.
        Executes with correct size multiplier per score tier.

Design goals
------------
- **Never stalls** — rank-first selection guarantees entries are found
  even in low-signal markets (adaptive threshold drops to floor)
- **Single responsibility per phase** — safety, management, entry are
  fully separated; safety never bleeds into entry logic
- **Cycle speed adapts** — NijaAIEngine.speed_ctrl records signal density
  each cycle; the loop caller reads ``next_interval`` to sleep appropriately
- **Drop-in** — ``NijaCoreLoop`` wraps the existing ``NIJAApexStrategyV71``
  and ``TradingStrategy`` objects; no existing logic is deleted

Usage
-----
In ``TradingStrategy.run_cycle`` (after the existing safety-gate block)::

    if NIJA_CORE_LOOP_AVAILABLE and hasattr(self, 'nija_core_loop'):
        result = self.nija_core_loop.run_scan_phase(
            broker=active_broker,
            balance=account_balance,
            symbols=symbols_to_scan,
            open_positions_count=self.open_positions_count,
        )
        # result.next_interval is the recommended sleep time in seconds

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import queue
import time
import threading
import types as _types
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.core_loop")

try:
    from bot.log_rate_limiter import get_log_rate_limiter
except ImportError:
    from log_rate_limiter import get_log_rate_limiter  # type: ignore[import]

try:
    from bot.runtime_contract import assert_runtime_contract_release_ready
except ImportError:
    from runtime_contract import assert_runtime_contract_release_ready  # type: ignore[import]

try:
    from bot.runtime_correlation import (
        clear_runtime_correlation,
        update_runtime_correlation,
    )
except ImportError:
    try:
        from runtime_correlation import clear_runtime_correlation, update_runtime_correlation  # type: ignore[import]
    except ImportError:
        def update_runtime_correlation(**fields):  # type: ignore[no-redef]
            return {}

        def clear_runtime_correlation() -> None:  # type: ignore[no-redef]
            return None

_CORE_LOOP_LOG_LIMITER = get_log_rate_limiter()


def _extract_cached_balance_for_log(broker: Any) -> float:
    """Return a broker balance for diagnostics without making exchange API calls."""
    for attr in ("_last_known_balance", "last_known_balance", "cached_balance", "last_balance"):
        if hasattr(broker, attr):
            value = getattr(broker, attr, None)
            try:
                return float(value or 0.0)
            except (TypeError, ValueError):
                pass

    cache = getattr(broker, "balance_cache", None)
    if isinstance(cache, Mapping):
        for key in ("total_balance", "balance", "usd_balance", "equity", "total_usd", "available_usd"):
            if key in cache:
                try:
                    return float(cache.get(key) or 0.0)
                except (TypeError, ValueError):
                    return 0.0
        for value in cache.values():
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, Mapping):
                for key in ("total_balance", "balance", "usd_balance", "equity", "total_usd", "available_usd"):
                    if key in value:
                        try:
                            return float(value.get(key) or 0.0)
                        except (TypeError, ValueError):
                            return 0.0
    return 0.0


def _cached_broker_balances_for_log(broker_manager: Any) -> Dict[str, Dict[str, Any]]:
    """Build a non-blocking broker-balance diagnostic snapshot.

    The live trading loop must never call exchange APIs merely to print a
    diagnostic line.  Coinbase 500s (or any other venue outage) should not sit in
    front of the scanner/execution path, so this helper only inspects in-memory
    broker attributes populated by bootstrap/capital hydration.
    """
    balances: Dict[str, Dict[str, Any]] = {}
    brokers = getattr(broker_manager, "brokers", {}) or {}
    if not isinstance(brokers, Mapping):
        return balances
    for broker_type, broker in brokers.items():
        name = str(getattr(broker_type, "value", broker_type)).strip().lower()
        if broker is None:
            balances[name] = {"balance": 0.0, "connected": False, "source": "missing"}
            continue
        balances[name] = {
            "balance": _extract_cached_balance_for_log(broker),
            "connected": bool(getattr(broker, "connected", False)),
            "source": "cached",
        }
    return balances


def _rate_limited_critical(category: str, key: str, window_seconds: float, message: str, *args: Any) -> None:
    allowed, suppressed = _CORE_LOOP_LOG_LIMITER.allow_with_count(
        category=category,
        key=key,
        window_seconds=window_seconds,
    )
    if not allowed:
        return
    if suppressed:
        logger.info("[quiet-runtime] suppressed=%d category=%s key=%s", suppressed, category, key)
    logger.critical(message, *args)

try:
    from bot.runtime_mode import resolve_runtime_mode_safe, RuntimeModeResolution
except ImportError:
    from runtime_mode import resolve_runtime_mode_safe, RuntimeModeResolution  # type: ignore[import]

try:
    from bot.pipeline_order_submitter import submit_market_order_via_pipeline
except ImportError:
    try:
        from pipeline_order_submitter import submit_market_order_via_pipeline  # type: ignore[import]
    except ImportError:
        submit_market_order_via_pipeline = None  # type: ignore[assignment]

try:
    from bot.graceful_handoff import get_handoff_coordinator as _get_handoff_coordinator
    _GRACEFUL_HANDOFF_AVAILABLE = True
except ImportError:
    _get_handoff_coordinator = None  # type: ignore[assignment]
    _GRACEFUL_HANDOFF_AVAILABLE = False


def _is_live_mode(existing_mode: Optional[RuntimeModeResolution] = None) -> bool:
    runtime_mode = existing_mode or resolve_runtime_mode_safe(logger)
    if runtime_mode is not None:
        return runtime_mode.is_live
    return os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower() in ("true", "1", "yes", "enabled")


def _env_truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes", "enabled", "on")


def _watchdog_backoff_delay(base_s: float, retries: int, enabled: bool, max_multiplier: float) -> float:
    if not enabled:
        return max(0.0, float(base_s))
    safe_base = max(0.0, float(base_s))
    safe_retries = max(0, int(retries))
    capped_multiplier = max(1.0, float(max_multiplier))
    multiplier = min(capped_multiplier, float(2 ** min(safe_retries, 10)))
    return safe_base * multiplier


# ---------------------------------------------------------------------------
# CycleSnapshot — immutable state captured once per activation tick
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CycleSnapshot:
    """Immutable snapshot of volatile apex state captured once per cycle.

    All gates receive a reference to the *same* snapshot instance, so every
    check sees an identical, consistent view of the world regardless of how
    long the cycle takes or whether background threads mutate the underlying
    apex attributes mid-scan.

    Fields
    ------
    balance           : Account equity (USD) as of cycle start.
    current_regime    : Market regime string (e.g. "bull", "bear", "ranging").
    daily_pnl_usd     : Running daily P&L in USD at cycle start.
    open_positions    : Number of open positions at cycle start (pre-exits).
    cycle_id          : Unique identifier for this cycle (ISO-format timestamp +
                        counter).  Shared across TradingStateMachine,
                        CapitalAllocationBrain, and MABM so every sub-system
                        decision within a single cycle is traceable to the same
                        frozen world-view.
    ca_is_hydrated    : CapitalAuthority.is_hydrated at cycle-start capture time.
    ca_total_capital  : CapitalAuthority.total_capital at cycle-start capture time.
    ca_valid_brokers  : Number of valid brokers reported by CA at capture time.
    mabm_brokers_ready: True when all registered platform brokers were fully ready
                        (connected + balance payload hydrated) at capture time.
    """
    balance: float
    current_regime: Optional[str]
    daily_pnl_usd: float
    open_positions: int
    # --- shared-snapshot hardening fields (default to safe/falsy values so
    # existing call-sites that build CycleSnapshot without them still work) ---
    cycle_id: str = ""
    ca_is_hydrated: bool = False
    ca_total_capital: float = 0.0
    ca_valid_brokers: int = 0
    mabm_brokers_ready: bool = False
    # True when the capital snapshot was captured after CAPITAL_HYDRATED_EVENT
    # fired AND ca_is_hydrated is confirmed — prevents stale pre-hydration
    # data from satisfying the activation gate.
    is_post_hydration: bool = False
    # Capital snapshot lineage metadata propagated from _capture_cycle_capital_state().
    snapshot_source: str = "placeholder"
    aggregation_normalized: bool = True

# ---------------------------------------------------------------------------
# Trading state machine + CapitalAuthority — optional; graceful fallback
# ---------------------------------------------------------------------------
try:
    from trading_state_machine import get_state_machine as _get_state_machine, TradingState as _TradingState
    _SM_AVAILABLE = True
except ImportError:
    try:
        from bot.trading_state_machine import get_state_machine as _get_state_machine, TradingState as _TradingState  # type: ignore[import]
        _SM_AVAILABLE = True
    except ImportError:
        _get_state_machine = None  # type: ignore[assignment]
        _TradingState = None  # type: ignore[assignment]
        _SM_AVAILABLE = False

try:
    from capital_authority import (  # type: ignore[import]
        get_capital_authority as _get_ca,
        CAPITAL_HYDRATED_EVENT as _CAPITAL_HYDRATED_EVENT,
    )
    _CA_LOOP_AVAILABLE = True
except ImportError:
    try:
        from bot.capital_authority import (  # type: ignore[import]
            get_capital_authority as _get_ca,
            CAPITAL_HYDRATED_EVENT as _CAPITAL_HYDRATED_EVENT,
        )
        _CA_LOOP_AVAILABLE = True
    except ImportError:
        _get_ca = None  # type: ignore[assignment]
        _CAPITAL_HYDRATED_EVENT = None  # type: ignore[assignment]
        _CA_LOOP_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shared-cycle context — frozen capital snapshot captured ONCE per cycle
# ---------------------------------------------------------------------------
# These module-level variables are written once at the START of each trading
# cycle (in run_trading_loop) — BEFORE _supervisor_step_state_machine() or
# strategy.run_cycle() run — and read by TradingStateMachine,
# CapitalAllocationBrain, and MABM so they all see an identical world-view.
#
# Lifecycle
# ---------
# 1. ``run_trading_loop()``  — clears ``_current_cycle_snapshot`` to ``None``,
#    generates ``_current_cycle_id``, calls ``_capture_cycle_capital_state()``
#    which fills ``_current_cycle_capital``.
# 2. ``_supervisor_step_state_machine()`` — reads ``_current_cycle_capital``
#    (snapshot not yet built; CycleSnapshot is constructed later).
# 3. ``run_scan_phase()`` — builds the immutable ``CycleSnapshot`` incorporating
#    capital fields from ``_current_cycle_capital`` and publishes it to
#    ``_current_cycle_snapshot`` so downstream callers can access it.
# 4. ``get_current_cycle_snapshot()`` — returns ``_current_cycle_snapshot``
#    (``None`` during phases 1-2 above; a valid snapshot from phase 3 onward).
#
# ``cycle_id`` uses an empty string default (not ``None``) so it can be safely
# logged with ``%s`` without a ``None`` guard, and compared with ``if not cid``.

_current_cycle_id: str = ""
_current_cycle_capital: Mapping[str, Any] = {}
_current_cycle_snapshot: Optional["CycleSnapshot"] = None

# ---------------------------------------------------------------------------
# Session-level data-failure quarantine.
# Symbols that repeatedly fail OHLC fetches (data_insufficient + timeout) are
# quarantined for the session so they do not waste scan time on every cycle.
# Key: (broker_name, symbol)   Value: consecutive failure count
# ---------------------------------------------------------------------------
_DATA_FAILURE_QUARANTINE: Dict[str, int] = {}
_DATA_FAILURE_QUARANTINE_LOCK = threading.Lock()
# Quarantine a symbol after this many consecutive data failures in a session.
# Default lowered from 5 → 3 so unsupported/illiquid symbols are excluded
# faster, reducing scan time wasted on dead pairs.
_DATA_FAILURE_QUARANTINE_THRESHOLD = int(
    os.environ.get("NIJA_DATA_FAILURE_QUARANTINE_THRESHOLD", "3")
)

# ---------------------------------------------------------------------------
# Start-signal gate — defined here (before any function that references it)
# so the name is always in module scope when _supervisor_step_state_machine()
# runs, regardless of call order.
# Emitted exactly once by bot.py when BootstrapFSM reaches RUNNING_SUPERVISED.
# ---------------------------------------------------------------------------
TRADING_ENGINE_READY = threading.Event()


def get_current_cycle_snapshot() -> Optional["CycleSnapshot"]:
    """Return the frozen CycleSnapshot for the currently-executing cycle.

    Returns ``None`` when called outside of an active run_scan_phase call or
    when the snapshot has not yet been constructed (e.g. during
    _supervisor_step_state_machine which runs before run_scan_phase).

    External callers (CapitalAllocationBrain, MABM helpers) use this to avoid
    duplicate CA / broker reads within a single cycle.
    """
    return _current_cycle_snapshot


def _capture_cycle_capital_state() -> _types.MappingProxyType:
    """Read CapitalAuthority + MABM broker state exactly ONCE.

    Called at the top of each cycle in run_trading_loop() BEFORE
    _supervisor_step_state_machine() so both the state-machine activation
    check and the subsequent strategy cycle see the same frozen capital view.

    Returns an immutable MappingProxyType with keys:
        ca_is_hydrated        (bool)
        ca_total_capital      (float)
        ca_valid_brokers      (int)
        mabm_brokers_ready    (bool)
        is_post_hydration     (bool)  — True when CAPITAL_HYDRATED_EVENT has fired
                                        AND ca_is_hydrated is confirmed for this cycle
        snapshot_source       (str)  "live_exchange" | "placeholder"
        aggregation_normalized (bool) — True when CA's registered broker count is
                                        consistent with MABM's reported viable broker
                                        count, confirming aggregation pipeline ran
                                        sequentially (FIX 2).
        sync_failed           (bool) — True when any critical subsystem read raised an
                                        unexpected exception during this capture.
                                        Consumers should treat the snapshot as suspect
                                        when this is True.
    """
    result: Dict[str, Any] = {
        "ca_is_hydrated": False,
        "ca_total_capital": 0.0,
        "ca_valid_brokers": 0,
        "mabm_brokers_ready": False,
        "is_post_hydration": False,
        "snapshot_source": "placeholder",
        "aggregation_normalized": True,  # default True (safe: don't block when unknown)
        "sync_failed": False,            # set True below on unexpected read errors
    }

    # ── CapitalAuthority state ────────────────────────────────────────────
    if _CA_LOOP_AVAILABLE and _get_ca is not None:
        try:
            _ca = _get_ca()
            result["ca_is_hydrated"] = bool(_ca.is_hydrated)
            result["ca_total_capital"] = float(getattr(_ca, "total_capital", 0.0) or 0.0)
        except Exception as _ce:
            result["sync_failed"] = True
            logger.warning(
                "_capture_cycle_capital_state: CA read failed — snapshot may be stale: %s", _ce
            )

    # ── is_post_hydration: CAPITAL_HYDRATED_EVENT fired + CA currently hydrated ──
    _hydrated_event_set = (
        _CAPITAL_HYDRATED_EVENT is not None and _CAPITAL_HYDRATED_EVENT.is_set()
    )
    result["is_post_hydration"] = _hydrated_event_set and bool(result["ca_is_hydrated"])

    # ── MABM broker readiness ─────────────────────────────────────────────
    try:
        try:
            from multi_account_broker_manager import (  # type: ignore[import]
                multi_account_broker_manager as _mabm_inst,
            )
        except ImportError:
            from bot.multi_account_broker_manager import (  # type: ignore[import]
                multi_account_broker_manager as _mabm_inst,
            )
        if _mabm_inst is not None and hasattr(_mabm_inst, "all_brokers_fully_ready"):
            result["mabm_brokers_ready"] = bool(_mabm_inst.all_brokers_fully_ready())
        # Derive valid_brokers + snapshot_source from MABM's last authoritative
        # refresh result. Using registered broker count here can drift when some
        # brokers are configured but not yet contributing balances.
        # "_capital_last_valid_brokers" only advances when refresh_capital_authority()
        # confirms viable broker balance payloads.
        _last_vb = int(getattr(_mabm_inst, "_capital_last_valid_brokers", 0) or 0) if _mabm_inst is not None else 0
        # FIX: When _capital_last_valid_brokers is still 0 (coordinator has not
        # yet confirmed viable broker payloads) but CapitalAuthority is already
        # hydrated with real capital, fall back to CA's registered_broker_count.
        # This prevents a startup deadlock where the activation invariant sees
        # valid_brokers=0 and snapshot_source="placeholder" even though both
        # brokers are connected and CA holds a real balance snapshot.
        if _last_vb == 0 and result.get("ca_is_hydrated") and result.get("ca_total_capital", 0.0) > 0.0:
            try:
                if _CA_LOOP_AVAILABLE and _get_ca is not None:
                    _ca_for_vb = _get_ca()
                    _ca_broker_count = int(getattr(_ca_for_vb, "registered_broker_count", 0) or 0)
                    if _ca_broker_count > 0:
                        _last_vb = _ca_broker_count
                        logger.info(
                            "_capture_cycle_capital_state: _capital_last_valid_brokers=0 but "
                            "CA is hydrated (real=$%.2f, brokers=%d) — using CA registered_broker_count "
                            "as valid_brokers fallback",
                            result["ca_total_capital"],
                            _ca_broker_count,
                        )
            except Exception as _ca_vb_err:
                logger.debug(
                    "_capture_cycle_capital_state: CA registered_broker_count fallback failed: %s",
                    _ca_vb_err,
                )
        result["ca_valid_brokers"] = max(result["ca_valid_brokers"], _last_vb)
        result["snapshot_source"] = "live_exchange" if _last_vb > 0 else "placeholder"
    except Exception as _me:
        result["sync_failed"] = True
        logger.warning(
            "_capture_cycle_capital_state: MABM read failed — broker readiness unknown: %s", _me
        )

    # ── FIX 2: Broker aggregation consistency check ───────────────────────
    # Verify that the CA's registered broker count is consistent with the
    # number of viable brokers MABM reports.  When MABM says N viable brokers
    # but CA has M < N registered balance entries, aggregation is still in
    # flight (pipeline is not yet sequential-complete).  Mark this cycle as
    # aggregation_normalized=False so activation is deferred until all broker
    # balances have propagated through to CA.
    #
    # Default is True (not False) intentionally.  This check is *additive*
    # — it only sets False when we can positively confirm a mismatch
    # (MABM says N brokers but CA has fewer).  If the check itself raises an
    # exception (CA or MABM unavailable), failing open (True) is correct:
    # the downstream activation_invariant already has independent hydration,
    # staleness, and broker-readiness gates that will catch the real issue.
    # Failing closed here (False) when modules are absent would permanently
    # block activation on systems that do not use this particular check.
    #
    # Pipeline contract (sequential, NOT parallel):
    #   Broker balances → ActiveCapital aggregation → Tier classification
    #   → ExecutionEngine gating → Strategy loop
    try:
        _ca_registered = 0
        if _CA_LOOP_AVAILABLE and _get_ca is not None:
            try:
                _ca_inst = _get_ca()
                _ca_registered = int(
                    getattr(_ca_inst, "registered_broker_count", 0) or 0
                )
            except Exception:
                pass
        # _last_vb is the number of brokers MABM has confirmed contributed
        # a valid balance payload (set by refresh_capital_authority()).
        # If MABM says viable_brokers > 0 but CA has fewer registered entries,
        # aggregation has not yet propagated — mark as not normalized.
        _expected_for_agg = int(result.get("ca_valid_brokers") or 0)
        _mabm_last_vb = 0
        try:
            # Dual-import pattern follows the established convention in this file
            # (module-level imports at top may not be available at call time).
            try:
                from multi_account_broker_manager import (  # type: ignore[import]
                    multi_account_broker_manager as _mabm_agg,
                )
            except ImportError:
                from bot.multi_account_broker_manager import (  # type: ignore[import]
                    multi_account_broker_manager as _mabm_agg,
                )
            _mabm_last_vb = int(
                getattr(_mabm_agg, "_capital_last_valid_brokers", 0) or 0
            ) if _mabm_agg is not None else 0
        except Exception:
            pass
        _expected_for_agg = max(_expected_for_agg, _mabm_last_vb)
        if _expected_for_agg > 0 and _ca_registered < _expected_for_agg:
            # CA has fewer broker entries than MABM reports — aggregation lag.
            result["aggregation_normalized"] = False
            logger.warning(
                "[PIPELINE] aggregation_normalized=False — MABM reports %d viable brokers "
                "but CA has only %d registered balance entries. Deferring tier classification "
                "until aggregation propagates (sequential pipeline not yet complete).",
                _expected_for_agg,
                _ca_registered,
            )
        else:
            result["aggregation_normalized"] = True
    except Exception as _agg_err:
        logger.debug("_capture_cycle_capital_state: aggregation check failed: %s", _agg_err)
        # Default already True — don't block on unexpected errors in the check itself.

    logger.critical(
        "CYCLE_CAPITAL_SNAPSHOT | ca_hydrated=%s | total=%.8f | valid_brokers=%s | "
        "mabm_ready=%s | source=%s | aggregation_normalized=%s | sync_failed=%s",
        result.get("ca_is_hydrated"),
        float(result.get("ca_total_capital", 0.0) or 0.0),
        result.get("ca_valid_brokers"),
        result.get("mabm_brokers_ready"),
        result.get("snapshot_source"),
        result.get("aggregation_normalized"),
        result.get("sync_failed"),
    )

    # Return an immutable view — callers must not mutate the cycle-capital dict
    # between capture and the end of the cycle.  Use .get() to read values.
    return _types.MappingProxyType(result)


def _supervisor_step_state_machine() -> None:
    """Supervisor activation step for the trading state machine.

    Runs once per loop cycle using the frozen cycle-capital snapshot.
    Attempts deterministic activation while in OFF, then emits clear
    diagnostics when activation remains blocked.
    """
    if not _SM_AVAILABLE or _get_state_machine is None:
        return
    try:
        sm = _get_state_machine()

        # ── HARD BLOCK: nothing runs until activation is committed ────────
        # Once _activation_committed is True the bot is LIVE_ACTIVE and there
        # is no further work for the supervisor to do here.
        if sm.get_activation_committed():
            return

        if sm.get_current_state() not in (
            _TradingState.OFF,
            _TradingState.LIVE_PENDING_CONFIRMATION,
        ):
            return

        _runtime_mode = resolve_runtime_mode_safe(logger)
        _live_verified = _is_live_mode(_runtime_mode)
        _min_balance = float(os.getenv("MINIMUM_TRADING_BALANCE", "50.0") or 50.0)  # $50 minimum for HF scalp mode (Apr 2026)
        _cycle_capital = _current_cycle_capital if _current_cycle_capital else {}
        _balance = float(_cycle_capital.get("ca_total_capital", 0.0) or 0.0)
        _sufficient_balance = _balance >= _min_balance and _balance > 0.0

        # Warn when the snapshot was captured with read errors — activation and
        # balance checks may be operating on incomplete/stale data.
        if bool(_cycle_capital.get("sync_failed", False)):
            logger.warning(
                "[SUPERVISOR] cycle capital snapshot has sync_failed=True — "
                "CA or MABM read error during capture; activation gates may use stale data"
            )

        logger.critical(
            "SUPERVISOR CYCLE CHECK | state=%s | start_signal=%s | live_verified=%s | balance=%.2f | min=%.2f",
            sm.get_current_state().value,
            TRADING_ENGINE_READY.is_set(),
            _live_verified,
            _balance,
            _min_balance,
        )

        # FIX: Proactively set _first_snap_accepted when the cycle capital
        # snapshot shows a valid live-exchange source with real capital and
        # valid brokers.  commit_activation() checks this flag as part of the
        # activation invariant, but it is only set *inside* commit_activation()
        # after all gates pass — creating a chicken-and-egg deadlock where the
        # flag is never set because the gate that requires it never passes.
        # Setting it here (before commit_activation is called) breaks the cycle.
        _snap_source_sv = str(_cycle_capital.get("snapshot_source", "") or "")
        _valid_brokers_sv = int(_cycle_capital.get("ca_valid_brokers", 0) or 0)
        _ca_hydrated_sv = bool(_cycle_capital.get("ca_is_hydrated", False))
        _ca_capital_sv = float(_cycle_capital.get("ca_total_capital", 0.0) or 0.0)
        if (
            not sm.get_first_snap_accepted()
            and _ca_hydrated_sv
            and _ca_capital_sv > 0.0
            and _valid_brokers_sv > 0
            and _snap_source_sv in {"live_exchange", "capital_authority"}
        ):
            try:
                sm.set_first_snap_accepted(True)
                logger.critical(
                    "[SUPERVISOR] _first_snap_accepted set to True — "
                    "CA hydrated real=$%.2f valid_brokers=%d source=%s",
                    _ca_capital_sv,
                    _valid_brokers_sv,
                    _snap_source_sv,
                )
            except Exception as _snap_accept_err:
                logger.warning(
                    "[SUPERVISOR] set_first_snap_accepted failed: %s", _snap_accept_err
                )

        # ── FORCE_TRADE: bypass _first_snap_accepted gate when snapshot_source
        # is "placeholder" (Redis/capital pipeline unavailable).  Without this,
        # NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true deployments never produce a
        # "live_exchange" snapshot, so _first_snap_accepted stays False forever
        # and commit_activation() is permanently blocked even with real capital.
        _force_activation_sv = (
            _env_truthy("FORCE_TRADE")
            or _env_truthy("NIJA_FORCE_ACTIVATION")
            or _env_truthy("FORCE_TRADE_MODE")
            or _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
        )
        if (
            _force_activation_sv
            and not sm.get_first_snap_accepted()
            and _ca_capital_sv > 0.0
        ):
            try:
                sm.set_first_snap_accepted(True)
                logger.warning(
                    "⚡ [SUPERVISOR] FORCE_TRADE: _first_snap_accepted forced True — "
                    "snapshot_source=%s ca_capital=$%.2f (bypassing live_exchange requirement). "
                    "This unblocks commit_activation() when Redis/capital pipeline is unavailable.",
                    _snap_source_sv or "placeholder",
                    _ca_capital_sv,
                )
            except Exception as _snap_force_err:
                logger.warning(
                    "[SUPERVISOR] FORCE_TRADE _first_snap_accepted force-set failed: %s",
                    _snap_force_err,
                )

        # Missing trigger fix: the supervisor attempts activation every cycle
        # while in OFF/LIVE_PENDING_CONFIRMATION, using the same frozen
        # cycle capital snapshot.
        #
        # Why allow LIVE_PENDING_CONFIRMATION even when _live_verified=False:
        # once the FSM is explicitly armed, downstream coordinator gates may
        # still need additional cycles to converge; skipping commit_activation()
        # in that state can stall lifecycle progression in WARM forever.
        #
        # FORCE_TRADE / NIJA_FORCE_ACTIVATION: operator override flags that
        # must also trigger commit_activation() so the FSM can arm to
        # LIVE_PENDING_CONFIRMATION and eventually reach LIVE_ACTIVE via the
        # 5-minute auto-transition timeout even when LIVE_CAPITAL_VERIFIED is
        # not explicitly set in the environment.
        _state_for_commit = sm.get_current_state()
        _attempt_commit = (
            _live_verified
            or _force_activation_sv
            or _state_for_commit == _TradingState.LIVE_PENDING_CONFIRMATION
        )
        if _attempt_commit:
            _committed = False
            try:
                if hasattr(sm, "commit_activation"):
                    _committed = bool(sm.commit_activation(cycle_capital=_cycle_capital))
            except Exception as _commit_err:
                logger.warning("Supervisor commit_activation failed: %s", _commit_err)

            # ── FORCE_TRADE hard-activation fallback ─────────────────────────
            # When commit_activation() fails (e.g. startup coordinator gates not
            # yet converged) but FORCE_TRADE is set, call _force_live_active_transition()
            # directly to bypass all distributed-authority pre-flight checks.
            # This is the final escape hatch for the "6000+ cycles, zero trades"
            # condition where the FSM is permanently stuck in LIVE_PENDING_CONFIRMATION
            # because Redis/capital-pipeline infrastructure is unavailable.
            if not _committed and _force_activation_sv and _live_verified:
                _state_after_commit = sm.get_current_state()
                if _state_after_commit != _TradingState.LIVE_ACTIVE:
                    logger.warning(
                        "⚡ [SUPERVISOR] FORCE_TRADE hard-activation: commit_activation() failed "
                        "(state=%s) — calling _force_live_active_transition() to bypass "
                        "distributed-authority gates. LIVE_CAPITAL_VERIFIED=true + FORCE_TRADE=true.",
                        _state_after_commit.value,
                    )
                    try:
                        if hasattr(sm, "_force_live_active_transition"):
                            _force_ok = sm._force_live_active_transition(
                                "FORCE_TRADE+LIVE_CAPITAL_VERIFIED: supervisor hard-activation bypass"
                            )
                            if _force_ok:
                                # Check that hard controls also agree before claiming orders will
                                # be submitted — hard controls (EMERGENCY_STOP, INITIALIZING,
                                # writer_not_ready) may still block even if the FSM reached
                                # LIVE_ACTIVE.  A False here is informational; the order attempt
                                # will happen and get a clear rejection log from execute_entry().
                                _hc_ok = True
                                _hc_reason = ""
                                try:
                                    from controls import get_hard_controls
                                    _hc = get_hard_controls() if callable(get_hard_controls) else None
                                    if _hc is not None:
                                        _hc_ok, _hc_reason = _hc.can_trade(None)  # type: ignore[arg-type]
                                except Exception:
                                    _hc_ok = True  # unknown → optimistic
                                if _hc_ok:
                                    logger.critical(
                                        "⚡ [SUPERVISOR] FORCE_TRADE hard-activation SUCCESS — "
                                        "FSM is now LIVE_ACTIVE. Orders will be submitted this cycle."
                                    )
                                else:
                                    logger.critical(
                                        "⚡ [SUPERVISOR] FORCE_TRADE hard-activation SUCCESS — "
                                        "FSM is now LIVE_ACTIVE, but hard controls still report: %s — "
                                        "orders will be attempted; execution engine will log rejections.",
                                        _hc_reason or "BLOCKED",
                                    )
                            else:
                                logger.warning(
                                    "⚡ [SUPERVISOR] FORCE_TRADE hard-activation returned False — "
                                    "FSM transition may have failed; check state machine logs."
                                )
                    except Exception as _force_act_err:
                        logger.warning(
                            "[SUPERVISOR] FORCE_TRADE _force_live_active_transition failed: %s",
                            _force_act_err,
                        )

            if not _committed and _sufficient_balance and sm.get_current_state() == _TradingState.OFF:
                try:
                    sm.transition_to(
                        _TradingState.LIVE_PENDING_CONFIRMATION,
                        "supervisor arming: LIVE_CAPITAL_VERIFIED + sufficient balance"
                        if _live_verified
                        else "supervisor arming: FORCE_TRADE override",
                    )
                    logger.critical("🟡 SUPERVISOR ARMING: OFF -> LIVE_PENDING_CONFIRMATION")
                except Exception as _arm_err:
                    logger.warning("Supervisor arming fallback failed: %s", _arm_err)
        elif _balance > 0.0:
            logger.warning(
                "⚠️ Supervisor activation blocked: LIVE_CAPITAL_VERIFIED is false and "
                "FORCE_TRADE/NIJA_FORCE_ACTIVATION not set, while balance is %.2f. "
                "Set LIVE_CAPITAL_VERIFIED=true or FORCE_TRADE=true to enable activation.",
                _balance,
            )
    except Exception as _sm_err:
        logger.error(
            "supervisor state machine step failed — trading loop activation may be blocked: %s",
            _sm_err,
            exc_info=True,
        )

# ---------------------------------------------------------------------------
# Entry-to-Order Trace — mandatory cycle observability
# ---------------------------------------------------------------------------
try:
    from entry_trace import CycleOutcome, emit_cycle_trace, emit_cycle_trace_summary
    _ENTRY_TRACE_AVAILABLE = True
except ImportError:
    try:
        from bot.entry_trace import CycleOutcome, emit_cycle_trace, emit_cycle_trace_summary
        _ENTRY_TRACE_AVAILABLE = True
    except ImportError:
        _ENTRY_TRACE_AVAILABLE = False
        # Fallback no-ops so call sites never need a guard
        class CycleOutcome:  # type: ignore[no-redef]
            SCAN_STARTED = "SCAN_STARTED"
            ENTRY_VETOED = "ENTRY_VETOED"
            ORDER_PLACED = "ORDER_PLACED"
            ORDER_REJECTED = "ORDER_REJECTED"
            SCAN_COMPLETE_NO_SIGNAL = "SCAN_COMPLETE_NO_SIGNAL"

        def emit_cycle_trace(outcome, **kwargs):  # type: ignore[misc]
            pass

        def emit_cycle_trace_summary(cycle_number, veto_counts, reject_counts):  # type: ignore[misc]
            pass

# Max positions the core loop may open in a single cycle
# (hard cap — position-level cap is enforced upstream by TradingStrategy)
MAX_ENTRIES_PER_CYCLE = 3

# How often (in completed run_scan_phase calls) to emit a [CYCLE_TRACE_SUMMARY]
# histogram of accumulated veto/rejection reason counts.
# Override at runtime with NIJA_VETO_SUMMARY_INTERVAL env var.
VETO_SUMMARY_INTERVAL: int = int(os.environ.get("NIJA_VETO_SUMMARY_INTERVAL", "50"))

# Minimum score before the loop will even attempt an entry
# (NijaAIEngine uses its own adaptive threshold; this is a hard circuit-breaker)
# Lowered 25.0 → 20.0 → 14.0 → 11.0 → 8.0 → 5.0 → 3.0 → 2.0 to unblock 0-trade condition.
# Override at runtime with NIJA_CORE_MIN_SCORE env var.
MIN_SCORE_HARD_FLOOR = float(os.environ.get("NIJA_CORE_MIN_SCORE", "2.0"))

# ── DEAD ZONE detection ──────────────────────────────────────────────────────
# When zero_signal_streak reaches DEAD_ZONE_STREAK_THRESHOLD the bot is
# officially in a "dead zone" — normal AI scoring is producing nothing usable.
# In dead-zone mode TWO things happen simultaneously:
#   1. Momentum-Only Entry Mode activates (relaxed RSI 52/48 + vol check).
#   2. Volume fallback is enabled regardless of profit-mode level.
# This guarantees at least one candidate per cycle during range-bound markets.
DEAD_ZONE_STREAK_THRESHOLD: int = int(os.environ.get("NIJA_DEAD_ZONE_STREAK", "2"))

# After this many consecutive zero-signal cycles, progressive score relaxation
# kicks in: each 3-cycle step (was 5) reduces the effective floor.
# Lowered 8 → 5 → 2 so relaxation triggers within 2 missed cycles.
FORCED_ENTRY_STREAK_THRESHOLD: int = int(os.environ.get("NIJA_FORCED_ENTRY_STREAK", "2"))

# Number of relaxation steps (each step = 3 cycles past threshold).
MAX_RELAXATION_STEPS: int = 3

# Fractional threshold reduction per step:
#   step 1 (streak  2–4): factor 0.15 → floor × 0.85
#   step 2 (streak  5–7): factor 0.25 → floor × 0.75
#   step 3 (streak   ≥8): factor 0.40 → floor × 0.60  (hard cap)
_RELAXATION_SCHEDULE: Tuple[float, ...] = (0.0, 0.15, 0.25, 0.40)

# After this many consecutive zero-signal cycles, the hard bypass activates:
# all quality floors are ignored and the top-ranked available candidate is
# accepted unconditionally.  Lowered 40 → 10 → 8 → 5 → 3 → 2.
HARD_BYPASS_STREAK_THRESHOLD: int = int(os.environ.get("NIJA_HARD_BYPASS_STREAK", "2"))

# How often (in cycles) to emit the execution KPI summary line.
# Covers: placed, rejected, vetoed, no_signal, entry_conversion_rate, signal_utilization.
# Override via NIJA_CYCLE_SUMMARY_INTERVAL env var.
CYCLE_SUMMARY_INTERVAL: int = int(os.environ.get("NIJA_CYCLE_SUMMARY_INTERVAL", "10"))

# One-shot manual forced-entry flag.
# Set to True externally to force the top-scored candidate in the very next
# scan cycle, bypassing all quality filters.  The flag is automatically reset
# to False after a single cycle so exactly one trade is forced.
# Use module-level access for both reading and writing:
#   import bot.nija_core_loop as _cl
#   _cl.FORCE_NEXT_CYCLE = True   # force the next scan cycle
#   print(_cl.FORCE_NEXT_CYCLE)   # check current state
# Thread-safety note: the read-and-reset operation inside _phase3_scan_and_enter
# is protected by _FORCE_LOCK to prevent duplicate forced entries under
# concurrent callers.
FORCE_NEXT_CYCLE: bool = False
_FORCE_LOCK = threading.Lock()


def _get_relaxation_factor(streak: int) -> float:
    """Return threshold-reduction fraction for the given zero-signal streak.

    Returns 0.0 when below FORCED_ENTRY_STREAK_THRESHOLD.
    Caps at _RELAXATION_SCHEDULE[MAX_RELAXATION_STEPS] = 0.60.
    """
    if streak < FORCED_ENTRY_STREAK_THRESHOLD:
        return 0.0
    return _RELAXATION_SCHEDULE[_get_relaxation_step(streak)]


def _get_relaxation_step(streak: int) -> int:
    """Return the (1-based) relaxation step index for the given streak.

    step 1 → streak 2–4, step 2 → streak 5–7, step 3 → streak ≥ 8 (cap).
    Returns 0 when below FORCED_ENTRY_STREAK_THRESHOLD.
    """
    if streak < FORCED_ENTRY_STREAK_THRESHOLD:
        return 0
    cycles_past = streak - FORCED_ENTRY_STREAK_THRESHOLD
    return min(MAX_RELAXATION_STEPS, cycles_past // 3 + 1)


def _get_relaxation_factor_with_threshold(streak: int, threshold: int) -> float:
    """Variant of _get_relaxation_factor that accepts a custom streak threshold."""
    if streak < threshold:
        return 0.0
    cycles_past = streak - threshold
    step = min(MAX_RELAXATION_STEPS, cycles_past // 3 + 1)
    return _RELAXATION_SCHEDULE[step]


def _get_relaxation_step_with_threshold(streak: int, threshold: int) -> int:
    """Variant of _get_relaxation_step that accepts a custom streak threshold."""
    if streak < threshold:
        return 0
    cycles_past = streak - threshold
    return min(MAX_RELAXATION_STEPS, cycles_past // 3 + 1)

# Attempt to import TOP_N from sniper_filter at module load time.
# Fallback to 2 when the module is unavailable.
try:
    from sniper_filter import TOP_N as _SNIPER_TOP_N_DEFAULT
except ImportError:
    try:
        from bot.sniper_filter import TOP_N as _SNIPER_TOP_N_DEFAULT
    except ImportError:
        _SNIPER_TOP_N_DEFAULT = 2

# ---------------------------------------------------------------------------
# Score Distribution Debugger — optional dependency
# ---------------------------------------------------------------------------
_SDD_AVAILABLE = False
_get_sdd = None  # type: ignore
try:
    from score_distribution_debugger import get_score_debugger as _get_sdd  # type: ignore
    _SDD_AVAILABLE = True
except ImportError:
    try:
        from bot.score_distribution_debugger import get_score_debugger as _get_sdd  # type: ignore
        _SDD_AVAILABLE = True
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Profit Mode Controller — optional dependency
# ---------------------------------------------------------------------------
_PMC_AVAILABLE = False
_get_pmc = None  # type: ignore
try:
    from profit_mode_controller import (  # type: ignore
        MarketConditionSnapshot as _MarketConditionSnapshot,
        get_profit_mode_controller as _get_pmc,
    )
    _PMC_AVAILABLE = True
except ImportError:
    try:
        from bot.profit_mode_controller import (  # type: ignore
            MarketConditionSnapshot as _MarketConditionSnapshot,
            get_profit_mode_controller as _get_pmc,
        )
        _PMC_AVAILABLE = True
    except ImportError:
        _MarketConditionSnapshot = None  # type: ignore[assignment]
        pass

# ---------------------------------------------------------------------------
# Momentum Entry Filter — relaxed dead-zone checkers
# ---------------------------------------------------------------------------
_MOMENTUM_FILTER_AVAILABLE = False
_check_mom_long_relaxed = None   # type: ignore
_check_mom_short_relaxed = None  # type: ignore
try:
    from momentum_entry_filter import (  # type: ignore
        check_momentum_long_relaxed as _check_mom_long_relaxed,
        check_momentum_short_relaxed as _check_mom_short_relaxed,
    )
    _MOMENTUM_FILTER_AVAILABLE = True
except ImportError:
    try:
        from bot.momentum_entry_filter import (  # type: ignore
            check_momentum_long_relaxed as _check_mom_long_relaxed,
            check_momentum_short_relaxed as _check_mom_short_relaxed,
        )
        _MOMENTUM_FILTER_AVAILABLE = True
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Trade Permission Engine — authoritative single-source decision layer
# ---------------------------------------------------------------------------
_TPE_AVAILABLE = False
_get_tpe = None  # type: ignore
try:
    from trade_permission_engine import (  # type: ignore
        get_trade_permission_engine as _get_tpe,
    )
    _TPE_AVAILABLE = True
except ImportError:
    try:
        from bot.trade_permission_engine import (  # type: ignore
            get_trade_permission_engine as _get_tpe,
        )
        _TPE_AVAILABLE = True
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Scanner Funnel Tracker — per-cycle alpha-generation quality baseline
# ---------------------------------------------------------------------------
_FUNNEL_TRACKER_AVAILABLE = False
_get_funnel_tracker = None  # type: ignore
try:
    from scanner_funnel_tracker import get_scanner_funnel_tracker as _get_funnel_tracker  # type: ignore
    _FUNNEL_TRACKER_AVAILABLE = True
except ImportError:
    try:
        from bot.scanner_funnel_tracker import get_scanner_funnel_tracker as _get_funnel_tracker  # type: ignore
        _FUNNEL_TRACKER_AVAILABLE = True
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CoreLoopResult:
    """Summary returned by NijaCoreLoop.run_scan_phase()."""
    symbols_scored:   int = 0
    entries_taken:    int = 0
    entries_blocked:  int = 0
    exits_taken:      int = 0
    errors:           List[str] = field(default_factory=list)
    next_interval:    int = 150    # recommended seconds before next cycle


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class NijaCoreLoop:
    """
    Rebuilt, single-pass core trading loop.

    Parameters
    ----------
    apex_strategy : NIJAApexStrategyV71
        The strategy instance that provides ``analyze_market``,
        ``execute_action``, and ``calculate_indicators``.
    max_positions : int
        Hard cap on concurrent open positions.
    """

    def __init__(self, apex_strategy: Any, max_positions: int = 5) -> None:
        self.apex = apex_strategy
        self.max_positions = max_positions
        self._lock = threading.Lock()

        # Lazy AI engine reference
        self._ai_engine = None

        # Consecutive cycles where Phase 3 produced zero entries (used by
        # the progressive relaxation mechanism — see FORCED_ENTRY_STREAK_THRESHOLD).
        self._zero_signal_streak: int = 0

        # ── Session-level execution KPI counters ─────────────────────────────
        # Incremented at each emit_cycle_trace call so the periodic summary
        # reflects exact outcome distribution since startup.
        self._total_cycles: int = 0     # SCAN_STARTED emits
        self._n_placed: int = 0         # ORDER_PLACED emits
        self._n_rejected: int = 0       # ORDER_REJECTED emits (broker rejection or execution failure)
        self._n_vetoed: int = 0         # ENTRY_VETOED emits
        self._n_no_signal: int = 0      # SCAN_COMPLETE_NO_SIGNAL emits
        # Veto / rejection reason histograms.
        # veto_reason_counts   — portfolio-level pre-scan blocks (position cap,
        #                        safety gate, user_mode, …)
        # reject_reason_counts — per-signal in-scan rejections (Trade Permission
        #                        Engine blocks, …)
        # A [CYCLE_TRACE_SUMMARY] is emitted every VETO_SUMMARY_INTERVAL cycles.
        self.veto_reason_counts: Dict[str, int] = {}
        self.reject_reason_counts: Dict[str, int] = {}
        self._summary_cycle_count: int = 0

        logger.info(
            "✅ NijaCoreLoop initialized (max_positions=%d, max_entries_per_cycle=%d)",
            max_positions,
            MAX_ENTRIES_PER_CYCLE,
        )

    # ------------------------------------------------------------------
    # Execution KPI summary
    # ------------------------------------------------------------------

    def _log_execution_kpis(self) -> None:
        """Log a one-line execution KPI summary with throughput ratios.

        entry_conversion_rate = placed / (placed + rejected)
            Fraction of broker submissions that succeeded.

        signal_utilization = placed / total_cycles
            Orders placed per cycle — measures realized throughput.
        """
        placed = self._n_placed
        rejected = self._n_rejected
        vetoed = self._n_vetoed
        no_signal = self._n_no_signal
        total = self._total_cycles

        submitted = placed + rejected
        entry_conversion_rate = placed / submitted if submitted > 0 else 0.0
        signal_utilization = placed / total if total > 0 else 0.0

        logger.info(
            "📊 [CYCLE_KPI] placed=%d rejected=%d vetoed=%d no_signal=%d "
            "| entry_conversion_rate=%.3f signal_utilization=%.3f "
            "(total_cycles=%d)",
            placed, rejected, vetoed, no_signal,
            entry_conversion_rate, signal_utilization,
            total,
        )
    # Veto / rejection histogram helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_reason(reason: str) -> str:
        """Return a short, stable key from a raw veto/reject reason string.

        Examples
        --------
        ``"position_cap_reached(3/5)"``   → ``"position_cap"``
        ``"latency_drift: …"``            → ``"latency_drift"``
        ``"trade_permission_engine"``     → ``"trade_permission_engine"``
        ``"min_notional"``                → ``"min_notional"``
        """
        if not reason:
            return "unknown"
        # Strip parenthetical detail: "position_cap_reached(3/5)" → "position_cap_reached"
        base = reason.split("(")[0].strip()
        # Drop trailing "_reached" suffix so "position_cap_reached" → "position_cap"
        base = base.replace("_reached", "")
        # Take only the first token before a colon or space (handles
        # "latency_drift: some message" and similar safety-gate strings)
        base = base.split(":")[0].split(" ")[0].strip()
        return base or "unknown"

    def _record_veto(self, reason: str) -> None:
        """Increment the veto histogram counter for *reason*."""
        key = self._normalize_reason(reason)
        self.veto_reason_counts[key] = self.veto_reason_counts.get(key, 0) + 1

    def _record_reject(self, reason: str) -> None:
        """Increment the per-signal rejection histogram counter for *reason*."""
        key = self._normalize_reason(reason)
        self.reject_reason_counts[key] = self.reject_reason_counts.get(key, 0) + 1

    @staticmethod
    def _normalize_funnel_reason(reason: Any) -> str:
        """Return a stable, uppercase reason code for trade funnel traces."""
        raw = str(reason or "").strip()
        if not raw:
            return "UNSPECIFIED"
        upper = raw.upper()
        if "MIN_NOTIONAL_AFTER_FEES" in upper:
            return "MIN_NOTIONAL_AFTER_FEES"
        if "MIN_NOTIONAL" in upper:
            return "MIN_NOTIONAL_AFTER_FEES"
        if "LOW_EXPECTANCY" in upper:
            return "LOW_EXPECTANCY"
        if "RSI" in upper:
            return "RSI_BELOW_THRESHOLD"
        chars = [ch if ch.isalnum() else "_" for ch in upper]
        code = "".join(chars).strip("_")
        while "__" in code:
            code = code.replace("__", "_")
        return code or "UNSPECIFIED"

    def _emit_trade_funnel_trace(self, pair: str, stages: Mapping[str, Tuple[str, str]]) -> None:
        """Emit deterministic per-symbol trade funnel trace lines."""
        stage_order = ("market_data", "regime", "signal", "ai_gate", "profitability")
        lines: List[str] = [f"PAIR={str(pair or '').replace('-', '/')}"]
        reason_code: Optional[str] = None
        for stage in stage_order:
            item = stages.get(stage)
            if not item:
                continue
            outcome, reason = item
            outcome_code = "PASS" if str(outcome).upper() == "PASS" else "FAIL"
            lines.append(f"{stage}={outcome_code}")
            if outcome_code == "FAIL":
                reason_code = self._normalize_funnel_reason(reason)
                break
        if reason_code:
            lines.append(f"reason={reason_code}")
        logger.info("\n".join(lines))

    def _maybe_emit_veto_summary(self) -> None:
        """Emit [CYCLE_TRACE_SUMMARY] every VETO_SUMMARY_INTERVAL completed cycles."""
        if self._summary_cycle_count >= VETO_SUMMARY_INTERVAL and self._summary_cycle_count % VETO_SUMMARY_INTERVAL == 0:
            emit_cycle_trace_summary(
                cycle_number=self._summary_cycle_count,
                veto_counts=self.veto_reason_counts,
                reject_counts=self.reject_reason_counts,
            )

    def start(self, strategy: Any = None) -> None:
        """Start the continuous execution loop via start_trading_engine() (idempotent)."""
        _target = strategy if strategy is not None else self.apex
        if _target is None:
            logger.warning("NijaCoreLoop.start(): no strategy — execution loop NOT started")
            return
        start_trading_engine(_target)
        logger.info("✅ NijaCoreLoop.start(): execution loop started")

    # ------------------------------------------------------------------
    # Lazy component loaders
    # ------------------------------------------------------------------

    def _get_ai_engine(self):
        if self._ai_engine is None:
            try:
                from nija_ai_engine import get_nija_ai_engine
                self._ai_engine = get_nija_ai_engine()
            except ImportError:
                try:
                    from bot.nija_ai_engine import get_nija_ai_engine
                    self._ai_engine = get_nija_ai_engine()
                except ImportError:
                    logger.warning(
                        "NijaAIEngine not available — core loop will use apex.analyze_market directly"
                    )
        return self._ai_engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_scan_phase(
        self,
        broker: Any,
        balance: float,
        symbols: List[str],
        open_positions_count: int = 0,
        user_mode: bool = False,
    ) -> CoreLoopResult:
        """
        Execute the full scan phase for one trading cycle.

        Phase 1 — Safety gate  (drawdown / daily loss)
        Phase 2 — Position management  (exits / trailing stops)
        Phase 3 — Score all symbols → rank → take top-N

        Parameters
        ----------
        broker              : Broker client instance (falls back to
                              ``apex.broker_client`` when None)
        balance             : Current account equity (USD)
        symbols             : Ordered list of symbols to scan
        open_positions_count: Number of currently open positions
        user_mode           : When True, skip Phase 3 (entries blocked)

        Returns
        -------
        CoreLoopResult with entries taken, next recommended interval, etc.
        """
        # ── Broker resolution: fall back to apex.broker_client when the
        # caller did not pass an explicit broker (or passed None).  This
        # covers the common case where run_scan_phase is called from
        # run_trading_loop → strategy.run_cycle without an explicit broker arg.
        if broker is None:
            broker = getattr(self.apex, "broker_client", None)

        # Guard: if still no broker or broker is disconnected, bail early so
        # individual per-symbol fetches don't silently return None for every
        # symbol and produce a zero-signal cycle.
        if broker is None or not getattr(broker, "connected", True):
            logger.warning(
                "🔴 Core loop: no broker connected — skipping scan phase "
                "(broker=%r connected=%r)",
                broker,
                getattr(broker, "connected", None) if broker is not None else None,
            )
            return CoreLoopResult()

        result = CoreLoopResult()
        cycle_start = time.time()

        # ── Scan-size throttling ──────────────────────────────────────────
        # Cap the symbol universe to NIJA_MAX_SCAN_SYMBOLS (default 100) to
        # prevent excessive OHLC fan-out.  The caller's ordering is preserved
        # so pre-ranked/liquid-first lists still produce the best candidates.
        try:
            from bot.ohlc_worker_pool import throttle_symbol_list  # type: ignore
        except ImportError:
            try:
                from ohlc_worker_pool import throttle_symbol_list  # type: ignore
            except ImportError:
                throttle_symbol_list = None  # type: ignore
        if throttle_symbol_list is not None:
            symbols = throttle_symbol_list(symbols)

        # ── Snapshot: capture volatile apex state ONCE for the entire cycle ──
        # All phases and gates receive this frozen reference so every check
        # sees a consistent view of the world even if background threads mutate
        # the underlying apex attributes while the scan is running.
        #
        # Capital fields (cycle_id, ca_is_hydrated, ca_total_capital,
        # ca_valid_brokers, mabm_brokers_ready, is_post_hydration) are
        # populated from the module-level _current_cycle_capital dict that
        # run_trading_loop captured once at cycle start — BEFORE
        # _supervisor_step_state_machine ran — so TradingStateMachine,
        # CapitalAllocationBrain, and MABM all operate on the same frozen
        # capital view.
        _cap = _current_cycle_capital  # may be {} when called outside run_trading_loop
        _cid = _current_cycle_id or (
            f"cycle-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-scan"
        )
        _ca_hydrated = bool(_cap.get("ca_is_hydrated", False))
        _ca_total_capital = float(_cap.get("ca_total_capital", 0.0) or 0.0)

        # ── Balance hydration waterfall ───────────────────────────────────
        # Priority order (highest → lowest):
        #   1. CA total capital (when hydrated AND non-zero)
        #   2. Caller-supplied balance (when non-zero)
        #   3. Broker cached balance (non-blocking attribute probe)
        #   4. broker.get_balance() live fetch (only when all above are zero)
        #   5. NIJA_FORCE_TRADE_BALANCE env var (operator override)
        #
        # The original logic used `_ca_total_capital if _ca_hydrated else balance`
        # which caused $0.00 snapshots whenever CA was hydrated but reported
        # zero capital — a common race condition at startup.
        _caller_balance = float(balance) if balance else 0.0
        _balance_source = "unknown"

        if _ca_hydrated and _ca_total_capital > 0.0:
            _canonical_balance = _ca_total_capital
            _balance_source = "ca_total_capital"
        elif _caller_balance > 0.0:
            _canonical_balance = _caller_balance
            _balance_source = "caller_supplied"
        else:
            # CA is not hydrated or reports zero AND caller supplied zero —
            # attempt broker cached-attribute probe (non-blocking).
            _broker_cached = _extract_cached_balance_for_log(broker) if broker is not None else 0.0
            if _broker_cached > 0.0:
                _canonical_balance = _broker_cached
                _balance_source = "broker_cached_attr"
            else:
                # Last resort: live broker.get_balance() call.
                _broker_live = 0.0
                try:
                    if broker is not None and hasattr(broker, "get_balance"):
                        _raw_bal = broker.get_balance()
                        if isinstance(_raw_bal, dict):
                            for _k in ("total_balance", "balance", "usd_balance", "equity", "total_usd", "available_usd"):
                                if _k in _raw_bal and float(_raw_bal[_k] or 0.0) > 0.0:
                                    _broker_live = float(_raw_bal[_k])
                                    break
                        elif _raw_bal is not None:
                            _broker_live = float(_raw_bal or 0.0)
                except Exception as _bal_err:
                    logger.warning("[NIJA] broker.get_balance() failed during balance hydration: %s", _bal_err)

                if _broker_live > 0.0:
                    _canonical_balance = _broker_live
                    _balance_source = "broker_get_balance"
                else:
                    # Final fallback: NIJA_FORCE_TRADE_BALANCE env var.
                    _env_balance_str = os.environ.get("NIJA_FORCE_TRADE_BALANCE", "").strip()
                    _env_balance = 0.0
                    try:
                        _env_balance = float(_env_balance_str) if _env_balance_str else 0.0
                    except (TypeError, ValueError):
                        pass
                    if _env_balance > 0.0:
                        _canonical_balance = _env_balance
                        _balance_source = "NIJA_FORCE_TRADE_BALANCE_env"
                    else:
                        # All sources exhausted — use zero and log loudly.
                        _canonical_balance = 0.0
                        _balance_source = "all_sources_zero"

        # ── [NIJA-PRINT] BALANCE SNAPSHOT ────────────────────────────────
        print(
            f"[NIJA-PRINT] BALANCE SNAPSHOT | "
            f"cycle_id={_cid} "
            f"canonical_balance=${_canonical_balance:.2f} "
            f"source={_balance_source} "
            f"ca_hydrated={_ca_hydrated} "
            f"ca_total_capital=${_ca_total_capital:.2f} "
            f"caller_balance=${_caller_balance:.2f} "
            f"NIJA_FORCE_TRADE_BALANCE={os.environ.get('NIJA_FORCE_TRADE_BALANCE', 'unset')}",
            flush=True,
        )
        logger.critical(
            "[NIJA] BALANCE SNAPSHOT | cycle_id=%s canonical=$%.2f source=%s "
            "ca_hydrated=%s ca_total_capital=$%.2f caller_balance=$%.2f "
            "NIJA_FORCE_TRADE_BALANCE=%s",
            _cid,
            _canonical_balance,
            _balance_source,
            _ca_hydrated,
            _ca_total_capital,
            _caller_balance,
            os.environ.get("NIJA_FORCE_TRADE_BALANCE", "unset"),
        )

        # Canonical balance source-of-truth:
        # - Once CA is hydrated AND reports a positive balance, use CA capital.
        # - If CA is hydrated but reports $0.00, fall back to caller-supplied
        #   balance so a stale/un-published CA snapshot does not zero-out the
        #   capital gate and block all orders.
        # - Before hydration, always use caller-supplied balance.
        # - If all sources are zero and FORCE_TRADE is active, try the broker
        #   cache directly, then the NIJA_FORCE_TRADE_BALANCE env override.
        _caller_balance = float(balance) if balance else 0.0
        if _ca_hydrated and _ca_total_capital > 0.0:
            _canonical_balance = _ca_total_capital
        elif _caller_balance > 0.0:
            _canonical_balance = _caller_balance
        else:
            # Last-resort: try broker cached balance then env override
            _broker_cached = _extract_cached_balance_for_log(broker) if broker is not None else 0.0
            _env_override = float(os.getenv("NIJA_FORCE_TRADE_BALANCE", "0") or 0)
            _canonical_balance = _broker_cached or _env_override or 0.0
            if _canonical_balance > 0.0:
                print(
                    f"[NIJA-PRINT] BALANCE HYDRATION FALLBACK | "
                    f"ca_hydrated={_ca_hydrated} ca_total=${_ca_total_capital:.2f} "
                    f"caller=${_caller_balance:.2f} broker_cached=${_broker_cached:.2f} "
                    f"env_override=${_env_override:.2f} → using=${_canonical_balance:.2f}",
                    flush=True,
                )
            else:
                print(
                    f"[NIJA-PRINT] BALANCE ZERO WARNING | "
                    f"ca_hydrated={_ca_hydrated} ca_total=${_ca_total_capital:.2f} "
                    f"caller=${_caller_balance:.2f} broker_cached=${_broker_cached:.2f} "
                    f"env_override=${_env_override:.2f} — all sources zero, capital gate will block",
                    flush=True,
                )
        print(
            f"[NIJA-PRINT] BALANCE SNAPSHOT | "
            f"ca_hydrated={_ca_hydrated} ca_total=${_ca_total_capital:.2f} "
            f"caller=${_caller_balance:.2f} canonical=${_canonical_balance:.2f}",
            flush=True,
        )
        snapshot = CycleSnapshot(
            balance=_canonical_balance,
            current_regime=getattr(self.apex, "current_regime", None),
            daily_pnl_usd=getattr(self.apex, "_daily_pnl_usd", 0.0),
            open_positions=open_positions_count,
            cycle_id=_cid,
            ca_is_hydrated=_ca_hydrated,
            ca_total_capital=_ca_total_capital,
            ca_valid_brokers=int(_cap.get("ca_valid_brokers", 0)),
            mabm_brokers_ready=bool(_cap.get("mabm_brokers_ready", False)),
            is_post_hydration=bool(_cap.get("is_post_hydration", False)),
            snapshot_source=str(_cap.get("snapshot_source", "placeholder") or "placeholder"),
            aggregation_normalized=bool(_cap.get("aggregation_normalized", True)),
        )

        # Publish the fully-constructed snapshot so that CapitalAllocationBrain
        # and MABM helpers can call get_current_cycle_snapshot() and get
        # consistent data for the remainder of this cycle.
        global _current_cycle_snapshot
        _current_cycle_snapshot = snapshot
        self._sync_risk_state_for_cycle(snapshot)

        logger.info(
            "🟢 Trading loop alive — scanning %d symbols (balance=$%.2f open=%d)",
            len(symbols), snapshot.balance, snapshot.open_positions,
        )

        # ── Per-cycle diagnostic header ───────────────────────────────────
        _cycle_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        logger.critical(
            "━━━ CYCLE #%d | %s | balance=$%.2f | open_positions=%d | "
            "symbols=%d | regime=%s | cycle_id=%s ━━━",
            self._total_cycles + 1,
            _cycle_ts,
            snapshot.balance,
            snapshot.open_positions,
            len(symbols),
            str(snapshot.current_regime or "unknown"),
            snapshot.cycle_id or "n/a",
        )

        # ── Market data fetch status ──────────────────────────────────────
        # Log broker identity and symbol universe size so operators can
        # confirm data is flowing before per-pair evaluation begins.
        _broker_name_diag = "unknown"
        try:
            if broker is not None:
                _broker_name_diag = (
                    self.apex._get_broker_name()
                    if hasattr(self.apex, "_get_broker_name")
                    else type(broker).__name__.replace("Broker", "").lower()
                )
        except Exception:
            pass
        logger.info(
            "📡 [MARKET_DATA] broker=%s | symbols_queued=%d | "
            "ca_hydrated=%s | ca_total_capital=$%.2f | valid_brokers=%d",
            _broker_name_diag,
            len(symbols),
            snapshot.ca_is_hydrated,
            snapshot.ca_total_capital,
            snapshot.ca_valid_brokers,
        )

        # ── Entry-to-Order Trace: opening event ──────────────────────────
        emit_cycle_trace(
            CycleOutcome.SCAN_STARTED,
            balance=round(snapshot.balance, 2),
            open_positions=snapshot.open_positions,
            symbols=len(symbols),
        )
        self._total_cycles += 1

        # ── Phase 1: Safety gate ──────────────────────────────────────────
        can_enter, safety_reason = self._phase1_safety(broker, snapshot)
        if not can_enter:
            logger.info("🛡️  Core loop safety gate blocked entries: %s", safety_reason)
            user_mode = True

        # ── Phase 2: Position management ─────────────────────────────────
        exits = self._phase2_manage_positions(broker, snapshot)
        result.exits_taken = exits
        # Update available slots after exits
        effective_open = max(0, snapshot.open_positions - exits)

        # ── Always Trade Mode bridge ──────────────────────────────────────
        # The ATM module existed but was not wired into the live core loop, so
        # an account with no confirmed entries could keep printing healthy loop
        # ticks while never arming the one-cycle force path.  Evaluate it after
        # safety/exit processing and before candidate generation.
        try:
            from bot.always_trade_mode import get_always_trade_mode
        except ImportError:
            try:
                from always_trade_mode import get_always_trade_mode  # type: ignore
            except ImportError:
                get_always_trade_mode = None  # type: ignore
        if get_always_trade_mode is not None:
            try:
                _atm_decision = get_always_trade_mode().run_pre_cycle_check(
                    user_mode=user_mode,
                    open_positions=effective_open,
                    balance=snapshot.balance,
                    last_trade_ts=getattr(self.apex, "last_trade_ts", None),
                )
                if getattr(_atm_decision, "force_entry", False):
                    global FORCE_NEXT_CYCLE
                    with _FORCE_LOCK:
                        FORCE_NEXT_CYCLE = True
                    logger.warning(
                        "⚡ ALWAYS TRADE MODE armed core-loop force entry — %s",
                        getattr(_atm_decision, "reason", "idle fallback"),
                    )
            except Exception as _atm_err:
                logger.debug("Always Trade Mode pre-cycle check skipped: %s", _atm_err)

        # ── Phase 3: Scan & ranked entry ──────────────────────────────────
        # ── Market-data health gate ───────────────────────────────────────
        # Before allowing new entries, verify the OHLC worker pool is healthy.
        # This prevents order submission when the data path is saturated,
        # stale, or returning high timeout rates — LIVE_ACTIVE is preserved;
        # only the per-cycle entry decision is gated.
        _md_healthy = True
        _md_new_entry_allowed = not user_mode
        _md_pool = None
        try:
            from bot.ohlc_worker_pool import get_pool as _get_ohlc_pool  # type: ignore
        except ImportError:
            try:
                from ohlc_worker_pool import get_pool as _get_ohlc_pool  # type: ignore
            except ImportError:
                _get_ohlc_pool = None  # type: ignore
        if _get_ohlc_pool is not None:
            try:
                _md_pool = _get_ohlc_pool()
                _md_healthy, _md_detail = _md_pool.compute_market_data_healthy()
                if not _md_healthy:
                    _md_new_entry_allowed = False
                    logger.warning(
                        "MARKET_DATA_HEALTHY=false detail=%s — new entries paused this cycle",
                        _md_detail,
                    )
                    print(
                        f"[NIJA-PRINT] MARKET_DATA_HEALTHY=false "
                        f"active_workers={_md_detail.get('active_ohlc_workers')} "
                        f"timeout_rate={_md_detail.get('timeout_rate')}",
                        flush=True,
                    )
                else:
                    logger.info("MARKET_DATA_HEALTHY=true new_entry_allowed=%s", _md_new_entry_allowed)
                    print(
                        f"[NIJA-PRINT] MARKET_DATA_HEALTHY=true new_entry_allowed={_md_new_entry_allowed}",
                        flush=True,
                    )
                # Purge stale dedupe entries every cycle
                _md_pool.purge_stale_dedupe()
            except Exception as _mde:
                logger.warning("MARKET_DATA_HEALTH_CHECK_FAILED err=%s", _mde)

        # Determine runtime context for telemetry (best-effort)
        _rt_state = "LIVE_ACTIVE"
        _rt_authority = int(
            str(os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")).strip() or "1"
        )
        try:
            from bot.trading_state_machine import TradingStateMachine  # type: ignore
            _tsm = getattr(self.apex, "state_machine", None) or getattr(self.apex, "_tsm", None)
            if _tsm is not None:
                _rt_state = str(_tsm.get_current_state().name if hasattr(_tsm.get_current_state(), "name") else _tsm.get_current_state())
        except Exception:
            pass

        # Gate entries: user_mode OR not healthy
        _effective_user_mode = user_mode or not _md_new_entry_allowed

        if not _effective_user_mode:
            available_slots = max(0, self.max_positions - effective_open)
            if available_slots > 0:
                logger.critical(
                    "🔍 [Phase3] SCAN_ENTRY — scanning markets | "
                    "symbols=%d slots=%d open=%d user_mode=%s safety_blocked=%s md_healthy=%s",
                    len(symbols), available_slots, effective_open,
                    user_mode, not can_enter, _md_healthy,
                )
                entries, blocked, scored, _gate_rejections = self._phase3_scan_and_enter(
                    broker=broker,
                    snapshot=snapshot,
                    symbols=symbols,
                    available_slots=available_slots,
                    zero_signal_streak=self._zero_signal_streak,
                )
                result.entries_taken = entries
                result.entries_blocked = blocked
                result.symbols_scored = scored

                # Update the zero-signal streak counter for the next cycle
                if entries > 0:
                    self._zero_signal_streak = 0
                else:
                    self._zero_signal_streak += 1
                    _relaxation = _get_relaxation_factor(self._zero_signal_streak)
                    if _relaxation > 0.0:
                        _step = _get_relaxation_step(self._zero_signal_streak)
                        logger.warning(
                            "⚡ Core loop: zero-signal streak=%d — "
                            "progressive relaxation step=%d/%d (factor=%.1f, floor×%.1f)",
                            self._zero_signal_streak,
                            _step, MAX_RELAXATION_STEPS, _relaxation, 1.0 - _relaxation,
                        )
                    elif self._zero_signal_streak == FORCED_ENTRY_STREAK_THRESHOLD - 1:
                        logger.info(
                            "⚡ Core loop: zero-signal streak=%d — "
                            "progressive relaxation activates next cycle (threshold=%d)",
                            self._zero_signal_streak,
                            FORCED_ENTRY_STREAK_THRESHOLD,
                        )

                # ── Gate rejection counters ───────────────────────────────
                _data_insuff = _gate_rejections.get("data_insufficient", 0)
                _indic_fail  = _gate_rejections.get("indicators_failed", 0)
                logger.critical(
                    "📊 [GATE_REJECTIONS] cycle=%d | "
                    "data_insufficient=%d | indicators_failed=%d | "
                    "market_filter_rejected=%d | "
                    "confidence_gate_rejected=%d | adx_gate_rejected=%d | "
                    "volume_gate_rejected=%d | momentum_filter_rejected=%d | "
                    "ai_gate_rejected=%d | notional_gate_rejected=%d | "
                    "capital_gate_rejected=%d | risk_gate_rejected=%d",
                    self._total_cycles,
                    _data_insuff,
                    _indic_fail,
                    _gate_rejections.get("market_filter_rejected", 0),
                    _gate_rejections.get("confidence_gate_rejected", 0),
                    _gate_rejections.get("adx_gate_rejected", 0),
                    _gate_rejections.get("volume_gate_rejected", 0),
                    _gate_rejections.get("momentum_filter_rejected", 0),
                    _gate_rejections.get("ai_gate_rejected", 0),
                    _gate_rejections.get("notional_gate_rejected", 0),
                    _gate_rejections.get("capital_gate_rejected", 0),
                    _gate_rejections.get("risk_gate_rejected", 0),
                )
                print(
                    f"[NIJA-PRINT] GATE_REJECTIONS | cycle={self._total_cycles} "
                    f"data_insufficient={_data_insuff} indicators_failed={_indic_fail} "
                    f"market_filter={_gate_rejections.get('market_filter_rejected', 0)} "
                    f"confidence={_gate_rejections.get('confidence_gate_rejected', 0)} "
                    f"adx={_gate_rejections.get('adx_gate_rejected', 0)} "
                    f"volume={_gate_rejections.get('volume_gate_rejected', 0)}",
                    flush=True,
                )
                if _data_insuff > 0 and scored == 0:
                    logger.critical(
                        "🚨 [DIAG] ALL %d symbols failed data fetch (data_insufficient=%d) — "
                        "broker candle API may be returning None/empty/short DataFrames. "
                        "Check broker connectivity, symbol format, and NIJA_CANDLE_FETCH_TIMEOUT.",
                        len(symbols), _data_insuff,
                    )

                # ── Entry-to-Order Trace: terminal outcome ────────────────
                if entries == 0:
                    emit_cycle_trace(
                        CycleOutcome.SCAN_COMPLETE_NO_SIGNAL,
                        symbols_scored=scored,
                    )
                    self._n_no_signal += 1
                # ORDER_PLACED / ORDER_REJECTED traces are emitted (and their
                # counters incremented) per entry inside _phase3_scan_and_enter

            else:
                _gate_rejections = {}
                logger.info(
                    "🔒 Core loop: position cap reached (%d/%d) — skipping entries",
                    effective_open,
                    self.max_positions,
                )
                # ── Entry-to-Order Trace: position cap veto ───────────────
                _cap_reason = f"position_cap_reached({effective_open}/{self.max_positions})"
                emit_cycle_trace(
                    CycleOutcome.ENTRY_VETOED,
                    reason=_cap_reason,
                )
                self._n_vetoed += 1
                self._record_veto(_cap_reason)
        else:
            _gate_rejections = {}
            _block_reason = (
                "market_data_unhealthy" if not _md_healthy
                else ("user_mode" if user_mode else "entries_blocked")
            )
            logger.info("🔒 Core loop: entries blocked (%s)", _block_reason)
            # ── Entry-to-Order Trace: pre-scan veto ──────────────────────
            # user_mode can be True for two distinct reasons:
            #   1. Safety gate fired (can_enter=False) → report the specific safety reason.
            #   2. Caller explicitly passed user_mode=True (can_enter still True) → report "user_mode".
            # These are mutually exclusive: the safety gate sets user_mode=True only when
            # can_enter is False, so the inner check is not redundant.
            _prescan_reason = safety_reason if not can_enter else _block_reason
            emit_cycle_trace(
                CycleOutcome.ENTRY_VETOED,
                reason=_prescan_reason,
            )
            self._n_vetoed += 1
            self._record_veto(_prescan_reason)

        # ── Cycle telemetry (OHLC pool health) ───────────────────────────
        try:
            if _md_pool is not None:
                _md_pool.emit_cycle_telemetry(
                    runtime_state=_rt_state,
                    execution_authority=_rt_authority,
                    scan_symbols=len(symbols),
                    new_entry_allowed=not _effective_user_mode,
                )
        except Exception as _tel_err:
            logger.debug("CYCLE_TELEMETRY_EMIT_FAILED err=%s", _tel_err)

        # ── Increment summary cycle counter and maybe emit histogram ─────
        self._summary_cycle_count += 1
        self._maybe_emit_veto_summary()
        ai = self._get_ai_engine()
        if ai is not None:
            result.next_interval = ai.speed_ctrl.interval
        else:
            result.next_interval = 150

        elapsed_ms = (time.time() - cycle_start) * 1000

        # ── Cycle summary ─────────────────────────────────────────────────
        logger.info(
            "📋 [CYCLE_SUMMARY] cycle=%d | pairs_evaluated=%d | pairs_passed_all_gates=%d | "
            "pairs_submitted=%d | cycle_duration_ms=%.0f | next_cycle_in=%ds | "
            "zero_signal_streak=%d",
            self._total_cycles,
            result.symbols_scored,
            result.entries_taken + result.entries_blocked,
            result.entries_taken,
            elapsed_ms,
            result.next_interval,
            self._zero_signal_streak,
        )

        logger.info(
            "🔄 Core loop complete — scored=%d entered=%d blocked=%d exited=%d "
            "elapsed=%.0fms next=%ds",
            result.symbols_scored,
            result.entries_taken,
            result.entries_blocked,
            result.exits_taken,
            elapsed_ms,
            result.next_interval,
        )

        # ── Periodic execution KPI summary ───────────────────────────────
        if self._total_cycles % CYCLE_SUMMARY_INTERVAL == 0:
            self._log_execution_kpis()

        return result

    # ------------------------------------------------------------------
    # Phase 1: Safety gate
    # ------------------------------------------------------------------

    def _sync_risk_state_for_cycle(self, snapshot: CycleSnapshot) -> None:
        """Refresh risk-state consumers from the same cycle snapshot before scans."""
        try:
            apex = self.apex
            bal = float(snapshot.balance)

            if hasattr(apex, "account_balance"):
                try:
                    setattr(apex, "account_balance", bal)
                except Exception:
                    pass

            _rm = getattr(apex, "risk_manager", None)
            if _rm is not None:
                for _method_name in ("update_balance", "update_account_balance", "set_account_balance"):
                    _method = getattr(_rm, _method_name, None)
                    if callable(_method):
                        try:
                            _method(bal)
                            break
                        except Exception:
                            continue
                if hasattr(_rm, "account_balance"):
                    try:
                        setattr(_rm, "account_balance", bal)
                    except Exception:
                        pass

            for _attr_name in ("global_risk_controller", "_global_risk", "global_risk"):
                _risk_ctrl = getattr(apex, _attr_name, None)
                if _risk_ctrl is not None and callable(getattr(_risk_ctrl, "update_balance", None)):
                    try:
                        _risk_ctrl.update_balance(bal)
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("Risk-state sync skipped: %s", exc)

    def _phase1_safety(self, broker: Any, snapshot: CycleSnapshot) -> Tuple[bool, str]:
        """
        Portfolio-level safety gate — checks only Layers 1 (global drawdown
        circuit breaker) and 2 (daily loss limit).

        Layer 4 (market-condition per-symbol check) is intentionally skipped
        here: it requires real symbol data and is enforced per-symbol inside
        ``apex.analyze_market``.  Passing an empty DataFrame to the controller
        would always return a score of 2/5 (below the threshold of 3) and
        incorrectly block all entries at the portfolio level before any
        symbols have been scanned.

        Receives the cycle-level ``snapshot`` so all state is read from a
        single, consistent, frozen reference rather than re-reading live
        apex attributes mid-cycle.

        Returns (can_enter, reason_string).
        """
        try:
            apex = self.apex
            drc = getattr(apex, "drawdown_risk_ctrl", None)
            if drc is None:
                return True, "no drawdown controller"

            # Pass an empty DataFrame so the controller's Layer 4 market-
            # condition check is bypassed (len(df) < 5 → skip Layer 4).
            # Only Layers 1 + 2 run at this portfolio-wide gate.
            result = drc.pre_entry_check(
                account_balance=snapshot.balance,
                df=pd.DataFrame(),      # empty → Layer 4 skipped (portfolio gate)
                indicators={},
                daily_pnl_usd=snapshot.daily_pnl_usd,
                regime=snapshot.current_regime,
            )
            can_trade = bool(result.can_trade)
            if not result.can_trade:
                return False, result.reason
            return True, "ok"
        except Exception as exc:
            logger.debug("Phase1 safety check error (non-fatal): %s", exc)
            return True, "safety check skipped"

    # ------------------------------------------------------------------
    # Phase 2: Position management
    # ------------------------------------------------------------------

    def _phase2_manage_positions(self, broker: Any, snapshot: CycleSnapshot) -> int:
        """
        Iterate open positions and process exits.

        Receives the cycle-level ``snapshot`` so balance is read from the
        frozen reference captured at cycle start.

        Returns number of positions closed this phase.
        """
        exits = 0
        try:
            apex = self.apex
            ee = getattr(apex, "execution_engine", None)
            if ee is None:
                return 0

            positions = list(getattr(ee, "positions", {}).keys())
            for symbol in positions:
                try:
                    pos = ee.get_position(symbol)
                    if pos is None:
                        continue
                    # Ask apex to analyse the position (manage-only: position exists)
                    # We need a DataFrame; if we can't get one, skip gracefully
                    df = self._fetch_df(broker, symbol)
                    if df is None or len(df) < 10:
                        continue

                    analysis = apex.analyze_market(df, symbol, snapshot.balance)
                    action = analysis.get("action", "hold")
                    if action in ("exit", "partial_exit", "take_profit_tp1",
                                  "take_profit_tp2", "take_profit_tp3"):
                        try:
                            apex.execute_action(analysis, symbol)
                            exits += 1
                        except Exception as exec_err:
                            logger.warning("Phase2 execute_action error for %s: %s", symbol, exec_err)
                except Exception as sym_err:
                    logger.debug("Phase2 position management error for %s: %s", symbol, sym_err)
        except Exception as exc:
            logger.warning("Phase2 position management error: %s", exc)

        return exits

    # ------------------------------------------------------------------
    # Phase 3: Scan, score, rank, enter
    # ------------------------------------------------------------------

    def _phase3_scan_and_enter(
        self,
        broker: Any,
        snapshot: CycleSnapshot,
        symbols: List[str],
        available_slots: int,
        zero_signal_streak: int = 0,
    ) -> Tuple[int, int, int, Dict[str, int]]:
        """
        Score all candidate symbols, rank them, execute top-N.

        Receives the cycle-level ``snapshot`` (captured once in
        ``run_scan_phase``) so all gates see a consistent, frozen view of
        balance, regime, and P&L regardless of how long the scan takes.

        When ``zero_signal_streak`` has reached ``FORCED_ENTRY_STREAK_THRESHOLD``,
        progressive score relaxation activates: each 5-cycle step reduces the
        effective MIN_SCORE_HARD_FLOOR by 10% (step 1), 15% (step 2), or 20%
        (step 3, capped).  Candidates below the relaxed floor are filtered out;
        remaining top-N are force-entered to prevent indefinite idling.

        Returns (entries_taken, entries_blocked, symbols_scored, gate_rejections).
        gate_rejections is a dict mapping gate name → rejection count for this cycle.
        """
        # ── VERBOSE ENTRY LOG: confirm _phase3_scan_and_enter() was reached ──
        print(
            f"[NIJA-PRINT] _phase3_scan_and_enter START | "
            f"cycle_id={getattr(snapshot, 'cycle_id', '?')} "
            f"symbols={len(symbols)} slots={available_slots} "
            f"streak={zero_signal_streak} "
            f"force_trade={_env_truthy('FORCE_TRADE')} "
            f"balance=${float(getattr(snapshot, 'balance', 0.0) or 0.0):.2f} "
            f"regime={getattr(snapshot, 'current_regime', 'unknown')}",
            flush=True,
        )
        logger.critical(
            "🔬 [Phase3] START _phase3_scan_and_enter | cycle_id=%s symbol_count=%d "
            "available_slots=%d zero_signal_streak=%d force_trade=%s "
            "balance=$%.2f regime=%s",
            getattr(snapshot, "cycle_id", "?"),
            len(symbols),
            available_slots,
            zero_signal_streak,
            _env_truthy("FORCE_TRADE"),
            float(getattr(snapshot, "balance", 0.0) or 0.0),
            str(getattr(snapshot, "current_regime", "unknown")),
        )

        # Pre-import AIEngineSignal once; guarded so the fallback path works
        # even when NijaAIEngine is unavailable.
        try:
            from nija_ai_engine import AIEngineSignal as _AISignal
        except ImportError:
            try:
                from bot.nija_ai_engine import AIEngineSignal as _AISignal
            except ImportError:
                _AISignal = None  # type: ignore

        # ── Read profit mode parameters (if available) ────────────────────
        # These override the module-level constants so runtime level changes
        # take effect immediately without restarting.
        _pmc_level = 0
        _effective_hard_floor = MIN_SCORE_HARD_FLOOR
        _effective_streak_threshold = FORCED_ENTRY_STREAK_THRESHOLD
        _effective_bypass_threshold = HARD_BYPASS_STREAK_THRESHOLD
        _volume_fallback_enabled = False
        if _PMC_AVAILABLE and _get_pmc is not None:
            try:
                _pmc_inst = _get_pmc()
                _pmc_params = getattr(_pmc_inst, "market_adjusted_params", _pmc_inst.params)
                _pmc_level = _pmc_params.level
                _effective_hard_floor = _pmc_params.min_score_hard_floor
                _effective_streak_threshold = _pmc_params.forced_entry_streak_threshold
                _effective_bypass_threshold = _pmc_params.hard_bypass_streak_threshold
                _volume_fallback_enabled = _pmc_params.enable_volume_fallback
            except Exception as _exc:
                logger.debug("Phase3: profit mode params read failed — using module defaults: %s", _exc)

        # Dead-zone flag: volume fallback and Momentum-Only Entry Mode are
        # always active once zero_signal_streak reaches DEAD_ZONE_STREAK_THRESHOLD,
        # regardless of profit-mode level.
        _dead_zone = zero_signal_streak >= DEAD_ZONE_STREAK_THRESHOLD
        if _dead_zone:
            _volume_fallback_enabled = True
            logger.warning(
                "🌑 DEAD ZONE detected (streak=%d ≥ %d) — "
                "enabling momentum-only entry mode + volume fallback",
                zero_signal_streak, DEAD_ZONE_STREAK_THRESHOLD,
            )

        ai = self._get_ai_engine()
        if ai is not None and _PMC_AVAILABLE and _get_pmc is not None:
            try:
                _set_floor = getattr(ai, "set_score_floor", None)
                if callable(_set_floor):
                    _set_floor(float(_pmc_params.min_score_absolute))
            except Exception as _exc:
                logger.debug("Phase3: AI score-floor sync failed — continuing with engine default: %s", _exc)

        # ── Broker candle-method diagnostic (logged once per phase3 call) ─
        # Identifies which candle-fetch method the broker exposes so data
        # failures can be diagnosed without enabling debug logging.
        _broker_for_diag = broker if broker is not None else getattr(self.apex, "broker_client", None)
        if _broker_for_diag is not None:
            _candle_methods_present = [
                m for m in ("get_candles", "fetch_ohlcv", "get_ohlcv",
                             "get_historical_data", "get_market_data")
                if callable(getattr(_broker_for_diag, m, None))
            ]
            logger.critical(
                "🔬 [Phase3] BROKER_DIAG | broker_type=%s candle_methods=%s "
                "ai_engine=%s score_floor=%.1f dead_zone=%s streak=%d",
                type(_broker_for_diag).__name__,
                _candle_methods_present or "NONE_FOUND",
                "available" if ai is not None else "UNAVAILABLE",
                getattr(ai, "_score_floor", -1.0) if ai is not None else -1.0,
                _dead_zone,
                zero_signal_streak,
            )
            print(
                f"[NIJA-PRINT] BROKER_DIAG | broker={type(_broker_for_diag).__name__} "
                f"candle_methods={_candle_methods_present} ai={'yes' if ai is not None else 'NO'}",
                flush=True,
            )
            if not _candle_methods_present:
                logger.critical(
                    "🚨 [DIAG] BROKER has NO candle-fetch methods! "
                    "broker=%s — all %d symbols will fail data fetch. "
                    "Expected one of: get_candles, fetch_ohlcv, get_ohlcv, "
                    "get_historical_data, get_market_data",
                    type(_broker_for_diag).__name__, len(symbols),
                )
        else:
            logger.critical(
                "🚨 [DIAG] BROKER IS NONE — no broker available for candle fetching. "
                "All %d symbols will fail data fetch. "
                "Check broker initialization and connection.",
                len(symbols),
            )

        candidates = []        # List[AIEngineSignal | _AISignal]  — AI-scored
        momentum_candidates = []  # collected from relaxed momentum scan
        scored = 0
        blocked = 0

        # ── Per-cycle gate rejection counters ─────────────────────────────
        # Incremented each time a symbol is rejected at a specific gate.
        # Returned to run_scan_phase for the [GATE_REJECTIONS] log line.
        _gate_rejections: Dict[str, int] = {
            "confidence_gate_rejected": 0,
            "adx_gate_rejected": 0,
            "volume_gate_rejected": 0,
            "momentum_filter_rejected": 0,
            "ai_gate_rejected": 0,
            "notional_gate_rejected": 0,
            "capital_gate_rejected": 0,
            "risk_gate_rejected": 0,
            "market_filter_rejected": 0,
            "data_insufficient": 0,
            "indicators_failed": 0,
        }

        # Always-on top-volume tracker (feeds volume fallback for any streak)
        _best_volume_symbol: Optional[str] = None
        _best_volume_side: str = "long"
        _best_volume_entry_type: str = "swing"
        _best_volume: float = -1.0

        # Per-cycle market-health telemetry feeds ProfitModeController so the
        # next cycle automatically tightens during data/API degradation, stays
        # selective during volatility spikes, and loosens only when data is
        # healthy but the market is producing no entries.
        _data_attempts = 0
        _data_successes = 0
        _data_skipped_timeout = 0  # symbols skipped due to broker API timeout/connection error
        _scoring_errors = 0
        _abs_return_sum = 0.0
        _abs_return_count = 0
        _adx_sum = 0.0
        _adx_count = 0
        _volume_pct_sum = 0.0
        _volume_pct_count = 0
        _market_filter_checks = 0
        _market_filter_passes = 0

        # Initialise the per-cycle score distribution debugger snapshot.
        _sdd = _get_sdd() if (_SDD_AVAILABLE and _get_sdd is not None) else None
        if _sdd is not None:
            _sdd.start_cycle()

        # ── Score every symbol ────────────────────────────────────────────
        logger.critical(
            "🔁 [Phase3] SIGNAL_LOOP_START — beginning symbol scoring loop | "
            "symbols_total=%d available_slots=%d ai_engine=%s",
            len(symbols),
            available_slots,
            "available" if ai is not None else "UNAVAILABLE",
        )
        print(
            f"[NIJA-PRINT] SIGNAL_LOOP_START | symbols={len(symbols)} "
            f"slots={available_slots} ai={'yes' if ai is not None else 'NO'}",
            flush=True,
        )
        funnel_traces: Dict[str, Dict[str, Tuple[str, str]]] = {}
        for _symbol_idx, symbol in enumerate(symbols):
            _funnel = funnel_traces.setdefault(symbol, {})
            # ── Per-symbol progress heartbeat (every 10 symbols) ─────────
            if _symbol_idx % 10 == 0:
                _prog_data_fail = _gate_rejections.get("data_insufficient", 0)
                logger.critical(
                    "🔁 [Phase3] SIGNAL_LOOP_PROGRESS — symbol %d/%d | "
                    "symbol=%s candidates_so_far=%d scored_so_far=%d "
                    "data_ok=%d data_fail=%d timeout_skipped=%d blocked_so_far=%d",
                    _symbol_idx + 1,
                    len(symbols),
                    symbol,
                    len(candidates),
                    scored,
                    _data_successes,
                    _prog_data_fail,
                    _data_skipped_timeout,
                    blocked,
                )
                print(
                    f"[NIJA-PRINT] SIGNAL_LOOP_PROGRESS | "
                    f"idx={_symbol_idx + 1}/{len(symbols)} sym={symbol} "
                    f"candidates={len(candidates)} scored={scored} "
                    f"data_ok={_data_successes} data_fail={_prog_data_fail} "
                    f"timeout_skipped={_data_skipped_timeout} blocked={blocked}",
                    flush=True,
                )
            # Cap: stop scoring once we have 10× the available slots — enough
            # diversity to find the top-N without scanning every symbol when the
            # market has 700+ pairs.
            if len(candidates) >= available_slots * 10:
                if _sdd is not None:
                    _sdd.record_skip(symbol, "cap_reached")
                _funnel.setdefault("signal", ("FAIL", "CAP_REACHED"))
                for _remaining_symbol in symbols[_symbol_idx + 1:]:
                    _remaining_funnel = funnel_traces.setdefault(_remaining_symbol, {})
                    _remaining_funnel.setdefault("signal", ("FAIL", "CAP_REACHED"))
                break

            try:
                _data_attempts += 1
                # Check session quarantine before fetching — symbols that have
                # repeatedly failed data fetches are skipped for the rest of the
                # session to avoid wasting cycle time.
                _qkey = f"{str(getattr(getattr(broker, 'broker_type', None), 'value', '') or '').lower()}:{symbol}"
                with _DATA_FAILURE_QUARANTINE_LOCK:
                    _fail_count = _DATA_FAILURE_QUARANTINE.get(_qkey, 0)
                if _fail_count >= _DATA_FAILURE_QUARANTINE_THRESHOLD:
                    if _sdd is not None:
                        _sdd.record_skip(symbol, "quarantine_data_failure")
                    _funnel["market_data"] = ("FAIL", "QUARANTINE_DATA_FAILURE")
                    _gate_rejections["data_insufficient"] += 1
                    continue
                df = self._fetch_df(broker, symbol)
                _df_len = len(df) if df is not None else 0
                # Minimum candle requirement: lowered from 100 → 50 so symbols
                # with shorter history still get scored.  Indicators need at
                # least 50 candles (EMA-50 is the longest-period indicator).
                _MIN_CANDLES = 50
                if df is None or _df_len < _MIN_CANDLES:
                    if _sdd is not None:
                        _sdd.record_skip(symbol, "data_insufficient")
                    # Increment quarantine failure counter for this symbol
                    with _DATA_FAILURE_QUARANTINE_LOCK:
                        _DATA_FAILURE_QUARANTINE[_qkey] = _DATA_FAILURE_QUARANTINE.get(_qkey, 0) + 1
                        _new_fail_count = _DATA_FAILURE_QUARANTINE[_qkey]
                    # df is None specifically indicates a timeout or connection
                    # error (broker returned nothing at all vs. too-short data).
                    if df is None:
                        _data_skipped_timeout += 1
                        _funnel["market_data"] = ("FAIL", "DATA_TIMEOUT_OR_EMPTY")
                    else:
                        _funnel["market_data"] = ("FAIL", "DATA_INSUFFICIENT")
                    _gate_rejections["data_insufficient"] += 1
                    # Log the first 3 data failures at critical level so the
                    # root cause is visible even when debug logging is off.
                    # Log when a symbol gets quarantined.
                    if _new_fail_count == _DATA_FAILURE_QUARANTINE_THRESHOLD:
                        logger.warning(
                            "🚫 [Phase3] DATA_FAILURE_QUARANTINE symbol=%s qkey=%s "
                            "fail_count=%d — quarantined for this session",
                            symbol, _qkey, _new_fail_count,
                        )
                    elif _gate_rejections["data_insufficient"] <= 3:
                        logger.critical(
                            "🚨 [DIAG] DATA_INSUFFICIENT symbol=%s df_len=%d "
                            "(need>=%d) df_is_none=%s — broker returned no/short data "
                            "(timeout_skipped_so_far=%d). "
                            "Signal loop skipping symbol and continuing. "
                            "data_insufficient_count=%d/%d fail_count_for_symbol=%d",
                            symbol, _df_len, _MIN_CANDLES, df is None,
                            _data_skipped_timeout,
                            _gate_rejections["data_insufficient"], _data_attempts,
                            _new_fail_count,
                        )
                    continue
                _data_successes += 1
                try:
                    if "close" in df.columns:
                        _returns = df["close"].pct_change().dropna().tail(20).abs() * 100.0
                        if len(_returns) > 0:
                            _abs_return_sum += float(_returns.mean())
                            _abs_return_count += 1
                except Exception:
                    pass
                _funnel["market_data"] = ("PASS", "")

                # Always track top-volume symbol (feeds volume fallback)
                if "volume" in df.columns:
                    try:
                        avg_vol = float(df["volume"].tail(20).mean())
                        if avg_vol > _best_volume:
                            _best_volume = avg_vol
                            _best_volume_symbol = symbol
                    except Exception:
                        pass

                indicators = self.apex.calculate_indicators(df)
                if not indicators:
                    if _sdd is not None:
                        _sdd.record_skip(symbol, "indicators_failed")
                    _funnel["signal"] = ("FAIL", "INDICATORS_FAILED")
                    _gate_rejections["indicators_failed"] += 1
                    if _gate_rejections["indicators_failed"] <= 3:
                        logger.critical(
                            "🚨 [DIAG] INDICATORS_FAILED symbol=%s df_len=%d — "
                            "calculate_indicators returned empty dict. "
                            "Check OHLCV column types and indicator calculation errors.",
                            symbol, _df_len,
                        )
                    continue

                # Determine trend from apex market filter
                try:
                    allow, trend, market_reason = self.apex.check_market_filter(df, indicators)
                    allow, trend, market_reason, *_market_filter_extra = self.apex.check_market_filter(
                        df, indicators
                    )
                    _market_filter_checks += 1
                    if not allow:
                        blocked += 1
                        if _sdd is not None:
                            _sdd.record_skip(symbol, "market_filter")
                        _funnel["regime"] = ("FAIL", market_reason or "MARKET_FILTER_BLOCKED")
                        _gate_rejections["market_filter_rejected"] += 1
                        # Log first 3 market-filter blocks at critical level
                        if blocked <= 3:
                            logger.critical(
                                "🚨 [DIAG] MARKET_FILTER_BLOCKED symbol=%s reason=%s "
                                "blocked_count=%d",
                                symbol, market_reason, blocked,
                            )
                        continue
                    _market_filter_passes += 1
                    _funnel["regime"] = ("PASS", "")
                except Exception as _mf_exc:
                    trend = "uptrend"
                    _funnel["regime"] = ("PASS", "MARKET_FILTER_FALLBACK")
                    _market_filter_checks += 1
                    _market_filter_passes += 1
                    logger.debug("check_market_filter exception for %s: %s", symbol, _mf_exc)

                side = "long" if trend == "uptrend" else "short"
                entry_type = (
                    self.apex._get_entry_type_for_regime(snapshot.current_regime)
                    if hasattr(self.apex, "_get_entry_type_for_regime")
                    else "swing"
                )
                broker_name = (
                    self.apex._get_broker_name()
                    if hasattr(self.apex, "_get_broker_name")
                    else "coinbase"
                )

                # Update top-volume side/entry_type to match the best symbol's context
                if symbol == _best_volume_symbol:
                    _best_volume_side = side
                    _best_volume_entry_type = entry_type

                # ── Extract per-pair diagnostic values ────────────────────
                # Read ADX, volume%, and confidence (composite score) from
                # indicators/df so they can be logged regardless of pass/fail.
                _diag_adx: float = 0.0
                _diag_vol_pct: float = 0.0
                _diag_confidence: float = 0.0
                _diag_momentum_pass: Optional[bool] = None
                try:
                    _adx_series = indicators.get("adx", None)
                    if _adx_series is not None and hasattr(_adx_series, "iloc") and len(_adx_series) > 0:
                        _diag_adx = float(_adx_series.iloc[-1])
                        _adx_sum += _diag_adx
                        _adx_count += 1
                except Exception:
                    pass
                try:
                    if "volume" in df.columns and len(df) >= 21:
                        _cur_vol = float(df["volume"].iloc[-1])
                        _avg_vol = float(df["volume"].iloc[-21:-1].mean())
                        if _avg_vol > 0:
                            _diag_vol_pct = (_cur_vol / _avg_vol - 1.0) * 100.0
                            _volume_pct_sum += _diag_vol_pct
                            _volume_pct_count += 1
                except Exception:
                    pass

                # ── Standard AI scoring ───────────────────────────────────
                if ai is not None:
                    logger.critical(
                        "🔎 [Phase3] EVALUATING_MARKET | symbol=%s side=%s "
                        "regime=%s entry_type=%s idx=%d/%d",
                        symbol, side,
                        str(getattr(snapshot, "current_regime", "unknown")),
                        entry_type,
                        _symbol_idx + 1,
                        len(symbols),
                    )
                    sig = ai.evaluate_symbol(
                        df=df,
                        indicators=indicators,
                        side=side,
                        regime=snapshot.current_regime,
                        broker=broker_name,
                        entry_type=entry_type,
                        symbol=symbol,
                    )
                    if sig is not None:
                        _diag_confidence = sig.composite_score
                        # Check whether the selected venue is actually live-executable
                        # before logging SIGNAL_PASSED.  A signal routed to a disabled
                        # broker (e.g. OKX when live execution is off) cannot be
                        # executed and must not appear as a tradeable candidate.
                        _venue_blocked = False
                        if str(broker_name or "").lower() == "okx":
                            _okx_exec_vars = (
                                "NIJA_OKX_EXECUTION_ENABLED",
                                "NIJA_OKX_LIVE_TRADING_ENABLED",
                                "OKX_LIVE_TRADING_ENABLED",
                                "NIJA_ENABLE_OKX_EXECUTION",
                            )
                            _okx_enabled = any(
                                os.environ.get(v, "").lower() in ("1", "true", "yes")
                                for v in _okx_exec_vars
                            )
                            if not _okx_enabled:
                                _venue_blocked = True
                        if _venue_blocked:
                            _funnel["signal"] = ("FAIL", "VENUE_DISABLED")
                            logger.warning(
                                "🚫 [Phase3] SIGNAL_BLOCKED_VENUE_DISABLED — %s score=%.1f "
                                "broker=%s (venue disabled for live execution)",
                                symbol, sig.composite_score, broker_name,
                            )
                        else:
                            _funnel["signal"] = ("PASS", "")
                            logger.critical(
                                "✅ [Phase3] SIGNAL_PASSED — %s score=%.1f threshold=%.1f "
                                "side=%s entry_type=%s",
                                symbol, sig.composite_score, sig.threshold_used,
                                side, entry_type,
                            )
                            # ── Per-pair evaluation log (PASS) ────────────────
                            logger.info(
                                "🔬 [PAIR_EVAL] pair=%s | side=%s | confidence=%.2f | "
                                "adx=%.1f | vol_pct=%.1f%% | momentum=%s | "
                                "gate=PASS | entry_score=%.1f | threshold=%.1f",
                                symbol, side, sig.composite_score,
                                _diag_adx, _diag_vol_pct,
                                "pass",
                                sig.composite_score, sig.threshold_used,
                            )
                            candidates.append(sig)
                    else:
                        _funnel["signal"] = ("FAIL", "RSI_BELOW_THRESHOLD")
                        # Determine which sub-gate caused the rejection by
                        # inspecting the score breakdown from a lightweight
                        # re-evaluation of the composite components.
                        _reject_gate = "confidence_gate"
                        try:
                            _breakdown = ai._compute_composite(
                                df, indicators, side,
                                snapshot.current_regime, broker_name, entry_type,
                            )[1]
                            _diag_confidence = float(_breakdown.get("composite_score", 0.0))
                            _raw_enhanced = float(_breakdown.get("enhanced_score", 0.0))
                            _score_breakdown = _breakdown.get("score_breakdown", {})
                            _adx_sub = float(_score_breakdown.get("trend_strength", 0.0)) if _score_breakdown else 0.0
                            _vol_sub = float(_score_breakdown.get("volume", 0.0)) if _score_breakdown else 0.0
                            _rsi_sub = float(_score_breakdown.get("dual_rsi", 0.0)) if _score_breakdown else 0.0
                            # Classify the primary rejection gate based on
                            # which sub-score is most deficient relative to
                            # its weight contribution.
                            if _adx_sub < 3.0:
                                _reject_gate = "adx_gate"
                                _gate_rejections["adx_gate_rejected"] += 1
                            elif _vol_sub < 3.0:
                                _reject_gate = "volume_gate"
                                _gate_rejections["volume_gate_rejected"] += 1
                            elif _rsi_sub < 5.0:
                                _reject_gate = "momentum_filter"
                                _gate_rejections["momentum_filter_rejected"] += 1
                            else:
                                _reject_gate = "confidence_gate"
                                _gate_rejections["confidence_gate_rejected"] += 1
                        except Exception:
                            _gate_rejections["confidence_gate_rejected"] += 1
                        # ── Per-pair evaluation log (FAIL) ────────────────
                        logger.info(
                            "🔬 [PAIR_EVAL] pair=%s | side=%s | confidence=%.2f | "
                            "adx=%.1f | vol_pct=%.1f%% | momentum=%s | "
                            "gate=FAIL | rejected_by=%s | entry_score=%.2f",
                            symbol, side, _diag_confidence,
                            _diag_adx, _diag_vol_pct,
                            "n/a",
                            _reject_gate, _diag_confidence,
                        )
                elif _AISignal is not None:
                    # Fallback: use apex.analyze_market directly and wrap result
                    logger.critical(
                        "⚠️ [Phase3] AI_ENGINE_UNAVAILABLE — using apex.analyze_market "
                        "fallback for symbol=%s (ai=None, _AISignal=available)",
                        symbol,
                    )
                    analysis = self.apex.analyze_market(df, symbol, snapshot.balance)
                    if analysis.get("action") in ("enter_long", "enter_short"):
                        _funnel["signal"] = ("PASS", "")
                        sig = _AISignal(
                            symbol=symbol,
                            side=side,
                            composite_score=50.0,
                            position_multiplier=1.0,
                            entry_type=entry_type,
                            threshold_used=25.0,
                            reason=analysis.get("reason", "apex signal"),
                            metadata={"apex_analysis": analysis},
                        )
                        logger.info(
                            "🔬 [PAIR_EVAL] pair=%s | side=%s | confidence=%.2f | "
                            "adx=%.1f | vol_pct=%.1f%% | momentum=%s | "
                            "gate=PASS | entry_score=%.1f | threshold=%.1f",
                            symbol, side, 50.0,
                            _diag_adx, _diag_vol_pct,
                            "pass",
                            50.0, 25.0,
                        )
                        candidates.append(sig)
                    else:
                        _apex_reject_reason = analysis.get("reason", "NO_ENTRY_SIGNAL")
                        _funnel["signal"] = ("FAIL", _apex_reject_reason)
                        _gate_rejections["confidence_gate_rejected"] += 1
                        logger.info(
                            "🔬 [PAIR_EVAL] pair=%s | side=%s | confidence=%.2f | "
                            "adx=%.1f | vol_pct=%.1f%% | momentum=%s | "
                            "gate=FAIL | rejected_by=confidence_gate | reason=%s",
                            symbol, side, 0.0,
                            _diag_adx, _diag_vol_pct,
                            "n/a",
                            _apex_reject_reason,
                        )

                # ── Momentum-Only Entry Mode (dead zone) ──────────────────
                # When in a dead zone run the lightweight relaxed momentum
                # checker on every symbol.  Passing symbols are collected as
                # B/C grade candidates (score pinned to TIER_FLOOR) regardless
                # of whether they passed the full AI scoring above.
                if _dead_zone and _MOMENTUM_FILTER_AVAILABLE and _AISignal is not None:
                    try:
                        if side == "long" and _check_mom_long_relaxed is not None:
                            mom_ok, mom_score, mom_reason = _check_mom_long_relaxed(df, indicators)
                        elif side == "short" and _check_mom_short_relaxed is not None:
                            mom_ok, mom_score, mom_reason = _check_mom_short_relaxed(df, indicators)
                        else:
                            mom_ok = False
                        _diag_momentum_pass = bool(mom_ok)
                        if not mom_ok:
                            _gate_rejections["momentum_filter_rejected"] += 1
                        if mom_ok:
                            momentum_candidates.append(_AISignal(
                                symbol=symbol,
                                side=side,
                                composite_score=_effective_hard_floor,
                                position_multiplier=0.75,   # B/C grade — reduced size
                                entry_type="momentum",
                                threshold_used=_effective_hard_floor,
                                reason=f"[MOMENTUM_ONLY] {mom_reason}",
                                metadata={
                                    "dead_zone": True,
                                    "momentum_score": mom_score,
                                    "bypass_low_quality": True,
                                    "weak_signal_entry": True,
                                },
                            ))
                    except Exception as _me:
                        logger.debug("Momentum-Only check failed for %s: %s", symbol, _me)

                scored += 1

            except Exception as sym_err:
                _scoring_errors += 1
                logger.debug("Phase3 scoring error for %s: %s", symbol, sym_err)
                if _sdd is not None:
                    _sdd.record_skip(symbol, "exception")
                _funnel["signal"] = ("FAIL", f"SCORING_EXCEPTION:{sym_err}")

        # ── Signal generation loop complete ───────────────────────────────
        _data_insuff_end = _gate_rejections.get("data_insufficient", 0)
        _indic_fail_end  = _gate_rejections.get("indicators_failed", 0)
        logger.critical(
            "🔁 [Phase3] SIGNAL_LOOP_END — symbol scoring loop finished | "
            "symbols_total=%d scored=%d candidates=%d momentum_candidates=%d "
            "blocked=%d scoring_errors=%d data_insufficient=%d indicators_failed=%d "
            "data_attempts=%d data_successes=%d timeout_skipped=%d",
            len(symbols),
            scored,
            len(candidates),
            len(momentum_candidates),
            blocked,
            _scoring_errors,
            _data_insuff_end,
            _indic_fail_end,
            _data_attempts,
            _data_successes,
            _data_skipped_timeout,
        )
        print(
            f"[NIJA-PRINT] SIGNAL_LOOP_END | symbols={len(symbols)} scored={scored} "
            f"candidates={len(candidates)} momentum={len(momentum_candidates)} "
            f"blocked={blocked} errors={_scoring_errors} "
            f"data_insufficient={_data_insuff_end} indicators_failed={_indic_fail_end} "
            f"data_attempts={_data_attempts} data_successes={_data_successes} "
            f"timeout_skipped={_data_skipped_timeout}",
            flush=True,
        )
        # Diagnose timeout-skipped symbols — visible even when some symbols scored OK
        if _data_skipped_timeout > 0:
            logger.critical(
                "⏱️ [DIAG] TIMEOUT_SKIPPED: %d/%d symbols returned None from broker "
                "(API timeout or connection error). Signal loop skipped these symbols "
                "and continued scanning. Check Kraken API connectivity. "
                "Set NIJA_KRAKEN_OHLC_TIMEOUT / NIJA_CANDLE_FETCH_TIMEOUT to adjust.",
                _data_skipped_timeout, _data_attempts,
            )

        # Diagnose the most common failure mode: all symbols failing data fetch
        if scored == 0 and _data_attempts > 0:
            if _data_insuff_end == _data_attempts:
                logger.critical(
                    "🚨 [DIAG] ZERO_SCORED: ALL %d data fetches returned insufficient data "
                    "(None or <50 rows). Root cause: broker candle API returning empty/short "
                    "DataFrames. Check broker method names, symbol format, and API connectivity. "
                    "Broker methods tried: get_candles, fetch_ohlcv, get_ohlcv, "
                    "get_historical_data, get_market_data",
                    _data_attempts,
                )
            elif _indic_fail_end > 0:
                logger.critical(
                    "🚨 [DIAG] ZERO_SCORED: %d/%d symbols failed indicator calculation. "
                    "Check that OHLCV columns (open/high/low/close/volume) are present and numeric.",
                    _indic_fail_end, _data_attempts,
                )
            elif blocked == _data_successes:
                logger.critical(
                    "🚨 [DIAG] ZERO_SCORED: All %d symbols with valid data were blocked by "
                    "market_filter. Market may be in a flat/choppy regime with no directional "
                    "conditions met. Consider lowering min_adx or volume_threshold.",
                    blocked,
                )

        if _PMC_AVAILABLE and _get_pmc is not None and _MarketConditionSnapshot is not None:
            try:
                _data_success_rate = (
                    float(_data_successes) / float(_data_attempts)
                    if _data_attempts > 0
                    else 1.0
                )
                _candidate_rate = (
                    float(len(candidates) + len(momentum_candidates)) / float(max(1, scored))
                    if scored > 0
                    else 0.0
                )
                _avg_abs_return_pct = (
                    _abs_return_sum / float(_abs_return_count)
                    if _abs_return_count > 0
                    else 0.0
                )
                _avg_adx = _adx_sum / float(_adx_count) if _adx_count > 0 else 0.0
                _avg_volume_pct = (
                    _volume_pct_sum / float(_volume_pct_count)
                    if _volume_pct_count > 0
                    else 0.0
                )
                _market_filter_pass_rate = (
                    float(_market_filter_passes) / float(_market_filter_checks)
                    if _market_filter_checks > 0
                    else 1.0
                )
                _api_error_rate = float(_scoring_errors) / float(max(1, _data_attempts))
                _get_pmc().update_market_conditions(
                    _MarketConditionSnapshot(
                        data_success_rate=_data_success_rate,
                        candidate_rate=_candidate_rate,
                        avg_abs_return_pct=_avg_abs_return_pct,
                        zero_signal_streak=zero_signal_streak,
                        api_error_rate=_api_error_rate,
                        avg_adx=_avg_adx,
                        avg_volume_pct=_avg_volume_pct,
                        market_filter_pass_rate=_market_filter_pass_rate,
                    )
                )
                _pmc_params = getattr(_get_pmc(), "market_adjusted_params", _pmc_params)
                _pmc_level = _pmc_params.level
                _effective_hard_floor = _pmc_params.min_score_hard_floor
                _effective_streak_threshold = _pmc_params.forced_entry_streak_threshold
                _effective_bypass_threshold = _pmc_params.hard_bypass_streak_threshold
                _volume_fallback_enabled = _pmc_params.enable_volume_fallback
                if ai is not None:
                    _set_floor = getattr(ai, "set_score_floor", None)
                    if callable(_set_floor):
                        _set_floor(float(_pmc_params.min_score_absolute))
            except Exception as _market_adj_err:
                logger.debug("Market-adaptive parameter update failed: %s", _market_adj_err)

        # ── Merge momentum candidates when AI candidates are scarce ──────
        # If we're in dead-zone mode and have fewer AI candidates than slots,
        # pad from the momentum list (highest-score first) up to available_slots.
        if _dead_zone and momentum_candidates and len(candidates) < available_slots:
            # Deduplicate — don't add a momentum candidate for a symbol already
            # represented in the AI-scored list.
            existing_symbols = {s.symbol for s in candidates}
            new_mom = [s for s in momentum_candidates if s.symbol not in existing_symbols]
            # Sort by score descending, take as many as needed to fill slots
            new_mom.sort(key=lambda s: s.composite_score, reverse=True)
            slots_needed = available_slots - len(candidates)
            candidates.extend(new_mom[:slots_needed])
            if new_mom:
                logger.warning(
                    "🔥 MOMENTUM-ONLY MODE — injecting %d/%d momentum candidates "
                    "(streak=%d, slots_needed=%d)",
                    min(len(new_mom), slots_needed), len(new_mom),
                    zero_signal_streak, slots_needed,
                )

        # ── One-cycle forced entry (FORCE_NEXT_CYCLE flag) ───────────────
        # Read before the no-candidates return path.  Previously this flag was
        # consumed after the empty-candidate early return, so FORCE_TRADE/ATM
        # could be armed yet never produce a tradable candidate.
        global FORCE_NEXT_CYCLE
        with _FORCE_LOCK:
            _force_this_cycle = FORCE_NEXT_CYCLE
            if _force_this_cycle:
                FORCE_NEXT_CYCLE = False  # reset atomically — one-shot only
        if _force_this_cycle:
            _volume_fallback_enabled = True

        # ── Volume fallback: inject top-volume candidate when still empty ─
        # Active whenever _volume_fallback_enabled (always true in dead zone;
        # also true for profit-mode Level 3) or one-cycle force is armed.
        if not candidates and (_volume_fallback_enabled or _force_this_cycle) and _best_volume_symbol and _AISignal is not None:
            logger.warning(
                "💰 VOLUME FALLBACK — no candidates after momentum scan; "
                "injecting highest-volume symbol: %s (avg_vol=%.0f)",
                _best_volume_symbol, _best_volume,
            )
            fallback_sig = _AISignal(
                symbol=_best_volume_symbol,
                side=_best_volume_side,
                composite_score=_effective_hard_floor,
                position_multiplier=0.25 if _force_this_cycle else 0.50,  # conservative micro-trade size
                entry_type=_best_volume_entry_type,
                threshold_used=_effective_hard_floor,
                reason="volume_fallback_guaranteed_activity",
                metadata={
                    "profit_mode_level": _pmc_level,
                    "volume_fallback": True,
                    "force_next_cycle": bool(_force_this_cycle),
                    "avg_volume": _best_volume,
                    "bypass_low_quality": True,
                    "dead_zone": _dead_zone,
                },
            )
            candidates.append(fallback_sig)

        logger.critical(
            "🎯 [Phase3] CANDIDATES FOUND: %d candidate(s) from %d scored symbols "
            "(blocked=%d dead_zone=%s force_this_cycle=%s force_trade=%s)",
            len(candidates),
            scored,
            blocked,
            _dead_zone,
            _force_this_cycle,
            _env_truthy("FORCE_TRADE"),
        )
        if candidates:
            logger.critical(
                "🎯 [Phase3] SIGNALS SCORED: %d signal(s) — %s",
                len(candidates),
                ", ".join(
                    f"{getattr(s, 'symbol', '?')}({getattr(s, 'side', '?')} score={getattr(s, 'composite_score', 0):.1f})"
                    for s in candidates
                ),
            )

        # ── Record scan-cycle result in funnel tracker ────────────────────
        if _FUNNEL_TRACKER_AVAILABLE and _get_funnel_tracker is not None:
            try:
                _get_funnel_tracker().record(
                    candidates_found=len(candidates),
                    symbols_scored=scored,
                    regime=str(snapshot.current_regime or "unknown"),
                )
            except Exception as _ftr_err:
                logger.debug("scanner_funnel_tracker.record failed: %s", _ftr_err)

        # ── Rank and select top-N ─────────────────────────────────────────
        # ── FORCE_TRADE: inject volume fallback even when candidates is empty ──
        # When FORCE_TRADE is active and no candidates survived scoring, inject
        # the best-volume symbol directly so the no-candidates early return is
        # bypassed and execute_action() is still called this cycle.
        _force_trade_active_early = (
            _env_truthy("FORCE_TRADE")
            or _env_truthy("FORCE_TRADE_MODE")
            or _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
            or _env_truthy("NIJA_FORCE_ACTIVATION")
        )
        if not candidates and _force_trade_active_early and _best_volume_symbol and _AISignal is not None:
            logger.critical(
                "⚡ [FORCE_TRADE] No candidates after full scan — injecting best-volume "
                "symbol %s as forced candidate to ensure execute_action() is called "
                "(scored=%d blocked=%d streak=%d)",
                _best_volume_symbol, scored, blocked, zero_signal_streak,
            )
            _forced_sig = _AISignal(
                symbol=_best_volume_symbol,
                side=_best_volume_side,
                composite_score=max(_effective_hard_floor, 1.0),
                position_multiplier=0.25,
                entry_type=_best_volume_entry_type,
                threshold_used=max(_effective_hard_floor, 1.0),
                reason="force_trade_no_candidates_fallback",
                metadata={
                    "force_trade_fallback": True,
                    "bypass_low_quality": True,
                    "bypass_quality_filter": True,
                    "volume_fallback": True,
                    "avg_volume": _best_volume,
                    "dead_zone": _dead_zone,
                    "zero_signal_streak": zero_signal_streak,
                },
            )
            candidates.append(_forced_sig)

        if not candidates:
            logger.critical(
                "🔍 [Phase3] NO CANDIDATES: scored=%d symbols, no candidates above floor=%.0f "
                "(force_trade=%s best_volume_symbol=%s ai_signal_available=%s)",
                scored, _effective_hard_floor,
                _force_trade_active_early,
                _best_volume_symbol or "none",
                _AISignal is not None,
            )
            if _sdd is not None:
                _sdd.emit_histogram(
                    entries_taken=0,
                    candidates_found=0,
                    rank_threshold=None,
                )
            if ai is not None:
                ai.speed_ctrl.record_cycle(0)
            return 0, blocked, scored, _gate_rejections

        selected = (
            ai.rank_and_select(candidates, available_slots, snapshot.current_regime)
            if ai is not None
            else candidates[:available_slots]
        )
        logger.critical(
            "🎯 [Phase3] SIGNALS SELECTED: %d candidate(s) ranked from %d total — "
            "symbols=%s",
            len(selected),
            len(candidates),
            ", ".join(
                f"{getattr(s, 'symbol', '?')}({getattr(s, 'side', '?')} score={getattr(s, 'composite_score', 0):.1f})"
                for s in selected
            ) or "none",
        )

        # ── FORCE_TRADE rescue: rank_and_select returned empty despite candidates ──
        # rank_and_select can return [] when all candidates score below the adaptive
        # threshold.  When FORCE_TRADE is active, force the top-scored candidate in
        # so execute_action() is always called rather than silently skipping the cycle.
        if not selected and candidates and _force_trade_active_early:
            top_candidate = max(candidates, key=lambda s: s.composite_score)
            top_candidate.metadata["bypass_quality_filter"] = True
            top_candidate.metadata["force_trade_rescue"] = True
            top_candidate.metadata["bypass_low_quality"] = True
            selected = [top_candidate]
            logger.critical(
                "⚡ [FORCE_TRADE] rank_and_select returned empty — rescuing top "
                "candidate %s (score=%.1f) to ensure execute_action() is called "
                "(candidates=%d streak=%d)",
                top_candidate.symbol,
                top_candidate.composite_score,
                len(candidates),
                zero_signal_streak,
            )

        # ── Progressive relaxation: activate after too many zero-signal cycles ──
        # Each 3-cycle step reduces the effective floor by 15% / 25% / 40%.
        _relaxation = _get_relaxation_factor_with_threshold(
            zero_signal_streak, _effective_streak_threshold
        )
        fallback_active = _relaxation > 0.0
        if fallback_active:
            _step = _get_relaxation_step_with_threshold(
                zero_signal_streak, _effective_streak_threshold
            )
            _relaxed_floor = _effective_hard_floor * (1.0 - _relaxation)
            logger.warning(
                "⚡ PROGRESSIVE RELAXATION step=%d/%d "
                "(streak=%d factor=%.0f%% floor=%.1f→%.1f) — top-%d eligible",
                _step, MAX_RELAXATION_STEPS,
                zero_signal_streak, _relaxation * 100,
                _effective_hard_floor, _relaxed_floor,
                _SNIPER_TOP_N_DEFAULT,
            )
            # Filter to candidates above the relaxed floor, then take top-N
            eligible = [s for s in selected if s.composite_score >= _relaxed_floor]
            selected = eligible[:_SNIPER_TOP_N_DEFAULT]
            for sig in selected:
                sig.metadata["bypass_low_quality"] = True
                sig.metadata["relaxation_factor"] = _relaxation
                sig.metadata["relaxation_step"] = _step
                sig.metadata["fallback_streak"] = zero_signal_streak

        # ── Hard bypass: consecutive zero-signal cycles → accept best available ──
        # Threshold uses profit mode value so Level 2/3 bypass sooner.
        if zero_signal_streak >= _effective_bypass_threshold:
            if not selected and candidates:
                # Quality floors filtered everything — pick the single best candidate
                top_candidate = max(candidates, key=lambda s: s.composite_score)
                selected = [top_candidate]
                logger.warning(
                    "🚨 HARD BYPASS activated (streak=%d ≥ %d) — quality floor "
                    "bypassed, forcing top candidate %s (score=%.1f)",
                    zero_signal_streak, _effective_bypass_threshold,
                    top_candidate.symbol, top_candidate.composite_score,
                )
            fallback_active = True  # ensure forced-entry path runs for selected signals
            for sig in selected:
                sig.metadata["bypass_quality_filter"] = True
                sig.metadata["hard_bypass_streak"] = zero_signal_streak

        # ── One-cycle forced entry (FORCE_NEXT_CYCLE flag) ───────────────
        # When FORCE_NEXT_CYCLE is True the top-scored candidate is selected
        # unconditionally, all quality filters are bypassed, and the flag has
        # already been atomically reset before the no-candidate return path.
        if _force_this_cycle and candidates:
            top_candidate = max(candidates, key=lambda s: s.composite_score)
            top_candidate.metadata["bypass_quality_filter"] = True
            top_candidate.metadata["hard_bypass_streak"] = zero_signal_streak
            for c in candidates:
                logger.info(
                    "🔹 Candidate: %s | Score: %.1f",
                    getattr(c, "symbol", "UNKNOWN"),
                    c.composite_score,
                )
            logger.warning(
                "🚀 FORCE_NEXT_CYCLE active — forcing entry on top candidate "
                "%s (score=%.1f, streak=%d)",
                top_candidate.symbol,
                top_candidate.composite_score,
                zero_signal_streak,
            )
            selected = [top_candidate]
            fallback_active = True  # ensure the execution block forces the action

        # ── FORCE_TRADE / NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK bypass ───────
        # When an operator override flag is active, force fallback_active=True
        # so that analyze_market() returning 'hold' (due to candle-close gate,
        # smart filters, market filter, etc.) does NOT silently block the entry.
        # Without this, signals are generated (scores logged) but execute_action()
        # is never called because analyze_market() returns 'hold' and fallback_active
        # is False (zero_signal_streak resets to 0 when candidates are found).
        # This is the root cause of the "6000+ cycles, zero trades" condition.
        #
        # NOTE: After 6000+ cycles, fallback_active is ALWAYS True (progressive
        # relaxation activates at streak ≥ 2), so the previous `not fallback_active`
        # guard silently prevented this block from ever running.  The condition is
        # now unconditional when FORCE_TRADE is set and candidates are selected —
        # fallback_active is set to True regardless of its current value, and an
        # explicit INFO log confirms execute_action() will be called for each signal.
        _force_trade_bypass = (
            _env_truthy("FORCE_TRADE")
            or _env_truthy("FORCE_TRADE_MODE")
            or _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
            or _env_truthy("NIJA_FORCE_ACTIVATION")
        )
        if _force_trade_bypass and selected:
            if not fallback_active:
                fallback_active = True
                logger.warning(
                    "⚡ FORCE_TRADE bypass: fallback_active forced True for %d selected candidate(s) "
                    "— analyze_market() 'hold' responses will be overridden to force entry.",
                    len(selected),
                )
            # Always log signal count and confirm execute_action() path when FORCE_TRADE is active.
            logger.warning(
                "⚡ [FORCE_TRADE] %d signal(s) selected — fallback_active=%s. "
                "execute_action() WILL be called for each signal this cycle. "
                "Signals: %s",
                len(selected),
                fallback_active,
                ", ".join(
                    f"{getattr(s, 'symbol', '?')}({getattr(s, 'side', '?')} score={getattr(s, 'composite_score', 0):.1f})"
                    for s in selected
                ),
            )

        # ── Execute selected entries ──────────────────────────────────────
        logger.critical(
            "🚦 [Phase3] Entering execution loop — selected=%d fallback_active=%s "
            "force_trade=%s zero_signal_streak=%d",
            len(selected),
            fallback_active,
            _force_trade_bypass,
            zero_signal_streak,
        )
        if not selected:
            logger.critical(
                "⚠️ [Phase3] selected is EMPTY — no signals to execute. "
                "candidates=%d scored=%d blocked=%d force_trade=%s",
                len(candidates),
                scored,
                blocked,
                _force_trade_active_early,
            )
        entries = 0
        for sig in selected:
            if entries >= MAX_ENTRIES_PER_CYCLE:
                break
            logger.critical(
                "⚡ [Phase3] EXECUTING SIGNAL %d/%d — symbol=%s side=%s score=%.1f "
                "fallback_active=%s force_trade=%s",
                entries + 1,
                len(selected),
                getattr(sig, "symbol", "UNKNOWN"),
                getattr(sig, "side", "UNKNOWN"),
                getattr(sig, "composite_score", 0.0),
                fallback_active,
                _force_trade_active_early,
            )
            try:
                _funnel = funnel_traces.setdefault(sig.symbol, {})
                df = self._fetch_df(broker, sig.symbol)
                if df is None or len(df) < 100:
                    _funnel["market_data"] = ("FAIL", "DATA_INSUFFICIENT")
                    continue
                # ── Trade Permission Engine ───────────────────────────────
                # Single authoritative decision check: emits DECISION TRACE
                # and returns EXECUTE or BLOCKED before the expensive
                # apex.analyze_market() call.
                _force_tpe_bypass = (
                    _env_truthy("FORCE_TRADE")
                    or _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
                    or _env_truthy("NIJA_FORCE_ACTIVATION")
                )
                logger.info(
                    "🔑 [TPE_GATE] symbol=%s side=%s score=%.1f balance=$%.2f "
                    "force_bypass=%s tpe_available=%s",
                    sig.symbol, sig.side, sig.composite_score,
                    snapshot.balance, _force_tpe_bypass, _TPE_AVAILABLE,
                )
                if _TPE_AVAILABLE and _get_tpe is not None:
                    try:
                        _perm = _get_tpe().evaluate(
                            symbol=sig.symbol,
                            side=sig.side,
                            ai_score=sig.composite_score,
                            ai_threshold=sig.threshold_used,
                            balance=snapshot.balance,
                            regime=snapshot.current_regime,
                            zero_signal_streak=zero_signal_streak,
                            df=df,
                            entry_type=getattr(sig, "entry_type", "swing"),
                            broker=(
                                self.apex._get_broker_name()
                                if hasattr(self.apex, "_get_broker_name")
                                else "coinbase"
                            ),
                            force_next_cycle=_force_this_cycle,
                            dead_zone=_dead_zone,
                            hard_bypass=(
                                zero_signal_streak >= _effective_bypass_threshold
                            ),
                            volume_fallback=bool(
                                sig.metadata.get("volume_fallback")
                            ),
                            metadata=sig.metadata,
                        )
                        logger.info(
                            "🔑 [TPE_RESULT] symbol=%s decision=%s reason=%s",
                            sig.symbol,
                            getattr(_perm, "final_decision", "UNKNOWN"),
                            getattr(_perm, "block_reason", "") or "none",
                        )
                        if _perm.final_decision != "EXECUTE":
                            blocked += 1
                            # ── Entry-to-Order Trace: per-signal veto (TPE) ──
                            _tpe_reason = (
                                getattr(_perm, "block_reason", None)
                                or getattr(_perm, "reason", None)
                                or "trade_permission_engine"
                            )
                            _funnel["ai_gate"] = ("FAIL", _tpe_reason)
                            emit_cycle_trace(
                                CycleOutcome.ENTRY_VETOED,
                                reason=f"trade_permission_engine({sig.symbol}:{_tpe_reason})",
                            )
                            # ── FORCE_TRADE fallback: if TPE still blocks despite
                            # the bypass flags in the engine itself, override here
                            # so the operator's explicit intent is honoured.
                            if _force_tpe_bypass:
                                logger.warning(
                                    "⚡ [TPE_FORCE_OVERRIDE] FORCE_TRADE active — "
                                    "overriding TPE BLOCKED decision for %s %s "
                                    "(reason was: %s). Proceeding to execute_action.",
                                    sig.symbol, sig.side, _tpe_reason,
                                )
                                _funnel["ai_gate"] = ("PASS", "force_trade_override")
                                # Fall through to execute_action below.
                            else:
                                blocked += 1
                                # ── Entry-to-Order Trace: per-signal veto (TPE) ──
                                _funnel["ai_gate"] = ("FAIL", _tpe_reason)
                                emit_cycle_trace(
                                    CycleOutcome.ENTRY_VETOED,
                                    reason=f"trade_permission_engine({sig.symbol}:{_tpe_reason})",
                                )
                                self._n_vetoed += 1
                                self._record_reject(_tpe_reason)
                                # Classify TPE rejection into the appropriate gate counter
                                _tpe_reason_lower = str(_tpe_reason).lower()
                                if "notional" in _tpe_reason_lower or "min_notional" in _tpe_reason_lower:
                                    _gate_rejections["notional_gate_rejected"] += 1
                                elif "capital" in _tpe_reason_lower or "balance" in _tpe_reason_lower:
                                    _gate_rejections["capital_gate_rejected"] += 1
                                elif "risk" in _tpe_reason_lower or "drawdown" in _tpe_reason_lower:
                                    _gate_rejections["risk_gate_rejected"] += 1
                                else:
                                    _gate_rejections["ai_gate_rejected"] += 1
                                continue
                        else:
                            _funnel["ai_gate"] = ("PASS", "")
                    except Exception as _tpe_err:
                        logger.warning(
                            "TradePermissionEngine error for %s (non-fatal): %s",
                            sig.symbol, _tpe_err,
                        )

                # Re-run full apex.analyze_market (handles SL/TP/sizing etc.)
                # Wrapped in a daemon thread with a timeout so a slow/hung
                # indicator calculation cannot stall the entire trading loop.
                try:
                    _analysis_timeout = max(
                        0.1,
                        float(os.getenv("NIJA_ANALYZE_MARKET_TIMEOUT", "15") or "15"),
                    )
                except (ValueError, TypeError):
                    _analysis_timeout = 15.0
                _am_result_q: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

                def _run_analyze_market(
                    _apex: Any = self.apex,
                    _df: Any = df,
                    _sym: str = sig.symbol,
                    _bal: float = snapshot.balance,
                ) -> None:
                    try:
                        _am_result_q.put(("result", _apex.analyze_market(_df, _sym, _bal)))
                    except Exception as _exc:  # noqa: BLE001
                        _am_result_q.put(("error", _exc))

                _am_worker = threading.Thread(
                    target=_run_analyze_market,
                    name="nija-analyze-market",
                    daemon=True,
                )
                _am_worker.start()
                try:
                    _am_kind, _am_payload = _am_result_q.get(timeout=_analysis_timeout)
                except queue.Empty:
                    logger.warning(
                        "⏱️ [Phase3] analyze_market timed out after %.1fs for %s — "
                        "treating as hold (NIJA_ANALYZE_MARKET_TIMEOUT=%.0f)",
                        _analysis_timeout, sig.symbol, _analysis_timeout,
                    )
                    _am_payload = {"action": "hold", "reason": "analyze_market_timeout"}
                    _am_kind = "result"
                if _am_kind == "error":
                    logger.warning(
                        "⚠️ [Phase3] analyze_market raised for %s: %s — treating as hold",
                        sig.symbol, _am_payload,
                    )
                    analysis = {"action": "hold", "reason": f"analyze_market_error:{_am_payload}"}
                else:
                    analysis = _am_payload
                action = analysis.get("action", "hold")

                # When fallback is active, force the action to enter if the
                # signal side is known — the streak means we need a trade.
                if fallback_active and action not in ("enter_long", "enter_short"):
                    if sig.side in ("long", "buy", "enter_long"):
                        action = "enter_long"
                    elif sig.side in ("short", "sell", "enter_short"):
                        action = "enter_short"
                    else:
                        # Unknown side — log and skip rather than guess direction
                        logger.warning(
                            "⚡ Fallback entry: unknown side '%s' for %s — skipping",
                            sig.side, sig.symbol,
                        )
                        blocked += 1
                        continue
                    analysis["action"] = action
                    analysis["reason"] = analysis.get("reason", "") + " [fallback_entry]"

                if fallback_active and action in ("enter_long", "enter_short"):
                    missing = {"position_size", "entry_price", "stop_loss", "take_profit"} - set(analysis.keys())
                    if missing:
                        logger.info(
                            "⚡ [CoreLoop] Building fallback entry payload for %s "
                            "(missing fields: %s, force_trade=%s)",
                            sig.symbol,
                            missing,
                            _force_trade_bypass,
                        )
                        try:
                            fallback_payload = self._build_forced_fallback_entry_analysis(
                                df=df,
                                sig=sig,
                                snapshot=snapshot,
                                action=action,
                                existing_reason=analysis.get("reason", ""),
                            )
                            analysis.update(fallback_payload)
                            # The fallback payload is already sized conservatively;
                            # avoid multiplying it below broker minimum notional.
                            sig.position_multiplier = 1.0
                        except Exception as _fallback_err:
                            # _build_forced_fallback_entry_analysis raised (e.g.
                            # competitive_profitability_policy liquidity block or
                            # missing close price).  When FORCE_TRADE is active,
                            # build a minimal hardcoded payload directly so that
                            # execute_action() is still called rather than silently
                            # skipping this signal.
                            #
                            # SAFETY: Never bypass a live-capital illiquid policy
                            # block via the emergency payload path.  If the error
                            # message indicates an illiquid policy rejection, treat
                            # it as a hard block regardless of FORCE_TRADE mode.
                            _fallback_err_msg = str(_fallback_err).lower()
                            _is_illiquid_block = (
                                "illiquid" in _fallback_err_msg
                                or "competitive profitability policy" in _fallback_err_msg
                                or "liquidity" in _fallback_err_msg
                                or "fallback_illiquid_policy_blocked" in _fallback_err_msg
                            )
                            if _is_illiquid_block:
                                logger.warning(
                                    "🚫 [CoreLoop] Illiquid policy hard block for %s (%s) — "
                                    "emergency payload bypass suppressed (live-capital safety).",
                                    sig.symbol,
                                    _fallback_err,
                                )
                                blocked += 1
                                _funnel["profitability"] = (
                                    "FAIL",
                                    f"ILLIQUID_POLICY_HARD_BLOCK:{_fallback_err}",
                                )
                                continue
                            if _force_trade_bypass:
                                logger.warning(
                                    "⚡ [FORCE_TRADE] _build_forced_fallback_entry_analysis "
                                    "raised for %s (%s) — constructing minimal emergency "
                                    "payload to ensure execute_action() is called.",
                                    sig.symbol,
                                    _fallback_err,
                                )
                                try:
                                    _price = float(df["close"].iloc[-1])
                                    _bal = max(float(snapshot.balance or 0.0), 0.0)
                                    _size = max(min(_bal * 0.05, _bal), 3.50)
                                    if action == "enter_short":
                                        _sl = _price * 1.012
                                        _tp = [_price * 0.990, _price * 0.985, _price * 0.980]
                                    else:
                                        _sl = _price * 0.988
                                        _tp = [_price * 1.010, _price * 1.015, _price * 1.020]
                                    analysis.update({
                                        "action": action,
                                        "entry_price": _price,
                                        "position_size": _size,
                                        "stop_loss": _sl,
                                        "take_profit": _tp,
                                        "trailing_stop_pct": 0.75,
                                        "reason": (
                                            analysis.get("reason", "") +
                                            " [emergency_fallback_payload]"
                                        ),
                                        "fallback_entry": True,
                                        "forced_fallback": True,
                                        "emergency_payload": True,
                                    })
                                    sig.position_multiplier = 1.0
                                    logger.warning(
                                        "⚡ [FORCE_TRADE] Emergency payload built for %s: "
                                        "price=%.6f size=$%.2f sl=%.6f",
                                        sig.symbol, _price, _size, _sl,
                                    )
                                except Exception as _emergency_err:
                                    logger.error(
                                        "❌ [FORCE_TRADE] Emergency payload construction "
                                        "also failed for %s: %s — signal will be blocked.",
                                        sig.symbol,
                                        _emergency_err,
                                    )
                                    blocked += 1
                                    _funnel["profitability"] = (
                                        "FAIL",
                                        f"EMERGENCY_PAYLOAD_FAILED:{_emergency_err}",
                                    )
                                    continue
                            else:
                                # Not in FORCE_TRADE mode — re-raise so the outer
                                # except block handles it normally.
                                raise

                if action not in ("enter_long", "enter_short"):
                    blocked += 1
                    _block_raw_reason = analysis.get("reason", "NO_PROFITABLE_ACTION") or "NO_PROFITABLE_ACTION"
                    _funnel["profitability"] = ("FAIL", _block_raw_reason)
                    # Normalize to a clean enum for reject_reason_counts so that
                    # ORDER_ADMISSION_SUMMARY shows the real top_reject instead of "none".
                    _block_reason_lower = _block_raw_reason.lower()
                    if (
                        "terminal_risk_hard_block" in _block_reason_lower
                        or "hard_sector_limit" in _block_reason_lower
                        or "sector_exposure_limit" in _block_reason_lower
                        or "entry_blocked_terminal" in _block_reason_lower
                        or "portfolio exposure limit" in _block_reason_lower
                        or "position blocked by risk engine" in _block_reason_lower
                    ):
                        _reject_key = "ENTRY_BLOCKED_TERMINAL_RISK_HARD_BLOCK"
                        if "sector" in _block_reason_lower:
                            _reject_key = "SECTOR_EXPOSURE_LIMIT_EXCEEDED"
                    elif "volume" in _block_reason_lower and "low" in _block_reason_lower:
                        _reject_key = "VOLUME_TOO_LOW"
                    elif "data" in _block_reason_lower and ("timeout" in _block_reason_lower or "empty" in _block_reason_lower):
                        _reject_key = "DATA_TIMEOUT_OR_EMPTY"
                    else:
                        # Use first 64 chars of raw reason as the key (existing behaviour).
                        _reject_key = _block_raw_reason[:64].strip()
                    self._record_reject(_reject_key)
                    logger.critical(
                        "🚫 [Phase3] SIGNAL BLOCKED before execute_action | symbol=%s "
                        "action=%s reason=%s reject_key=%s fallback_active=%s force_trade=%s — "
                        "signal will NOT reach execute_action this cycle.",
                        sig.symbol,
                        action,
                        _block_raw_reason,
                        _reject_key,
                        fallback_active,
                        _force_trade_bypass,
                    )
                    continue
                _funnel["profitability"] = ("PASS", "")
                logger.critical(
                    "✅ [Phase3] SIGNAL PASSED all gates | symbol=%s action=%s "
                    "fallback_active=%s — calling execute_action() now.",
                    sig.symbol,
                    action,
                    fallback_active,
                )

                # Apply AI engine position multiplier to analysis size hint
                if "position_size" in analysis and sig.position_multiplier != 1.0:
                    original = analysis["position_size"]
                    analysis["position_size"] = original * sig.position_multiplier
                    logger.info(
                        "   🤖 AI multiplier ×%.2f applied to %s size: $%.2f → $%.2f",
                        sig.position_multiplier, sig.symbol,
                        original, analysis["position_size"],
                    )

                # Inject signal-level EV metadata so the expectancy gate in
                # ExecutionEngine receives the real win rate instead of the
                # global 50% default.  composite_score is mapped to a
                # conservative win-rate estimate: score ≥ 75 → 0.65,
                # score ≥ 60 → 0.58, score ≥ 50 → 0.54, below 50 → 0.50.
                if "composite_score" not in analysis:
                    analysis.setdefault("composite_score", float(sig.composite_score))
                if "expected_win_rate" not in analysis:
                    _score_for_wr = float(sig.composite_score or 0.0)
                    if _score_for_wr >= 75.0:
                        analysis["expected_win_rate"] = 0.65
                    elif _score_for_wr >= 60.0:
                        analysis["expected_win_rate"] = 0.58
                    elif _score_for_wr >= 50.0:
                        analysis["expected_win_rate"] = 0.54
                    else:
                        analysis["expected_win_rate"] = 0.50
                if "regime" not in analysis:
                    _sig_regime = getattr(sig, "regime", None) or getattr(sig, "market_regime", None)
                    if _sig_regime:
                        analysis["regime"] = _sig_regime

                logger.critical(
                    "🚀 [CoreLoop] SUBMITTING ORDER | symbol=%s side=%s action=%s "
                    "position_size=$%.2f entry_price=%.6f score=%.1f mult=×%.2f",
                    sig.symbol,
                    sig.side,
                    action,
                    float(analysis.get("position_size", 0.0) or 0.0),
                    float(analysis.get("entry_price", 0.0) or 0.0),
                    sig.composite_score,
                    sig.position_multiplier,
                )
                logger.critical(
                    "⚡ [CoreLoop] execute_action CALLED | symbol=%s action=%s "
                    "analysis_keys=%s",
                    sig.symbol,
                    action,
                    list(analysis.keys()),
                )
                print(
                    f"[NIJA-PRINT] BEFORE execute_action | "
                    f"symbol={sig.symbol} action={action} "
                    f"size=${float(analysis.get('position_size', 0.0) or 0.0):.2f} "
                    f"price={float(analysis.get('entry_price', 0.0) or 0.0):.6f}",
                    flush=True,
                )
                success = self.apex.execute_action(analysis, sig.symbol)
                print(
                    f"[NIJA-PRINT] AFTER execute_action | "
                    f"symbol={sig.symbol} side={sig.side} success={success}",
                    flush=True,
                )
                logger.critical(
                    "📬 [CoreLoop] ORDER RESULT | symbol=%s side=%s success=%s",
                    sig.symbol,
                    sig.side,
                    success,
                )
                if success:
                    entries += 1
                    logger.info(
                        "   ✅ Core loop entry: %s %s score=%.1f mult=×%.2f%s",
                        sig.symbol, sig.side.upper(),
                        sig.composite_score, sig.position_multiplier,
                        f" [RELAX×{sig.metadata.get('relaxation_step', 0)}]" if fallback_active else "",
                    )
                    # ── Entry-to-Order Trace: ORDER_PLACED ───────────────
                    emit_cycle_trace(
                        CycleOutcome.ORDER_PLACED,
                        symbol=sig.symbol,
                        side=sig.side,
                        score=round(sig.composite_score, 1),
                    )
                    self._n_placed += 1
                else:
                    blocked += 1
                    logger.critical(
                        "❌ [CoreLoop] ORDER REJECTED | symbol=%s side=%s action=%s "
                        "position_size=$%.2f entry_price=%.6f stop_loss=%.6f score=%.1f "
                        "fallback_active=%s — execute_action() returned False. "
                        "See execute_action / ExecutionEngine logs above for the broker "
                        "rejection reason (gate name, error message, or exception).",
                        sig.symbol,
                        sig.side,
                        analysis.get("action", "unknown"),
                        float(analysis.get("position_size", 0.0) or 0.0),
                        float(analysis.get("entry_price", 0.0) or 0.0),
                        float(analysis.get("stop_loss", 0.0) or 0.0),
                        sig.composite_score,
                        fallback_active,
                    )
                    print(
                        f"[NIJA-PRINT] ORDER REJECTED | symbol={sig.symbol} side={sig.side} "
                        f"action={analysis.get('action', 'unknown')} "
                        f"size=${float(analysis.get('position_size', 0.0) or 0.0):.2f} "
                        f"price={float(analysis.get('entry_price', 0.0) or 0.0):.6f} "
                        f"sl={float(analysis.get('stop_loss', 0.0) or 0.0):.6f}",
                        flush=True,
                    )
                    # ── Entry-to-Order Trace: ORDER_REJECTED ─────────────
                    emit_cycle_trace(
                        CycleOutcome.ORDER_REJECTED,
                        symbol=sig.symbol,
                        reason="execute_action_returned_false",
                    )
                    self._n_rejected += 1
                    try:
                        from bot.trading_state_machine import report_execution_anomaly
                        report_execution_anomaly("rejected_orders", "execute_action_returned_false")
                    except Exception:
                        pass

            except Exception as exec_err:
                print(
                    f"[NIJA-PRINT] EXCEPTION in execute_action | "
                    f"symbol={sig.symbol} error={exec_err!r}",
                    flush=True,
                )
                logger.warning("Phase3 execute error for %s: %s", sig.symbol, exec_err)
                blocked += 1
                _funnel = funnel_traces.setdefault(sig.symbol, {})
                _funnel["profitability"] = ("FAIL", f"EXECUTION_EXCEPTION:{exec_err}")
                # Authority-gate denials (ExecutionBlocked) must NOT be recorded
                # as rejected_orders: they create a feedback loop where denials →
                # high rejection rate → circuit breaker tripped → EMERGENCY_STOP
                # → more authority denials.  Only real exchange rejections count.
                _is_authority_denial = (
                    "execution authority violation" in str(exec_err).lower()
                    or "executionblocked" in type(exec_err).__name__.lower()
                    or "fatal: execution authority" in str(exec_err).lower()
                )
                if not _is_authority_denial:
                    try:
                        from bot.trading_state_machine import report_execution_anomaly
                        report_execution_anomaly("rejected_orders", f"execute_exception:{exec_err}")
                    except Exception:
                        pass

        for symbol in symbols:
            stages = funnel_traces.get(symbol)
            if stages:
                self._emit_trade_funnel_trace(symbol, stages)

        # ── Emit score histogram for this cycle ──────────────────────────
        if _sdd is not None:
            rank_threshold = selected[0].threshold_used if selected else None
            _sdd.emit_histogram(
                entries_taken=entries,
                candidates_found=len(candidates),
                rank_threshold=rank_threshold,
            )

        # ── VERBOSE EXIT LOG: confirm execution loop outcome ──────────────
        _force_direct_would_trigger = entries == 0 and _env_truthy("FORCE_TRADE")
        logger.critical(
            "🏁 [Phase3] END _phase3_scan_and_enter | entries=%d blocked=%d "
            "scored=%d candidates=%d selected=%d force_trade=%s "
            "FORCE_TRADE_DIRECT_fallback_would_trigger=%s",
            entries,
            blocked,
            scored,
            len(candidates),
            len(selected),
            _env_truthy("FORCE_TRADE"),
            _force_direct_would_trigger,
        )
        if _force_direct_would_trigger:
            logger.critical(
                "⚡ [Phase3] FORCE_TRADE active but entries=0 — "
                "FORCE_TRADE_DIRECT fallback condition MET. "
                "Check execute_action() logs above for why orders were not placed "
                "(broker gate, capital gate, or execution engine rejection).",
            )

        # ── FORCE_TRADE direct execute_action() fallback ─────────────────
        # When FORCE_TRADE=true and the entire selection/execution pipeline
        # produced zero entries (entries == 0), bypass ALL selection logic
        # and call execute_action() directly with a minimal payload built
        # from the best-volume symbol tracked during the scoring phase.
        #
        # This is the FINAL fallback — it fires on EVERY cycle when
        # FORCE_TRADE=true and no order was submitted, regardless of what
        # happened in the signal selection code above (silent drops, gate
        # rejections, analyze_market returning 'hold', TPE blocks, etc.).
        #
        # Root cause addressed: after 2+ trading cycles with FORCE_TRADE=true,
        # signals are generated and market conditions evaluated ("Trade allowed:
        # True") but execute_action() is never called because the selection
        # pipeline silently drops all signals before reaching the execution
        # block.  The CRITICAL-level logs (CANDIDATES FOUND, SIGNALS SCORED,
        # SIGNALS SELECTED, EXECUTING SIGNAL, ORDER RESULT) are absent,
        # confirming the execution block is never reached.
        _force_direct_bypass = (
            _env_truthy("FORCE_TRADE")
            or _env_truthy("FORCE_TRADE_MODE")
            or _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
        )
        if _force_direct_bypass and entries == 0 and _best_volume_symbol:
            logger.critical(
                "⚡ [FORCE_TRADE_DIRECT] FINAL FALLBACK TRIGGERED — "
                "entries=0 after full selection pipeline. "
                "Calling execute_action() DIRECTLY for best-volume symbol=%s "
                "(avg_vol=%.0f). Bypassing ALL selection logic. cycle_id=%s",
                _best_volume_symbol,
                _best_volume,
                snapshot.cycle_id or "n/a",
            )
            try:
                _ft_df = self._fetch_df(broker, _best_volume_symbol)
                if _ft_df is not None and len(_ft_df) >= 10:
                    _ft_price = float(_ft_df["close"].iloc[-1])
                    _ft_bal = max(float(snapshot.balance or 0.0), 0.0)
                    # Conservative micro-trade: 5% of balance, minimum $3.50
                    _ft_size = max(min(_ft_bal * 0.05, _ft_bal), 3.50)
                    # Determine action: default to long on spot-only brokers (e.g. Coinbase)
                    # that do not support shorting, otherwise follow the best-volume side.
                    _ft_broker_name = (
                        self.apex._get_broker_name()
                        if hasattr(self, "apex") and hasattr(self.apex, "_get_broker_name")
                        else "coinbase"
                    )
                    _ft_broker_can_short = False
                    try:
                        from bot.exchange_capabilities import can_short as _can_short_ft
                        _ft_broker_can_short = _can_short_ft(_ft_broker_name, _best_volume_symbol)
                    except Exception:
                        try:
                            from exchange_capabilities import can_short as _can_short_ft  # type: ignore[import]
                            _ft_broker_can_short = _can_short_ft(_ft_broker_name, _best_volume_symbol)
                        except Exception:
                            pass  # conservative: assume short is NOT supported

                    _ft_wants_short = _best_volume_side not in ("long", "buy", "enter_long")
                    if _ft_wants_short and not _ft_broker_can_short:
                        logger.warning(
                            "⚡ [FORCE_TRADE_DIRECT] Broker %s does not support shorting for %s — "
                            "overriding action from enter_short to enter_long.",
                            _ft_broker_name,
                            _best_volume_symbol,
                        )
                        print(
                            f"[NIJA-PRINT] FORCE_TRADE_DIRECT SHORT→LONG OVERRIDE | "
                            f"symbol={_best_volume_symbol} broker={_ft_broker_name} "
                            f"reason=broker_does_not_support_shorting",
                            flush=True,
                        )
                    _ft_action = (
                        "enter_long"
                        if (_best_volume_side in ("long", "buy", "enter_long") or not _ft_broker_can_short)
                        else "enter_short"
                    )
                    if _ft_action == "enter_short":
                        _ft_sl = _ft_price * 1.012
                        _ft_tp = [_ft_price * 0.990, _ft_price * 0.985, _ft_price * 0.980]
                    else:
                        _ft_sl = _ft_price * 0.988
                        _ft_tp = [_ft_price * 1.010, _ft_price * 1.015, _ft_price * 1.020]
                    _ft_analysis = {
                        "action": _ft_action,
                        "entry_price": _ft_price,
                        "position_size": _ft_size,
                        "stop_loss": _ft_sl,
                        "take_profit": _ft_tp,
                        "trailing_stop_pct": 0.75,
                        "reason": "FORCE_TRADE_direct_execute_fallback",
                        "fallback_entry": True,
                        "forced_fallback": True,
                        "force_trade_direct": True,
                    }
                    logger.critical(
                        "⚡ [FORCE_TRADE_DIRECT] Calling execute_action() | "
                        "symbol=%s action=%s price=%.6f size=$%.2f sl=%.6f",
                        _best_volume_symbol,
                        _ft_action,
                        _ft_price,
                        _ft_size,
                        _ft_sl,
                    )
                    print(
                        f"[NIJA-PRINT] FORCE_TRADE_DIRECT BEFORE execute_action | "
                        f"symbol={_best_volume_symbol} action={_ft_action} "
                        f"price={_ft_price:.6f} size=${_ft_size:.2f} sl={_ft_sl:.6f}",
                        flush=True,
                    )
                    _ft_success = self.apex.execute_action(_ft_analysis, _best_volume_symbol)
                    print(
                        f"[NIJA-PRINT] FORCE_TRADE_DIRECT AFTER execute_action | "
                        f"symbol={_best_volume_symbol} side={_best_volume_side} "
                        f"success={_ft_success}",
                        flush=True,
                    )
                    logger.critical(
                        "⚡ [FORCE_TRADE_DIRECT] ORDER RESULT | "
                        "symbol=%s side=%s success=%s",
                        _best_volume_symbol,
                        _best_volume_side,
                        _ft_success,
                    )
                    if _ft_success:
                        entries += 1
                        logger.critical(
                            "✅ [FORCE_TRADE_DIRECT] Order submitted successfully — "
                            "symbol=%s side=%s price=%.6f size=$%.2f",
                            _best_volume_symbol,
                            _best_volume_side,
                            _ft_price,
                            _ft_size,
                        )
                    else:
                        logger.critical(
                            "❌ [FORCE_TRADE_DIRECT] execute_action() returned False | "
                            "symbol=%s side=%s action=%s price=%.6f size=$%.2f sl=%.6f — "
                            "See execute_action / ExecutionEngine logs above for the broker "
                            "rejection reason (gate name, error message, or exception).",
                            _best_volume_symbol,
                            _best_volume_side,
                            _ft_action,
                            _ft_price,
                            _ft_size,
                            _ft_sl,
                        )
                        print(
                            f"[NIJA-PRINT] FORCE_TRADE_DIRECT ORDER REJECTED | "
                            f"symbol={_best_volume_symbol} side={_best_volume_side} "
                            f"action={_ft_action} price={_ft_price:.6f} "
                            f"size=${_ft_size:.2f} sl={_ft_sl:.6f}",
                            flush=True,
                        )
                else:
                    logger.critical(
                        "❌ [FORCE_TRADE_DIRECT] Could not fetch DataFrame for %s "
                        "(df=%s len=%d) — direct fallback skipped.",
                        _best_volume_symbol,
                        "None" if _ft_df is None else "ok",
                        0 if _ft_df is None else len(_ft_df),
                    )
            except Exception as _ft_err:
                print(
                    f"[NIJA-PRINT] FORCE_TRADE_DIRECT EXCEPTION | "
                    f"symbol={_best_volume_symbol} error={_ft_err!r}",
                    flush=True,
                )
                logger.critical(
                    "❌ [FORCE_TRADE_DIRECT] execute_action() raised exception for %s: %s — "
                    "direct fallback failed.",
                    _best_volume_symbol,
                    _ft_err,
                )
        elif _force_direct_bypass and entries == 0 and not _best_volume_symbol:
            logger.critical(
                "❌ [FORCE_TRADE_DIRECT] FORCE_TRADE active but no best-volume symbol "
                "available (scored=%d) — direct fallback cannot run. "
                "Check that symbols list is non-empty and broker data is flowing.",
                scored,
            )

        return entries, blocked, scored, _gate_rejections

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_forced_fallback_entry_analysis(
        self,
        *,
        df: pd.DataFrame,
        sig: Any,
        snapshot: CycleSnapshot,
        action: str,
        existing_reason: str = "",
    ) -> Dict[str, Any]:
        """Build a complete minimal entry payload for forced fallback orders.

        ``apex.analyze_market`` can return ``hold`` before sizing when strict
        pre-entry market-condition filters reject ADX/volume/price-action.  The
        core loop may still intentionally force a small Always-Trade/volume
        fallback entry.  In that path we must provide the fields required by
        ``execute_action`` instead of only flipping ``action`` from hold to enter.
        """
        price = 0.0
        try:
            price = float(df["close"].iloc[-1])
        except Exception:
            price = 0.0
        if price <= 0:
            raise ValueError("cannot build fallback entry without positive close price")

        broker_name = "coinbase"
        try:
            if hasattr(self.apex, "_get_broker_name"):
                broker_name = str(self.apex._get_broker_name() or broker_name).lower()
        except Exception:
            pass

        min_notional = 3.50
        try:
            from bot.minimum_notional_gate import get_minimum_notional_gate
            min_notional = float(
                get_minimum_notional_gate().config.get_min_notional_for_broker(
                    broker_name, balance=float(snapshot.balance or 0.0)
                )
            )
        except Exception:
            min_notional = 10.50 if "kraken" in broker_name else 3.50

        balance = max(float(snapshot.balance or 0.0), 0.0)
        if balance <= 0:
            raise ValueError("cannot build fallback entry without positive balance")
        risk_fraction = 0.05
        stop_loss_pct = 1.20
        # Keep fallback geometry compatible with ExecutionEngine's hard target
        # geometry gate (MIN_TP_PCT defaults to 0.8%, MAX_SL_PCT to 3.0%).
        # The previous 0.60% TP1 generated a complete-looking payload that was
        # still rejected before order submission.
        take_profit_pct = (0.85, 1.20, 1.80)
        trailing_stop_pct = 0.75
        take_profit_pct = (1.00, 1.50, 2.00)
        trailing_stop_pct = 0.75
        # Check whether any FORCE_TRADE flag is active — when set, the
        # liquidity gate in competitive_profitability_policy must NOT raise
        # ValueError because that exception propagates to the outer execution
        # loop's except-block, increments `blocked`, and causes execute_action()
        # to be silently skipped.  This was the root cause of the
        # "6000+ cycles, zero trades" condition.
        _force_trade_active = (
            _env_truthy("FORCE_TRADE")
            or _env_truthy("FORCE_TRADE_MODE")
            or _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
            or _env_truthy("NIJA_FORCE_ACTIVATION")
        )
        try:
            from bot.competitive_profitability_policy import get_competitive_profitability_policy
            competitive_profile = get_competitive_profitability_policy().profile_entry(
                df=df,
                side="short" if action == "enter_short" else "long",
            )
            if not competitive_profile.liquidity_ok:
                if _force_trade_active:
                    logger.warning(
                        "⚡ [FORCE_TRADE] competitive_profitability_policy liquidity check "
                        "FAILED for %s (%s) — using default fallback geometry.",
                        getattr(sig, "symbol", "UNKNOWN"),
                        competitive_profile.liquidity_reason,
                    )
                else:
                    raise ValueError(
                        "competitive profitability policy blocked illiquid fallback entry: "
                        f"{competitive_profile.liquidity_reason}"
                    )
            else:
                risk_fraction = competitive_profile.risk_fraction
                stop_loss_pct = min(float(competitive_profile.stop_loss_pct), 3.0)
                raw_tp = tuple(float(pct) for pct in competitive_profile.take_profit_pct)
                tp1 = max(raw_tp[0] if len(raw_tp) > 0 else 0.0, 0.85)
                tp2 = max(raw_tp[1] if len(raw_tp) > 1 else tp1, tp1 + 0.20)
                tp3 = max(raw_tp[2] if len(raw_tp) > 2 else tp2, tp2 + 0.25)
                take_profit_pct = (tp1, tp2, tp3)
                trailing_stop_pct = competitive_profile.trailing_stop_pct
        except ValueError:
            raise
        except Exception:
            pass
        size_cap = max(min(balance * risk_fraction, balance), 0.0)
        position_size = min(max(min_notional, size_cap), balance)

        if action == "enter_short":
            stop_loss = price * (1.0 + stop_loss_pct / 100.0)
            take_profit = [price * (1.0 - pct / 100.0) for pct in take_profit_pct]
        else:
            stop_loss = price * (1.0 - stop_loss_pct / 100.0)
            take_profit = [price * (1.0 + pct / 100.0) for pct in take_profit_pct]

        reason = existing_reason or getattr(sig, "reason", "forced_fallback_entry")
        if "fallback_entry" not in reason:
            reason = f"{reason} [fallback_entry]"

        return {
            "action": action,
            "entry_price": price,
            "position_size": position_size,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trailing_stop_pct": trailing_stop_pct,
            "reason": reason,
            "fallback_entry": True,
            "forced_fallback": True,
            "competitive_profitability_policy": True,
        }

    def _fetch_df(self, broker: Any, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV DataFrame from the broker.

        When ``broker`` is None the method falls back to ``apex.broker_client``
        so per-symbol fetches never silently return None when the caller omits
        the broker argument.

        Retry logic
        -----------
        On the first attempt the method tries every known candle-fetch method
        on the broker object.  If all methods return insufficient data (< 10
        rows) or raise exceptions, the method retries up to
        ``NIJA_FETCH_DF_MAX_RETRIES`` times (default 2) with a short sleep
        between attempts.  This handles transient rate-limit blips and
        momentary API unavailability without blocking the entire trading loop.

        Returns ``None`` when all retries are exhausted.
        """
        try:
            _max_retries = max(1, int(os.getenv("NIJA_FETCH_DF_MAX_RETRIES", "2") or "2"))
            _retry_delay_s = max(0.1, float(os.getenv("NIJA_FETCH_DF_RETRY_DELAY_S", "1.0") or "1.0"))
        except (TypeError, ValueError):
            _max_retries = 2
            _retry_delay_s = 1.0

        for _attempt in range(1, _max_retries + 1):
            try:
                _broker = broker
                if _broker is None:
                    _broker = getattr(self.apex, "broker_client", None)
                if _broker is None:
                    logger.warning(
                        "⚠️ [_fetch_df] broker=None for symbol=%s — no broker_client on apex either. "
                        "Cannot fetch candle data.",
                        symbol,
                    )
                    return None
                call_plan = (
                    ("get_candles", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
                    ("fetch_ohlcv", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
                    ("get_ohlcv", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
                    ("get_historical_data", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
                    ("get_market_data", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
                )
                _tried_methods = []
                for method_name, primary_call, fallback_call in call_plan:
                    method = getattr(_broker, method_name, None)
                    if not callable(method):
                        continue
                    _tried_methods.append(method_name)
                    try:
                        result = self._call_market_data_method(method, primary_call, fallback_call)
                        df = self._coerce_market_data_frame(result)
                        if df is not None and len(df) >= 10:
                            if _attempt > 1:
                                logger.info(
                                    "✅ [_fetch_df] symbol=%s recovered on attempt %d/%d "
                                    "via %s (df_len=%d)",
                                    symbol, _attempt, _max_retries, method_name, len(df),
                                )
                            return df
                        # Log when a method exists but returns bad data
                        logger.debug(
                            "_fetch_df: %s.%s returned df_len=%d for %s (attempt %d/%d)",
                            type(_broker).__name__, method_name,
                            len(df) if df is not None else -1, symbol,
                            _attempt, _max_retries,
                        )
                    except Exception as _method_exc:
                        logger.debug(
                            "_fetch_df: %s.%s raised %s for %s (attempt %d/%d)",
                            type(_broker).__name__, method_name, _method_exc, symbol,
                            _attempt, _max_retries,
                        )
                if not _tried_methods:
                    # No matching method found on broker — log once at warning level
                    _broker_methods = [m for m in dir(_broker) if not m.startswith("_")]
                    logger.warning(
                        "⚠️ [_fetch_df] broker=%s has none of the expected candle methods "
                        "(get_candles/fetch_ohlcv/get_ohlcv/get_historical_data/get_market_data). "
                        "Available methods: %s",
                        type(_broker).__name__,
                        _broker_methods[:20],
                    )
                    return None  # No point retrying if no methods exist

                # All methods returned insufficient data on this attempt.
                if _attempt < _max_retries:
                    logger.warning(
                        "⚠️ [_fetch_df] symbol=%s — all candle methods returned insufficient "
                        "data on attempt %d/%d; retrying in %.1fs",
                        symbol, _attempt, _max_retries, _retry_delay_s,
                    )
                    time.sleep(_retry_delay_s)
                else:
                    logger.warning(
                        "⚠️ [_fetch_df] symbol=%s — all %d fetch attempts exhausted; "
                        "returning None (data_insufficient). "
                        "Check broker connectivity and symbol format.",
                        symbol, _max_retries,
                    )
            except Exception as exc:
                logger.warning(
                    "⚠️ [_fetch_df] unexpected error for %s (attempt %d/%d): %s",
                    symbol, _attempt, _max_retries, exc,
                )
                if _attempt < _max_retries:
                    time.sleep(_retry_delay_s)
        return None

    @staticmethod
    def _call_market_data_method(
        method: Any,
        primary_call: Tuple[Tuple[Any, ...], Dict[str, Any]],
        fallback_call: Tuple[Tuple[Any, ...], Dict[str, Any]],
    ) -> Any:
        """Call a broker market-data method while tolerating signature drift.

        Wraps each attempt in a daemon thread with a configurable timeout so
        that a hanging broker API call (e.g. Coinbase/Kraken rate-limit stall)
        cannot block the entire trading loop indefinitely.  The timeout is
        controlled by the ``NIJA_CANDLE_FETCH_TIMEOUT`` environment variable
        (default 10 s).  On timeout the method returns ``None`` so
        ``_fetch_df`` falls through to the next call variant or skips the
        symbol gracefully.
        """
        try:
            _timeout = max(0.1, float(os.getenv("NIJA_CANDLE_FETCH_TIMEOUT", "10") or "10"))
        except (ValueError, TypeError):
            _timeout = 10.0

        def _run_with_timeout(fn: Any, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Any:
            result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

            def _runner() -> None:
                try:
                    result_queue.put(("result", fn(*args, **kwargs)))
                except Exception as exc:  # noqa: BLE001
                    result_queue.put(("error", exc))

            worker = threading.Thread(target=_runner, name="nija-candle-fetch", daemon=True)
            worker.start()
            try:
                kind, payload = result_queue.get(timeout=_timeout)
            except queue.Empty:
                _sym = args[0] if args else "?"
                logger.warning(
                    "⏱️ [_call_market_data_method] candle fetch timed out after %.1fs — "
                    "skipping symbol %s (fn=%s, NIJA_CANDLE_FETCH_TIMEOUT=%.0f)",
                    _timeout, _sym, getattr(fn, "__name__", str(fn)), _timeout,
                )
                return None
            if kind == "error":
                raise payload  # type: ignore[misc]
            return payload

        try:
            args, kwargs = primary_call
            return _run_with_timeout(method, args, kwargs)
        except TypeError:
            args, kwargs = fallback_call
            return _run_with_timeout(method, args, kwargs)

    @classmethod
    def _coerce_market_data_frame(cls, result: Any) -> Optional[pd.DataFrame]:
        """Normalize broker candle payload variants into an OHLCV DataFrame."""
        if result is None:
            return None
        if isinstance(result, tuple):
            if len(result) >= 2 and result[1]:
                return None
            result = result[0] if result else None
        if isinstance(result, pd.DataFrame):
            return cls._normalize_ohlcv_columns(result.copy())
        if isinstance(result, Mapping):
            for key in ("candles", "data", "ohlcv", "result", "rows"):
                if key in result:
                    return cls._coerce_market_data_frame(result.get(key))
            return cls._normalize_ohlcv_columns(pd.DataFrame([result]))
        if isinstance(result, (list, tuple)):
            if not result:
                return None
            call_plan = (
                ("get_candles", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
                ("fetch_ohlcv", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
                ("get_ohlcv", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
                ("get_historical_data", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
                ("get_market_data", ((symbol,), {"limit": 200}), ((symbol, "1m", 200), {})),
            )
            for method_name, primary_call, fallback_call in call_plan:
                method = getattr(broker, method_name, None)
                if not callable(method):
                    continue
                result = self._call_market_data_method(method, primary_call, fallback_call)
                df = self._coerce_market_data_frame(result)
                if df is not None and len(df) >= 10:
                    return df
            frame = pd.DataFrame(result)
            if not frame.empty and all(isinstance(col, int) for col in frame.columns):
                # CCXT-style rows: [timestamp, open, high, low, close, volume, ...]
                if len(frame.columns) >= 6:
                    frame = frame.iloc[:, :6]
                    frame.columns = ["timestamp", "open", "high", "low", "close", "volume"]
                # Compact rows occasionally omit timestamp: [open, high, low, close, volume]
                elif len(frame.columns) == 5:
                    frame.columns = ["open", "high", "low", "close", "volume"]
            return cls._normalize_ohlcv_columns(frame)
        return None

    @staticmethod
    def _normalize_ohlcv_columns(frame: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Return a numeric OHLCV frame when the payload has usable candles."""
        if frame is None or frame.empty:
            return None
        rename_map = {
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "price": "close",
            "last": "close",
        }
        normalized = frame.rename(
            columns={col: rename_map.get(str(col).lower(), col) for col in frame.columns}
        )
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(set(normalized.columns)):
            return None
        for col in required:
            normalized[col] = pd.to_numeric(normalized[col], errors="coerce")
        normalized = normalized.dropna(subset=list(required))
        if normalized.empty:
            return None
        return normalized

    @staticmethod
    def _call_market_data_method(
        method: Any,
        primary_call: Tuple[Tuple[Any, ...], Dict[str, Any]],
        fallback_call: Tuple[Tuple[Any, ...], Dict[str, Any]],
    ) -> Any:
        """Call a broker market-data method while tolerating signature drift."""
        try:
            args, kwargs = primary_call
            return method(*args, **kwargs)
        except TypeError:
            args, kwargs = fallback_call
            return method(*args, **kwargs)

    @classmethod
    def _coerce_market_data_frame(cls, result: Any) -> Optional[pd.DataFrame]:
        """Normalize broker candle payload variants into an OHLCV DataFrame."""
        if result is None:
            return None
        if isinstance(result, tuple):
            if len(result) >= 2 and result[1]:
                return None
            result = result[0] if result else None
        if isinstance(result, pd.DataFrame):
            return cls._normalize_ohlcv_columns(result.copy())
        if isinstance(result, Mapping):
            for key in ("candles", "data", "ohlcv", "result", "rows"):
                if key in result:
                    return cls._coerce_market_data_frame(result.get(key))
            return cls._normalize_ohlcv_columns(pd.DataFrame([result]))
        if isinstance(result, (list, tuple)):
            if not result:
                return None
            frame = pd.DataFrame(result)
            if not frame.empty and all(isinstance(col, int) for col in frame.columns):
                # CCXT-style rows: [timestamp, open, high, low, close, volume, ...]
                if len(frame.columns) >= 6:
                    frame = frame.iloc[:, :6]
                    frame.columns = ["timestamp", "open", "high", "low", "close", "volume"]
                # Compact rows occasionally omit timestamp: [open, high, low, close, volume]
                elif len(frame.columns) == 5:
                    frame.columns = ["open", "high", "low", "close", "volume"]
            return cls._normalize_ohlcv_columns(frame)
        return None

    @staticmethod
    def _normalize_ohlcv_columns(frame: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Return a numeric OHLCV frame when the payload has usable candles."""
        if frame is None or frame.empty:
            return None
        rename_map = {
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "price": "close",
            "last": "close",
        }
        normalized = frame.rename(
            columns={col: rename_map.get(str(col).lower(), col) for col in frame.columns}
        )
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(set(normalized.columns)):
            return None
        for col in required:
            normalized[col] = pd.to_numeric(normalized[col], errors="coerce")
        normalized = normalized.dropna(subset=list(required))
        if normalized.empty:
            return None
        return normalized

    @staticmethod
    def _call_market_data_method(
        method: Any,
        primary_call: Tuple[Tuple[Any, ...], Dict[str, Any]],
        fallback_call: Tuple[Tuple[Any, ...], Dict[str, Any]],
    ) -> Any:
        """Call a broker market-data method while tolerating signature drift."""
        try:
            args, kwargs = primary_call
            return method(*args, **kwargs)
        except TypeError:
            args, kwargs = fallback_call
            return method(*args, **kwargs)

    @classmethod
    def _coerce_market_data_frame(cls, result: Any) -> Optional[pd.DataFrame]:
        """Normalize broker candle payload variants into an OHLCV DataFrame."""
        if result is None:
            return None
        if isinstance(result, tuple):
            if len(result) >= 2 and result[1]:
                return None
            result = result[0] if result else None
        if isinstance(result, pd.DataFrame):
            return cls._normalize_ohlcv_columns(result.copy())
        if isinstance(result, Mapping):
            for key in ("candles", "data", "ohlcv", "result", "rows"):
                if key in result:
                    return cls._coerce_market_data_frame(result.get(key))
            return cls._normalize_ohlcv_columns(pd.DataFrame([result]))
        if isinstance(result, (list, tuple)):
            if not result:
                return None
            frame = pd.DataFrame(result)
            if not frame.empty and all(isinstance(col, int) for col in frame.columns):
                # CCXT-style rows: [timestamp, open, high, low, close, volume, ...]
                if len(frame.columns) >= 6:
                    frame = frame.iloc[:, :6]
                    frame.columns = ["timestamp", "open", "high", "low", "close", "volume"]
                # Compact rows occasionally omit timestamp: [open, high, low, close, volume]
                elif len(frame.columns) == 5:
                    frame.columns = ["open", "high", "low", "close", "volume"]
            return cls._normalize_ohlcv_columns(frame)
        return None

    @staticmethod
    def _normalize_ohlcv_columns(frame: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Return a numeric OHLCV frame when the payload has usable candles."""
        if frame is None or frame.empty:
            return None
        rename_map = {
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "price": "close",
            "last": "close",
        }
        normalized = frame.rename(
            columns={col: rename_map.get(str(col).lower(), col) for col in frame.columns}
        )
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(set(normalized.columns)):
            return None
        for col in required:
            normalized[col] = pd.to_numeric(normalized[col], errors="coerce")
        normalized = normalized.dropna(subset=list(required))
        if normalized.empty:
            return None
        return normalized


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------
_loop: Optional[NijaCoreLoop] = None


def get_nija_core_loop(apex_strategy: Any = None, max_positions: int = 5) -> NijaCoreLoop:
    """Return (or lazily create) the module-level singleton NijaCoreLoop.

    ``apex_strategy`` is required only on the first call (when the singleton
    does not yet exist).  Subsequent calls may omit it to retrieve the already-
    created instance.
    """
    global _loop
    if _loop is None:
        if apex_strategy is None:
            raise ValueError(
                "get_nija_core_loop: apex_strategy must be provided on the first call"
            )
        _loop = NijaCoreLoop(apex_strategy=apex_strategy, max_positions=max_positions)
    return _loop


# ---------------------------------------------------------------------------
# Standalone trading loop — for use as a daemon thread target
# ---------------------------------------------------------------------------
# _loop_guard / _loop_running guard against duplicate loop starts:
#   - _loop_guard  : Lock that serialises the check-and-set on _loop_running.
#   - _loop_running: Flag set to True the first time run_trading_loop acquires
#                    the lock; subsequent callers bail out immediately so only
#                    one continuous cycle ever runs.
_loop_guard = threading.Lock()
_loop_running = False
# Hard trading-active flag.  Set to True only after BOTH the hydration and CSM
# barriers have passed.  The main while-loop is conditioned on this flag so the
# loop body never executes until the bot is genuinely ready to trade.
_trading_active = False
# Set to True after _exec_test_probe() fires so the probe only runs once
# per process lifetime, even if NIJA_EXEC_TEST_MODE stays "true" externally.
_exec_test_fired = False
# NOTE: TRADING_ENGINE_READY is defined earlier in this module (alongside
# _current_cycle_id / _current_cycle_capital) so it is guaranteed to exist
# before _supervisor_step_state_machine() is ever called.  Do not redefine it
# here — the earlier definition is the canonical one.  The FORCE_TRADE check
# that sets this event lives in run_trading_loop() so it is evaluated at
# runtime, not at module import time.


# ---------------------------------------------------------------------------
# Execution test probe
# ---------------------------------------------------------------------------

def _exec_test_probe(strategy: Any) -> Dict:
    """
    Fire a single minimal market buy to validate broker connectivity and
    order routing end-to-end.

    Auth, nonce, and exchange connection are intentionally *not* bypassed.
    Strategy scoring filters and the AI entry gate are bypassed via the
    ``reason="EXEC_TEST_PROBE"`` flag that flows through the call stack.

    Returns
    -------
    Dict with the broker response (or an error dict when no broker is found).
    """
    symbol = os.getenv("NIJA_EXEC_TEST_SYMBOL", "BTC/USDT")
    size = float(os.getenv("NIJA_EXEC_TEST_SIZE_USD", "5"))

    broker = getattr(strategy, "broker", None)
    if broker is None:
        bm = getattr(strategy, "broker_manager", None)
        if bm is not None:
            broker = bm.get_primary_broker()

    if broker is None:
        logger.error("🧪 EXEC TEST PROBE: no broker available — cannot execute")
        return {"status": "error", "error": "NO_BROKER"}

    logger.info(
        "🧪 EXEC TEST PROBE → symbol=%s size=$%.2f broker=%s",
        symbol,
        size,
        getattr(getattr(broker, "broker_type", None), "value", type(broker).__name__),
    )

    if submit_market_order_via_pipeline is None:
        result = {
            "status": "error",
            "error": "ExecutionPipeline submit helper unavailable; direct broker fallback blocked",
        }
    else:
        result = submit_market_order_via_pipeline(
            broker=broker,
            symbol=symbol,
            side="buy",
            quantity=size,
            size_type="quote",
            strategy="EXEC_TEST_PROBE",
        )

    return result


def start_trading_engine(strategy: Any) -> threading.Thread:
    """Single, guaranteed entry point for the trading loop thread.

    This is the ONLY function that may spawn a ``run_trading_loop`` thread.
    All callers (``bot.py`` main, ``NijaCoreLoop.start``, etc.) must go
    through here — no one else is permitted to call ``threading.Thread``
    with ``run_trading_loop`` as the target directly.

    Parameters
    ----------
    strategy : TradingStrategy instance (must not be None)

    Returns
    -------
    threading.Thread — the started daemon thread
    """
    logger.critical("🚀 STARTING TRADING ENGINE THREAD")

    # Install graceful shutdown handler before spawning the trading thread so
    # SIGTERM is handled from the main thread (required by Python's signal API).
    if _GRACEFUL_HANDOFF_AVAILABLE and _get_handoff_coordinator is not None:
        try:
            _get_handoff_coordinator().install_shutdown_handler()
            logger.info(
                "start_trading_engine: graceful shutdown handler installed "
                "(SIGTERM will trigger clean lock release)"
            )
        except Exception as _hh_exc:
            logger.warning(
                "start_trading_engine: graceful shutdown handler install failed "
                "(non-fatal): %s",
                _hh_exc,
            )

    t = threading.Thread(
        target=run_trading_loop,
        args=(strategy,),
        name="TradingLoop",
        daemon=True,
    )
    t.start()
    logger.critical("LIFECYCLE: entering live trading runtime")
    return t


def run_trading_loop(strategy: Any, cycle_secs: int = 150) -> None:
    """
    Continuous self-healing trading loop.

    Must be started exclusively via :func:`start_trading_engine`.
    Do NOT spawn this function as a thread target anywhere else.

    Parameters
    ----------
    strategy   : TradingStrategy instance
    cycle_secs : Seconds to sleep between cycles (default 150 = 2.5 min)
    """
    logger.critical("🧵 TRADING LOOP THREAD ALIVE")
    print("🧵 TRADING LOOP THREAD ALIVE — run_trading_loop() entered", flush=True)
    _contract_status = assert_runtime_contract_release_ready(context="run_trading_loop")
    logger.info("Runtime contract status: %s", _contract_status.as_dict())

    global _loop_running, _trading_active
    global _current_cycle_id, _current_cycle_capital, _current_cycle_snapshot

    logger.critical("🔥 ENTERED RUN_TRADING_LOOP FUNCTION")
    print("🔥 ENTERED RUN_TRADING_LOOP FUNCTION", flush=True)

    # ── STEP 1: Resolve runtime mode ──────────────────────────────────────────
    logger.critical("[INIT STEP 1/6] Resolving runtime mode")
    print("[INIT STEP 1/6] Resolving runtime mode", flush=True)
    _runtime_mode = resolve_runtime_mode_safe(logger)
    _live_verified = _is_live_mode(_runtime_mode)
    logger.critical(
        "[INIT STEP 1/6] Runtime mode resolved: live_verified=%s "
        "LIVE_CAPITAL_VERIFIED=%s FORCE_TRADE=%s NIJA_FORCE_ACTIVATION=%s",
        _live_verified,
        os.getenv("LIVE_CAPITAL_VERIFIED", "not_set"),
        os.getenv("FORCE_TRADE", "not_set"),
        os.getenv("NIJA_FORCE_ACTIVATION", "not_set"),
    )
    print(
        f"[INIT STEP 1/6] live_verified={_live_verified} "
        f"LIVE_CAPITAL_VERIFIED={os.getenv('LIVE_CAPITAL_VERIFIED', 'not_set')} "
        f"FORCE_TRADE={os.getenv('FORCE_TRADE', 'not_set')}",
        flush=True,
    )

    if _live_verified and not TRADING_ENGINE_READY.is_set():
        logger.critical(
            "LIVE_CAPITAL_VERIFIED=true detected — bypassing passive activation wait gate"
        )
        TRADING_ENGINE_READY.set()

    # ── FORCE_TRADE: set the start gate at runtime so the trading loop never
    # waits for the bootstrap FSM when an operator override flag is active.
    # Evaluated here (not at module load time) so the environment variable is
    # read when the loop actually starts, not when the module is imported.
    if not TRADING_ENGINE_READY.is_set() and (
        os.environ.get("FORCE_TRADE", "").strip().lower() in ("1", "true", "yes", "on", "enabled")
        or os.environ.get("FORCE_TRADE_MODE", "").strip().lower() in ("1", "true", "yes", "on", "enabled")
    ):
        logger.warning(
            "⚡ FORCE_TRADE: TRADING_ENGINE_READY set at runtime (run_trading_loop entry) — "
            "trading loop will not wait for bootstrap FSM"
        )
        TRADING_ENGINE_READY.set()

    # ── STEP 2: Wait for TRADING_ENGINE_READY with hard total timeout ─────────
    # The wait loop previously had no total deadline — it would spin forever
    # if TRADING_ENGINE_READY was never set (e.g. bootstrap FSM stalled).
    # NIJA_START_GATE_TIMEOUT_S (default 120s) caps the total wait so the
    # loop always proceeds to the first cycle rather than hanging indefinitely.
    logger.critical("[INIT STEP 2/6] Waiting for TRADING_ENGINE_READY start signal")
    print("[INIT STEP 2/6] Waiting for TRADING_ENGINE_READY start signal", flush=True)
    _start_gate_max_s = float(os.getenv("NIJA_START_GATE_TIMEOUT_S", "120"))
    _start_gate_t0 = time.monotonic()
    _start_gate_iters = 0
    while not TRADING_ENGINE_READY.is_set():
        _start_gate_iters += 1
        _elapsed_gate = time.monotonic() - _start_gate_t0
        try:
            if _SM_AVAILABLE and _get_state_machine is not None:
                _wait_sm = _get_state_machine()
                if _wait_sm.is_live_trading_active():
                    logger.critical(
                        "LIVE_ACTIVE detected while waiting for TRADING_ENGINE_READY — releasing start gate"
                    )
                    TRADING_ENGINE_READY.set()
                    break
        except Exception as _wait_gate_err:
            logger.debug("TRADING_ENGINE_READY wait probe failed: %s", _wait_gate_err)

        # Hard total timeout: force-set the event and proceed rather than
        # hanging forever when bootstrap FSM never fires the signal.
        if _elapsed_gate >= _start_gate_max_s:
            logger.critical(
                "⚡ [INIT STEP 2/6] TRADING_ENGINE_READY hard timeout reached after %.0fs "
                "(iter=%d) — force-setting start gate to unblock trading loop. "
                "Set NIJA_START_GATE_TIMEOUT_S to adjust (default 120s).",
                _elapsed_gate,
                _start_gate_iters,
            )
            print(
                f"[INIT STEP 2/6] HARD TIMEOUT: force-setting TRADING_ENGINE_READY after "
                f"{_elapsed_gate:.0f}s (iter={_start_gate_iters})",
                flush=True,
            )
            TRADING_ENGINE_READY.set()
            break

        if not TRADING_ENGINE_READY.wait(timeout=30):
            logger.critical(
                "TIMEOUT_WAITING_FOR_TRADING_ENGINE_READY "
                "(iter=%d elapsed=%.0fs remaining=%.0fs)",
                _start_gate_iters,
                _elapsed_gate,
                max(0.0, _start_gate_max_s - _elapsed_gate),
            )
            print(
                f"[INIT STEP 2/6] Still waiting for start signal "
                f"(iter={_start_gate_iters} elapsed={_elapsed_gate:.0f}s "
                f"remaining={max(0.0, _start_gate_max_s - _elapsed_gate):.0f}s)",
                flush=True,
            )
            try:
                from bot.bootstrap_utils import dump_startup_state
            except ImportError:
                try:
                    from bootstrap_utils import dump_startup_state  # type: ignore[import]
                except ImportError:
                    dump_startup_state = None  # type: ignore[assignment]
            if dump_startup_state is not None:
                dump_startup_state("trading_engine_ready_wait")
    logger.critical("[INIT STEP 2/6] ✅ START SIGNAL RECEIVED — ENTERING LIVE LOOP")
    print("[INIT STEP 2/6] ✅ START SIGNAL RECEIVED — ENTERING LIVE LOOP", flush=True)

    # ── STEP 3: Bootstrap FSM execution authority check ──────────────────────
    logger.critical("[INIT STEP 3/6] Checking bootstrap FSM execution authority")
    print("[INIT STEP 3/6] Checking bootstrap FSM execution authority", flush=True)

    try:
        from bot.bootstrap_state_machine import get_bootstrap_fsm
    except ImportError:
        try:
            from bootstrap_state_machine import get_bootstrap_fsm  # type: ignore[import]
        except ImportError:
            get_bootstrap_fsm = None  # type: ignore[assignment]
    if get_bootstrap_fsm is not None:
        _bfsm_ea = get_bootstrap_fsm()
        if not _bfsm_ea.execution_authority:
            # Fallback: if execution_authority was not set by the normal bootstrap
            # path (e.g. finalize_boot() was skipped), set it now using the fencing
            # token which is already validated.  This prevents a crash when the FSM
            # reaches RUNNING_SUPERVISED but execution_authority was not latched.
            _ft = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
            if _ft and hasattr(_bfsm_ea, "_execution_authority"):
                logger.warning(
                    "execution_authority not set after bootstrap — applying fencing-token "
                    "fallback (token_prefix=%s) to unblock strategy loop",
                    _ft[:8],
                )
                _bfsm_ea._execution_authority = True
            elif hasattr(_bfsm_ea, "_execution_authority"):
                # No fencing token (Redis not configured or distributed lock not acquired).
                # FORCE_TRADE / NIJA_FORCE_ACTIVATION bypass: grant execution authority
                # directly so the trading loop is not permanently blocked in deployments
                # that do not use Redis-based distributed locking.
                _force_bypass_ea = (
                    os.environ.get("FORCE_TRADE", "").strip().lower()
                    in ("1", "true", "yes", "on", "enabled")
                    or os.environ.get("NIJA_FORCE_ACTIVATION", "").strip().lower()
                    in ("1", "true", "yes", "on", "enabled")
                    or os.environ.get("NIJA_SKIP_STARTUP_PHASE_GATE", "").strip().lower()
                    in ("1", "true", "yes", "on", "enabled")
                )
                if _force_bypass_ea:
                    logger.warning(
                        "⚡ execution_authority not set and no fencing token present — "
                        "force flag active, granting execution authority directly to unblock "
                        "trading loop (FORCE_TRADE / NIJA_FORCE_ACTIVATION / NIJA_SKIP_STARTUP_PHASE_GATE)"
                    )
                    _bfsm_ea._execution_authority = True
                else:
                    logger.critical(
                        "🚫 execution_authority not set and no fencing token present — "
                        "trading loop cannot start. Set FORCE_TRADE=true to bypass, or "
                        "configure Redis for distributed locking."
                    )
                    if _loop_guard.acquire(timeout=5):
                        try:
                            _loop_running = False
                        finally:
                            _loop_guard.release()
                    return
            else:
                logger.critical(
                    "🚫 execution_authority not set and BootstrapFSM has no _execution_authority "
                    "attribute — trading loop cannot start safely."
                )
                if _loop_guard.acquire(timeout=5):
                    try:
                        _loop_running = False
                    finally:
                        _loop_guard.release()
                return


    logger.critical("[INIT STEP 3/6] ✅ Bootstrap FSM execution authority check complete")
    print("[INIT STEP 3/6] ✅ Bootstrap FSM execution authority check complete", flush=True)

    # Supervisor-mode hard gate: only block execution when supervisor mode is
    # enabled AND live trading is not active.
    _supervisor_mode = os.getenv("SUPERVISOR_MODE", "false").lower() in (
        "true", "1", "yes", "enabled"
    )
    logger.critical(
        "[PRE-STEP-4] Supervisor mode check: SUPERVISOR_MODE=%s",
        os.getenv("SUPERVISOR_MODE", "false"),
    )
    print(f"[PRE-STEP-4] SUPERVISOR_MODE={os.getenv('SUPERVISOR_MODE', 'false')}", flush=True)
    if _supervisor_mode:
        _live_active_now = False
        try:
            if _SM_AVAILABLE and _get_state_machine is not None:
                _live_active_now = bool(_get_state_machine().is_live_trading_active())
        except Exception as _sm_probe_err:
            logger.debug("Supervisor mode live-state probe failed: %s", _sm_probe_err)

        logger.critical(
            "[PRE-STEP-4] SUPERVISOR_MODE=true — live_active=%s; %s",
            _live_active_now,
            "proceeding" if _live_active_now else "BLOCKING startup (live trading not active)",
        )
        print(
            f"[PRE-STEP-4] SUPERVISOR_MODE=true live_active={_live_active_now}",
            flush=True,
        )
        if not _live_active_now:
            logger.critical(
                "🚫 [PRE-STEP-4] SUPERVISOR_MODE enabled while live mode is inactive — "
                "blocking run_trading_loop startup. "
                "Set SUPERVISOR_MODE=false or ensure live trading is active to proceed."
            )
            print(
                "[PRE-STEP-4] BLOCKED: SUPERVISOR_MODE=true but live trading is not active — "
                "trading loop will not start. Set SUPERVISOR_MODE=false to bypass.",
                flush=True,
            )
            return

    # ── Strategy existence guard ────────────────────────────────────────────
    # Must be checked BEFORE acquiring _loop_guard / setting _loop_running so
    # that a None strategy never permanently blocks future valid start attempts.
    # A None strategy here means the caller violated the contract (strategy must
    # exist before TradingCoreLoop starts) — refuse to proceed.
    logger.critical("[PRE-STEP-4] Strategy existence check: strategy=%s", type(strategy).__name__)
    print(f"[PRE-STEP-4] strategy type={type(strategy).__name__}", flush=True)
    if strategy is None:
        logger.critical(
            "🚫 run_trading_loop called with strategy=None — "
            "refusing to start; _loop_running NOT set so the loop can be "
            "started correctly once strategy is available."
        )
        return

    try:
        logger.critical(
            "[PRE-STEP-4] LOOP START CHECK — _loop_running=%s; attempting _loop_guard acquire",
            _loop_running,
        )
        print(
            f"[PRE-STEP-4] _loop_running={_loop_running} — acquiring _loop_guard (timeout=10s)",
            flush=True,
        )
        # Use acquire(timeout=...) instead of the bare `with` context manager so
        # that a stale lock held by a crashed/stuck previous thread does not block
        # the startup sequence indefinitely.  10 seconds is generous — the lock
        # should never be held for more than a few microseconds in normal operation.
        _loop_guard_timeout_s = float(os.getenv("NIJA_LOOP_GUARD_TIMEOUT_S", "10"))
        _loop_guard_acquired = _loop_guard.acquire(timeout=_loop_guard_timeout_s)
        if not _loop_guard_acquired:
            logger.critical(
                "⚠️ [PRE-STEP-4] _loop_guard.acquire() timed out after %.0fs — "
                "another thread may be holding the lock. Proceeding without guard "
                "to prevent indefinite startup hang. _loop_running=%s",
                _loop_guard_timeout_s,
                _loop_running,
            )
            print(
                f"[PRE-STEP-4] WARNING: _loop_guard timed out after {_loop_guard_timeout_s:.0f}s "
                f"— proceeding without guard. _loop_running={_loop_running}",
                flush=True,
            )
            # If _loop_running is already True, another instance is running — bail out.
            if _loop_running:
                logger.critical(
                    "🚧 [PRE-STEP-4] _loop_running=True and lock timed out — "
                    "duplicate start detected; exiting this invocation."
                )
                return
            # Lock timed out but _loop_running is False — force-set it and proceed.
            _loop_running = True
        else:
            try:
                if _loop_running:
                    logger.critical(
                        "🚧 [PRE-STEP-4] LOOP BLOCKED PATH REACHED — duplicate start guard triggered "
                        "(_loop_running=True). Exiting this invocation."
                    )
                    print(
                        "[PRE-STEP-4] BLOCKED: _loop_running=True — duplicate start guard triggered",
                        flush=True,
                    )
                    return
                _loop_running = True
                logger.critical("[PRE-STEP-4] _loop_guard acquired and _loop_running set to True")
                print("[PRE-STEP-4] _loop_guard acquired — _loop_running=True", flush=True)
            finally:
                _loop_guard.release()

        logger.info("🟢 Trading loop alive (INITIAL START)")

        # ── STEP 4: Capital Hydration Barrier ─────────────────────────────────
        logger.critical("[INIT STEP 4/6] Entering capital hydration barrier")
        print("[INIT STEP 4/6] Entering capital hydration barrier", flush=True)

        # ── Capital Hydration Barrier (FIX 1) ─────────────────────────────────
        # Block until CapitalAuthority has received at least one broker snapshot.
        # This prevents the race where the strategy loop evaluates capital before
        # any broker balance has been fetched (returning $0.00), which caused the
        # "Balance $0.00 below minimum / AUTO mode fallback" log pattern.
        # Timeout: 30 s (configurable via NIJA_HYDRATION_BARRIER_TIMEOUT).
        _hydration_timeout = float(
            os.getenv("NIJA_HYDRATION_BARRIER_TIMEOUT", "30")
        )
        logger.critical(
            "[INIT STEP 4/6] Capital hydration barrier: timeout=%.0fs "
            "CAPITAL_HYDRATED_EVENT_set=%s",
            _hydration_timeout,
            bool(_CAPITAL_HYDRATED_EVENT is not None and _CAPITAL_HYDRATED_EVENT.is_set())
            if _CA_LOOP_AVAILABLE else "CA_unavailable",
        )
        print(
            f"[INIT STEP 4/6] hydration timeout={_hydration_timeout:.0f}s "
            f"CA_available={_CA_LOOP_AVAILABLE}",
            flush=True,
        )
        try:
            try:
                from bot.capital_authority import (
                    wait_for_hydration as _wait_hydration,
                    CapitalIntegrityError as _CapIntegrityErr,
                )
            except ImportError:
                from capital_authority import (  # type: ignore[import]
                    wait_for_hydration as _wait_hydration,
                    CapitalIntegrityError as _CapIntegrityErr,
                )
            logger.critical("[INIT STEP 4/6] Calling wait_for_hydration(timeout_s=%.0fs)", _hydration_timeout)
            print(f"[INIT STEP 4/6] wait_for_hydration() starting (timeout={_hydration_timeout:.0f}s)", flush=True)
            _wait_hydration(timeout_s=_hydration_timeout)
            logger.critical(
                "✅ [HYDRATION_BARRIER] Capital hydration confirmed — "
                "is_hydrated=True, broker snapshot received. Proceeding to trading loop."
            )
        except _CapIntegrityErr as _hb_err:
            # ── FORCE FLAG BYPASS ─────────────────────────────────────────────
            # When NIJA_SKIP_STARTUP_PHASE_GATE=true, NIJA_FORCE_ACTIVATION=true,
            # or FORCE_TRADE=true, proceed past the hydration barrier even if the
            # capital pipeline has not yet delivered a snapshot.
            _hb_force_bypass = (
                os.environ.get("NIJA_SKIP_STARTUP_PHASE_GATE", "").strip().lower()
                in ("1", "true", "yes", "on", "enabled")
                or os.environ.get("NIJA_FORCE_ACTIVATION", "").strip().lower()
                in ("1", "true", "yes", "on", "enabled")
                or os.environ.get("FORCE_TRADE", "").strip().lower()
                in ("1", "true", "yes", "on", "enabled")
            )
            if _hb_force_bypass:
                logger.warning(
                    "⚡ [HYDRATION_BARRIER] CAPITAL INTEGRITY ERROR bypassed — force flag active. "
                    "error=%s (NIJA_SKIP_STARTUP_PHASE_GATE / NIJA_FORCE_ACTIVATION / FORCE_TRADE)",
                    _hb_err,
                )
            else:
                # ── HARD-TIMEOUT BYPASS ───────────────────────────────────────
                # Previously this path aborted the trading loop entirely, which
                # caused a silent hang (the thread exited with no further logs).
                # Now we log a critical warning and proceed anyway — a hydration
                # timeout means the capital pipeline is slow, not that the bot
                # should stop trading.  The downstream strategy cycle will handle
                # a $0 balance gracefully (skip entries, wait for next cycle).
                logger.critical(
                    "⚠️ [HYDRATION_BARRIER] CAPITAL INTEGRITY ERROR: %s — "
                    "proceeding past hydration barrier after timeout to prevent "
                    "trading loop abort. Set NIJA_SKIP_STARTUP_PHASE_GATE=true or "
                    "FORCE_TRADE=true to suppress this warning.",
                    _hb_err,
                )
                print(
                    f"[INIT STEP 4/6] WARNING: hydration barrier timed out ({_hb_err}) — "
                    "proceeding anyway to prevent loop abort",
                    flush=True,
                )
        except (ImportError, Exception) as _hb_exc:
            logger.warning(
                "⚠️ [HYDRATION_BARRIER] Could not enforce hydration barrier (%s) — "
                "proceeding without guarantee. Check capital_authority module.",
                _hb_exc,
            )
        logger.critical("[INIT STEP 4/6] ✅ Capital hydration barrier passed")
        print("[INIT STEP 4/6] ✅ Capital hydration barrier passed", flush=True)
        # ── End Capital Hydration Barrier ──────────────────────────────────────

        # ── STEP 5: CSM v2 Ready Barrier ──────────────────────────────────────
        logger.critical("[INIT STEP 5/6] Entering CSM v2 ready barrier")
        print("[INIT STEP 5/6] Entering CSM v2 ready barrier", flush=True)

        # ── CSM v2 Ready Barrier ───────────────────────────────────────────────
        # Block until CapitalCSMv2 transitions to READY state.  This is the
        # second hard barrier (after hydration) and ensures that all readiness
        # criteria (LIVE_CAPITAL_VERIFIED, positive balance, confidence score,
        # fresh snapshot) are satisfied before the first strategy cycle runs.
        _csm_timeout = float(os.getenv("NIJA_CSM_READY_TIMEOUT", "30"))
        logger.critical(
            "[INIT STEP 5/6] CSM v2 ready barrier: timeout=%.0fs "
            "LIVE_CAPITAL_VERIFIED=%s NIJA_CSM_READY_TIMEOUT=%s",
            _csm_timeout,
            os.getenv("LIVE_CAPITAL_VERIFIED", "not_set"),
            os.getenv("NIJA_CSM_READY_TIMEOUT", "30_default"),
        )
        print(
            f"[INIT STEP 5/6] CSM timeout={_csm_timeout:.0f}s "
            f"LIVE_CAPITAL_VERIFIED={os.getenv('LIVE_CAPITAL_VERIFIED', 'not_set')}",
            flush=True,
        )
        try:
            try:
                from bot.capital_csm_v2 import (
                    get_csm_v2 as _get_csm_v2,
                    CapitalIntegrityError as _CsmIntegrityErr,
                )
            except ImportError:
                from capital_csm_v2 import (  # type: ignore[import]
                    get_csm_v2 as _get_csm_v2,
                    CapitalIntegrityError as _CsmIntegrityErr,
                )
            _csm = _get_csm_v2()
            logger.critical(
                "[INIT STEP 5/6] CSM PRE-WAIT STATE: %s is_hydrated=%s blocked_reason=%r",
                _csm.state,
                _csm.is_hydrated,
                getattr(_csm, "blocked_reason", ""),
            )
            print(
                f"[INIT STEP 5/6] CSM pre-wait state={_csm.state} "
                f"is_hydrated={_csm.is_hydrated}",
                flush=True,
            )
            _csm_ready = _csm.wait_for_ready(timeout=_csm_timeout)
            logger.critical(
                "[INIT STEP 5/6] CSM POST-WAIT STATE: %s ready=%s",
                _csm.state,
                _csm_ready,
            )
            print(
                f"[INIT STEP 5/6] CSM post-wait state={_csm.state} ready={_csm_ready}",
                flush=True,
            )
            if not _csm_ready:
                # DEGRADED = capital exists but confidence score below threshold.
                # This is NOT a fatal condition — allow the loop to proceed so
                # trades can still execute.  Only BLOCKED (zero capital or env
                # gate closed) is truly fatal.
                from bot.capital_csm_v2 import CapitalCSMState as _CsmState  # noqa: F811
                _csm_state_now = _csm.state
                if _csm_state_now == _CsmState.DEGRADED:
                    logger.critical(
                        "⚠️ CSM DEGRADED (low confidence) — loop will proceed with caution. "
                        "reason=%s",
                        _csm.blocked_reason,
                    )
                elif _csm_state_now == _CsmState.BLOCKED:
                    # ── FORCE FLAG BYPASS ─────────────────────────────────────
                    # When NIJA_SKIP_STARTUP_PHASE_GATE=true, NIJA_FORCE_ACTIVATION=true,
                    # or FORCE_TRADE=true the operator has explicitly acknowledged that
                    # the CSM gate may not be satisfied (e.g. capital pipeline has not
                    # yet delivered a snapshot) and wants the trading loop to start
                    # immediately.  Treat BLOCKED as DEGRADED in this case so the loop
                    # proceeds rather than aborting.
                    _csm_force_bypass = (
                        os.environ.get("NIJA_SKIP_STARTUP_PHASE_GATE", "").strip().lower()
                        in ("1", "true", "yes", "on", "enabled")
                        or os.environ.get("NIJA_FORCE_ACTIVATION", "").strip().lower()
                        in ("1", "true", "yes", "on", "enabled")
                        or os.environ.get("FORCE_TRADE", "").strip().lower()
                        in ("1", "true", "yes", "on", "enabled")
                    )
                    if _csm_force_bypass:
                        logger.warning(
                            "⚡ CSM BLOCKED but force flag active — bypassing CSM gate and proceeding. "
                            "reason=%s (NIJA_SKIP_STARTUP_PHASE_GATE / NIJA_FORCE_ACTIVATION / FORCE_TRADE)",
                            _csm.blocked_reason,
                        )
                    else:
                        # ── HARD-TIMEOUT BYPASS ───────────────────────────────
                        # Previously this path raised _CsmIntegrityErr which was
                        # caught below and caused the trading loop to abort (return),
                        # producing a silent hang with no further log output.
                        # Now we log a critical warning and proceed — a BLOCKED CSM
                        # state (e.g. LIVE_CAPITAL_VERIFIED not set, or capital
                        # pipeline not yet delivered a snapshot) should not
                        # permanently prevent the loop from running.  The downstream
                        # strategy cycle and execution engine enforce their own gates.
                        logger.critical(
                            "⚠️ [CSM-BARRIER] CSM BLOCKED — proceeding past barrier to prevent "
                            "trading loop abort. reason=%s  "
                            "Set NIJA_SKIP_STARTUP_PHASE_GATE=true or FORCE_TRADE=true to "
                            "suppress this warning. Trades will be blocked by execution engine "
                            "until CSM reaches READY state.",
                            _csm.blocked_reason,
                        )
                        print(
                            f"[INIT STEP 5/6] WARNING: CSM BLOCKED ({_csm.blocked_reason}) — "
                            "proceeding anyway to prevent loop abort",
                            flush=True,
                        )
                else:
                    # INITIALIZING after timeout — try a verified repair before giving up.
                    # Proceeding with INITIALIZING means no capital snapshot has been
                    # ingested; this is more severe than DEGRADED (low confidence).
                    # Attempt to inject a fresh CA snapshot to advance the CSM state.
                    logger.critical(
                        "⛔ [CSM_BLOCKED] CSM still INITIALIZING after %.0fs — "
                        "attempting verified repair before proceeding. state=%s",
                        _csm_timeout,
                        _csm_state_now.value,
                    )
                    print(
                        f"[INIT STEP 5/6] CSM_BLOCKED state=INITIALIZING after {_csm_timeout:.0f}s — "
                        "attempting repair",
                        flush=True,
                    )
                    _csm_repair_done = False
                    try:
                        try:
                            from bot.capital_authority import get_capital_authority as _get_repair_ca
                        except ImportError:
                            from capital_authority import get_capital_authority as _get_repair_ca  # type: ignore[import]
                        _repair_ca = _get_repair_ca()
                        if _repair_ca is not None and getattr(_repair_ca, "is_hydrated", False):
                            _repair_snap = None
                            if callable(getattr(_repair_ca, "get_snapshot", None)):
                                _repair_snap = _repair_ca.get_snapshot()
                            if _repair_snap is not None:
                                _csm.ingest_snapshot(_repair_snap)
                                _csm_repair_done = True
                                logger.critical(
                                    "🔧 [CSM-BARRIER] Repair snapshot injected — csm_state=%s",
                                    _csm.state,
                                )
                    except Exception as _csm_repair_err:
                        logger.warning("[CSM-BARRIER] CSM repair probe failed: %s", _csm_repair_err)

                    _csm_state_post_repair = _csm.state
                    if _csm_state_post_repair == _CsmState.INITIALIZING:
                        logger.critical(
                            "⛔ [CSM_BLOCKED] CSM remains INITIALIZING after repair — "
                            "proceeding with degraded capital confidence. "
                            "Trades will be blocked by execution engine until CSM reaches READY. "
                            "repair_attempted=%s",
                            _csm_repair_done,
                        )
                        print(
                            f"[INIT STEP 5/6] CSM_BLOCKED: still INITIALIZING after repair "
                            f"(repair_attempted={_csm_repair_done}) — proceeding with caution",
                            flush=True,
                        )
                    else:
                        logger.critical(
                            "✅ [CSM-BARRIER] CSM advanced past INITIALIZING via repair: %s",
                            _csm_state_post_repair.value,
                        )
            else:
                logger.critical(
                    "✅ CAPITAL READY — STARTING TRADING LOOP"
                )
        except Exception as _csm_exc:
            # Catch both _CsmIntegrityErr and any other exception from the CSM
            # barrier.  Previously _CsmIntegrityErr caused a hard abort (return)
            # which silently killed the trading thread.  Now we log and proceed.
            logger.critical(
                "⚠️ [CSM-BARRIER] CSM barrier raised exception (%s: %s) — "
                "proceeding past barrier to prevent trading loop abort. "
                "Trades will be blocked by execution engine until CSM reaches READY state.",
                type(_csm_exc).__name__,
                _csm_exc,
            )
            print(
                f"[INIT STEP 5/6] WARNING: CSM barrier exception ({type(_csm_exc).__name__}: "
                f"{_csm_exc}) — proceeding anyway",
                flush=True,
            )
        logger.critical("[INIT STEP 5/6] ✅ CSM v2 ready barrier passed")
        print("[INIT STEP 5/6] ✅ CSM v2 ready barrier passed", flush=True)
        # ── End CSM v2 Ready Barrier ───────────────────────────────────────────

        # ── STEP 5.5: Capital snapshot pre-validation ──────────────────────────
        # Before entering the trading loop, verify that a nonzero CapitalAuthority
        # snapshot is available.  If the snapshot shows total=0 or valid_brokers=0,
        # wait briefly for the capital pipeline to deliver a valid value rather than
        # silently entering a $0 first cycle.
        # Timeout is intentionally short (10 s default) — we have already waited up
        # to 30 s in the hydration barrier.  This step only catches the race where
        # is_hydrated=True but the first capital value has not yet propagated.
        _cap_precheck_timeout = float(os.getenv("NIJA_CAP_PRECHECK_TIMEOUT_S", "10"))
        logger.critical(
            "[INIT STEP 5.5] Capital snapshot pre-validation: timeout=%.0fs",
            _cap_precheck_timeout,
        )
        print(f"[INIT STEP 5.5] Capital snapshot pre-validation timeout={_cap_precheck_timeout:.0f}s", flush=True)
        _cap_precheck_t0 = time.monotonic()
        _cap_precheck_ok = False
        while time.monotonic() - _cap_precheck_t0 < _cap_precheck_timeout:
            _precheck_snap = _capture_cycle_capital_state()
            _precheck_total = float(_precheck_snap.get("ca_total_capital", 0.0) or 0.0)
            _precheck_vb = int(_precheck_snap.get("ca_valid_brokers", 0) or 0)
            if _precheck_total > 0.0 and _precheck_vb >= 1:
                _cap_precheck_ok = True
                logger.critical(
                    "✅ [CAP_PRECHECK] Capital snapshot valid before first cycle: "
                    "total=$%.2f valid_brokers=%d",
                    _precheck_total,
                    _precheck_vb,
                )
                break
            logger.debug(
                "[CAP_PRECHECK] Waiting for nonzero capital snapshot "
                "(total=%.2f valid_brokers=%d elapsed=%.1fs/%.0fs)",
                _precheck_total,
                _precheck_vb,
                time.monotonic() - _cap_precheck_t0,
                _cap_precheck_timeout,
            )
            time.sleep(1.0)
        if not _cap_precheck_ok:
            _precheck_snap = _capture_cycle_capital_state()
            _precheck_total = float(_precheck_snap.get("ca_total_capital", 0.0) or 0.0)
            _precheck_vb = int(_precheck_snap.get("ca_valid_brokers", 0) or 0)
            logger.critical(
                "⚠️ [CAP_PRECHECK] Capital snapshot pre-validation timed out after %.0fs — "
                "proceeding with total=$%.2f valid_brokers=%d. "
                "First cycle may execute with degraded capital confidence.",
                _cap_precheck_timeout,
                _precheck_total,
                _precheck_vb,
            )
            print(
                f"[INIT STEP 5.5] CAP_PRECHECK timeout: total={_precheck_total:.2f} "
                f"valid_brokers={_precheck_vb} — proceeding anyway",
                flush=True,
            )
        logger.critical("[INIT STEP 5.5] ✅ Capital snapshot pre-validation complete")
        print("[INIT STEP 5.5] ✅ Capital snapshot pre-validation complete", flush=True)
        # ── End Capital snapshot pre-validation ───────────────────────────────

        # ── Trading Loop Entry Anchor (FIX 1) ─────────────────────────────────
        # Both hydration and CSM barriers have passed.  Arm the trading-active
        # flag HERE and verify it before entering the loop — this is the single
        # authoritative gate.  If the assert fires something above cleared the
        # flag unexpectedly; that is a logic bug that must be surfaced loudly.
        # ── STEP 6: Arm trading-active flag and enter cycle loop ─────────────
        logger.critical("[INIT STEP 6/6] Arming trading-active flag and entering cycle loop")
        print("[INIT STEP 6/6] Arming trading-active flag and entering cycle loop", flush=True)
        _trading_active = True
        if not _trading_active:
            logger.critical("💥 _trading_active failed to set — logic error, aborting")
            raise RuntimeError("_trading_active must be True before entering trading loop")
        logger.critical("🚀 ENTERING TRADING LOOP - FINAL GATE PASSED")
        print("🚀 ENTERING TRADING LOOP - FINAL GATE PASSED — all barriers cleared", flush=True)
        logger.critical("[INIT STEP 6/6] ✅ All init steps complete — first cycle starting now")
        print("[INIT STEP 6/6] ✅ All init steps complete — first cycle starting now", flush=True)
        # ── End Trading Loop Entry Anchor ──────────────────────────────────────

        cycle = 0
        _skipped_cycles = 0          # consecutive cycles skipped due to no broker
        _MAX_SKIP_LOG_INTERVAL = 5   # log downtime banner every N skipped cycles
        _activation_idle_since = None
        _activation_idle_timeout_s = float(os.getenv("NIJA_IDLE_ACTIVATION_TIMEOUT_S", "90") or 90)
        _watchdog_backoff_enabled = _env_truthy("NIJA_WATCHDOG_BACKOFF_ENABLED")
        _watchdog_backoff_max_multiplier = max(
            1.0,
            float(os.getenv("NIJA_WATCHDOG_BACKOFF_MAX_MULTIPLIER", "8") or 8),
        )
        _activation_retry_count = 0
        _next_activation_attempt_ts = 0.0
        _last_cycle_skip_signature = None
        _tick_log_every = max(1, int(float(os.getenv("NIJA_CORE_LOOP_TICK_LOG_EVERY", "10") or 10)))

        logger.critical("🚀 ENTERING ACTIVE TRADE LOOP")
        print("🚀 ENTERING ACTIVE TRADE LOOP — cycle scheduler starting", flush=True)
        try:
            from bot.bootstrap_state_machine import get_bootstrap_fsm
        except ImportError:
            try:
                from bootstrap_state_machine import get_bootstrap_fsm  # type: ignore[import]
            except ImportError:
                get_bootstrap_fsm = None  # type: ignore[assignment]
        if get_bootstrap_fsm is not None:
            _bfsm_sched = get_bootstrap_fsm()
            if not _bfsm_sched.execution_authority:
                # Fallback: same fencing-token recovery as the strategy loop gate above.
                _ft_sched = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
                if _ft_sched and hasattr(_bfsm_sched, "_execution_authority"):
                    logger.warning(
                        "execution_authority not set before scheduler — applying fencing-token "
                        "fallback (token_prefix=%s) to unblock cycle scheduler",
                        _ft_sched[:8],
                    )
                    _bfsm_sched._execution_authority = True
                elif hasattr(_bfsm_sched, "_execution_authority"):
                    # No fencing token (Redis not configured or distributed lock not acquired).
                    # FORCE_TRADE / NIJA_FORCE_ACTIVATION bypass: grant execution authority
                    # directly so the cycle scheduler is not permanently blocked in deployments
                    # that do not use Redis-based distributed locking.
                    _force_bypass_sched = (
                        os.environ.get("FORCE_TRADE", "").strip().lower()
                        in ("1", "true", "yes", "on", "enabled")
                        or os.environ.get("NIJA_FORCE_ACTIVATION", "").strip().lower()
                        in ("1", "true", "yes", "on", "enabled")
                        or os.environ.get("NIJA_SKIP_STARTUP_PHASE_GATE", "").strip().lower()
                        in ("1", "true", "yes", "on", "enabled")
                    )
                    if _force_bypass_sched:
                        logger.warning(
                            "⚡ execution_authority not set and no fencing token present — "
                            "force flag active, granting execution authority directly to unblock "
                            "cycle scheduler (FORCE_TRADE / NIJA_FORCE_ACTIVATION / NIJA_SKIP_STARTUP_PHASE_GATE)"
                        )
                        _bfsm_sched._execution_authority = True
                    else:
                        logger.critical(
                            "🚫 execution_authority not set and no fencing token present — "
                            "cycle scheduler cannot start. Set FORCE_TRADE=true to bypass, or "
                            "configure Redis for distributed locking."
                        )
                        if _loop_guard.acquire(timeout=5):
                            try:
                                _loop_running = False
                            finally:
                                _loop_guard.release()
                        return
                else:
                    # Graceful fallback: same force-flag recovery as the strategy loop
                    # gate above.  A hard assert here crashes the trading thread
                    # silently; instead, check for FORCE_TRADE / NIJA_FORCE_ACTIVATION /
                    # NIJA_SKIP_STARTUP_PHASE_GATE and grant authority when set.
                    _force_flags_sched = (
                        os.environ.get("FORCE_TRADE", "").strip().lower() in ("1", "true", "yes", "on", "enabled")
                        or os.environ.get("NIJA_FORCE_ACTIVATION", "").strip().lower() in ("1", "true", "yes", "on", "enabled")
                        or os.environ.get("NIJA_SKIP_STARTUP_PHASE_GATE", "").strip().lower() in ("1", "true", "yes", "on", "enabled")
                    )
                    if _force_flags_sched and hasattr(_bfsm_sched, "_execution_authority"):
                        logger.warning(
                            "execution_authority not set and no fencing token — "
                            "FORCE flag detected, granting execution_authority to unblock cycle scheduler"
                        )
                        print("[NIJA] FORCE flag: granting execution_authority for cycle scheduler")
                        _bfsm_sched._execution_authority = True
                    else:
                        logger.critical(
                            "execution_authority not set, no fencing token, and no FORCE flag — "
                            "cycle scheduler cannot start; set FORCE_TRADE=true to override"
                        )
                        print("[NIJA] ERROR: execution_authority missing — cycle scheduler blocked")
                    logger.critical(
                        "🚫 execution_authority not set and BootstrapFSM has no _execution_authority "
                        "attribute — cycle scheduler cannot start safely."
                    )
                    if _loop_guard.acquire(timeout=5):
                        try:
                            _loop_running = False
                        finally:
                            _loop_guard.release()
                    return
        logger.critical("LIFECYCLE: entering cycle scheduler")
        while _trading_active:
            try:
                # Graceful shutdown gate: stop accepting new cycles when SIGTERM
                # has been received.  The shutdown handler waits for in-flight
                # trades to complete before releasing the lock, so we exit the
                # loop cleanly here rather than starting a new cycle.
                if _GRACEFUL_HANDOFF_AVAILABLE and _get_handoff_coordinator is not None:
                    try:
                        if _get_handoff_coordinator().is_shutting_down:
                            logger.critical(
                                "🛑 GRACEFUL SHUTDOWN: trading loop exiting — "
                                "SIGTERM received, no new cycles will start"
                            )
                            _trading_active = False
                            break
                    except Exception as _shutdown_check_err:
                        logger.debug(
                            "Graceful shutdown check failed (non-fatal): %s",
                            _shutdown_check_err,
                        )

                # FIX 4: emit every cycle so a silent dead-bot is immediately visible.
                _rate_limited_critical("core_loop_tick", "scheduler", 30.0, "🟢 LIVE LOOP TICK")
                if cycle == 0 or ((cycle + 1) % _tick_log_every == 0):
                    logger.info("🟢 LIVE LOOP TICK | cycle=%s", cycle + 1)
                # Always print cycle iteration to stdout so Railway logs show the loop is alive.
                print(f"🔄 TRADING LOOP CYCLE ITERATION | cycle={cycle + 1}", flush=True)
                if _env_truthy("NIJA_STDOUT_LOOP_TICK", "false"):
                    print("🚀 MAIN LOOP TICK")
                logger.info("[ScannerLoop] heartbeat cycle=%s phase=pre_activation_gate", cycle + 1)

                _live_now = False
                _sm_loop = None
                try:
                    if _SM_AVAILABLE and _get_state_machine is not None:
                        _sm_loop = _get_state_machine()
                        _live_now = bool(_sm_loop.is_live_trading_active())
                except Exception as _sm_loop_err:
                    logger.debug("CORE LOOP live probe failed: %s", _sm_loop_err)
                _rate_limited_critical(
                    "core_loop_activation_eval",
                    "scheduler",
                    30.0,
                    "🧠 CORE LOOP ACTIVE — evaluating activation",
                )
                _rate_limited_critical(
                    "core_loop_live_state",
                    "scheduler",
                    30.0,
                    "CORE LOOP TICK | live=%s",
                    _live_now,
                )
                logger.debug("🧠 CORE LOOP ACTIVE — evaluating activation")
                logger.debug("CORE LOOP TICK | live=%s", _live_now)

                if _sm_loop is not None:
                    _runtime_mode_loop = resolve_runtime_mode_safe(logger)
                    _live_verified_loop = _is_live_mode(_runtime_mode_loop)
                    try:
                        _current_state_loop = _sm_loop.get_current_state()
                    except Exception:
                        _current_state_loop = None

                    # Unified lifecycle arming path: OFF -> LIVE_PENDING_CONFIRMATION
                    # before attempting final activation to LIVE_ACTIVE.
                    #
                    # NOTE: `and not _live_now` was intentionally removed here.
                    # is_live_trading_active() returns True when FORCE_TRADE=true even
                    # when state is still OFF, which caused this arm to silently skip
                    # and state to remain stuck at OFF.  Since we already guard with
                    # `_current_state_loop == _TradingState.OFF`, the extra check is
                    # redundant under correct behaviour and harmful under FORCE_TRADE.
                    if (
                        _live_verified_loop
                        and _current_state_loop == _TradingState.OFF
                    ):
                        try:
                            _sm_loop.transition_to(
                                _TradingState.LIVE_PENDING_CONFIRMATION,
                                "core loop arming: LIVE_CAPITAL_VERIFIED set",
                            )
                            logger.info("🟡 LIFECYCLE ARM: OFF -> LIVE_PENDING_CONFIRMATION")
                            _current_state_loop = _TradingState.LIVE_PENDING_CONFIRMATION
                        except Exception as _arm_err:
                            logger.warning("Core loop arm transition failed: %s", _arm_err)

                # Capture a fresh frozen capital snapshot BEFORE activation so
                # activation gates never evaluate stale previous-cycle values.
                _next_cycle = cycle + 1
                _current_cycle_snapshot = None  # clear previous cycle's snapshot
                _current_cycle_id = (
                    f"cycle-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{_next_cycle:06d}"
                )
                _current_cycle_capital = _capture_cycle_capital_state()
                _cycle_balance = _current_cycle_capital.get("ca_total_capital", 0.0)

                if _sm_loop is not None and not _live_now:
                    _now_mono = time.monotonic()
                    if _now_mono >= _next_activation_attempt_ts:
                        logger.debug("⚡ ATTEMPTING AUTO-ACTIVATION")
                        try:
                            _sm_loop.maybe_auto_activate(cycle_capital=_current_cycle_capital)
                            _activation_retry_count = 0
                            _next_activation_attempt_ts = 0.0
                        except Exception as _auto_act_err:
                            _activation_retry_count += 1
                            _delay_s = _watchdog_backoff_delay(
                                1.0,
                                _activation_retry_count - 1,
                                _watchdog_backoff_enabled,
                                _watchdog_backoff_max_multiplier,
                            )
                            _next_activation_attempt_ts = time.monotonic() + _delay_s
                            logger.warning("Core loop maybe_auto_activate failed: %s", _auto_act_err)
                    else:
                        logger.debug(
                            "Activation retry backoff active: %.1fs remaining",
                            max(0.0, _next_activation_attempt_ts - _now_mono),
                        )

                    # Idle fallback: if activation remains inactive too long,
                    # perform a safe re-arm/retry cycle (no gate bypass).
                    if _activation_idle_since is None:
                        _activation_idle_since = time.monotonic()
                    _idle_elapsed = time.monotonic() - _activation_idle_since
                    if _idle_elapsed >= _activation_idle_timeout_s:
                        logger.critical(
                            "⏱️ ACTIVATION IDLE TIMEOUT: %.1fs elapsed — re-arming lifecycle and retrying activation",
                            _idle_elapsed,
                        )
                        try:
                            _state_now = _sm_loop.get_current_state()
                            if _state_now == _TradingState.LIVE_PENDING_CONFIRMATION:
                                _sm_loop.transition_to(
                                    _TradingState.OFF,
                                    "idle activation fallback: reset arm",
                                )
                            if _sm_loop.get_current_state() == _TradingState.OFF:
                                _sm_loop.transition_to(
                                    _TradingState.LIVE_PENDING_CONFIRMATION,
                                    "idle activation fallback: re-arm",
                                )
                            _sm_loop.maybe_auto_activate(cycle_capital=_current_cycle_capital)
                        except Exception as _idle_retry_err:
                            _activation_retry_count += 1
                            _delay_s = _watchdog_backoff_delay(
                                1.0,
                                _activation_retry_count - 1,
                                _watchdog_backoff_enabled,
                                _watchdog_backoff_max_multiplier,
                            )
                            _next_activation_attempt_ts = time.monotonic() + _delay_s
                            logger.warning("Idle activation fallback retry failed: %s", _idle_retry_err)
                        finally:
                            _activation_idle_since = time.monotonic()
                else:
                    _activation_idle_since = None
                    _activation_retry_count = 0
                    _next_activation_attempt_ts = 0.0

                    if os.getenv("NIJA_FORCE_LIVE_BYPASS", "false").lower() in (
                        "true", "1", "yes", "enabled"
                    ):
                        logger.error(
                            "NIJA_FORCE_LIVE_BYPASS requested but ignored: forced activation bypass is disabled"
                        )

                # FIX 5: assert we are executing on the correct named thread.
                assert threading.current_thread().name == "TradingLoop", (
                    f"run_trading_loop executing on wrong thread: "
                    f"{threading.current_thread().name!r} (expected 'TradingLoop')"
                )

                cycle += 1

                if cycle == 1:
                    logger.critical("🟢 TRADING LOOP ACTIVE — FIRST TICK REACHED")
                    logger.critical("✅ FIRST STRATEGY TICK")
                    # Emit a clear operator diagnostic if LIVE_CAPITAL_VERIFIED is not set.
                    _runtime_mode_cycle = resolve_runtime_mode_safe(logger)
                    _lcv_val = (
                        _runtime_mode_cycle.raw.get("LIVE_CAPITAL_VERIFIED", "false")
                        if _runtime_mode_cycle is not None
                        else os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower().strip()
                    )
                    _live_trading_val = (
                        _runtime_mode_cycle.raw.get("LIVE_TRADING", "false")
                        if _runtime_mode_cycle is not None
                        else os.getenv("LIVE_TRADING", "false").lower().strip()
                    )
                    _dry_run_val = (
                        _runtime_mode_cycle.raw.get("DRY_RUN_MODE", "false")
                        if _runtime_mode_cycle is not None
                        else os.getenv("DRY_RUN_MODE", "false").lower().strip()
                    )
                    _force_trade_val = os.getenv("FORCE_TRADE", "").lower().strip() or "false"
                    _force_trade_mode_val = os.getenv("FORCE_TRADE_MODE", "").lower().strip() or "false"
                    logger.critical(
                        "⚙️ MODE FLAGS | LIVE_CAPITAL_VERIFIED=%r LIVE_TRADING=%r DRY_RUN_MODE=%r "
                        "FORCE_TRADE=%r FORCE_TRADE_MODE=%r",
                        _lcv_val,
                        _live_trading_val,
                        _dry_run_val,
                        _force_trade_val,
                        _force_trade_mode_val,
                    )
                    _live_authorized = _is_live_mode(_runtime_mode_cycle)
                    if not _live_authorized:
                        logger.critical(
                            "⚠️  OPERATOR ACTION REQUIRED: "
                            "LIVE_CAPITAL_VERIFIED/LIVE_TRADING not set to 'true' "
                            "(LIVE_CAPITAL_VERIFIED=%r LIVE_TRADING=%r). "
                            "Trading is permanently blocked until this env var is set. "
                            "Add 'LIVE_CAPITAL_VERIFIED=true' to your environment / Railway "
                            "variables and redeploy.",
                            _lcv_val,
                            _live_trading_val,
                        )

                # Shared-cycle snapshot is captured before activation attempts.
                _rate_limited_critical(
                    "core_loop_available_capital",
                    "scheduler",
                    60.0,
                    "💰 AVAILABLE CAPITAL: %.2f",
                    _cycle_balance,
                )

                # Trigger live-state activation checks using this cycle's frozen
                # capital snapshot before any strategy execution starts.
                _supervisor_step_state_machine()

                # ── FORCE_TRADE hard-activation safety net ────────────────────
                # After _supervisor_step_state_machine() runs, check if the FSM
                # is still not LIVE_ACTIVE despite FORCE_TRADE=true.  If so,
                # call _force_live_active_transition() directly as a last resort.
                # This catches the case where the supervisor's commit_activation()
                # call failed (e.g. startup coordinator proof not yet passed) but
                # FORCE_TRADE + LIVE_CAPITAL_VERIFIED are both set — the operator
                # has explicitly authorized live trading and the FSM must comply.
                _force_loop_bypass = (
                    _env_truthy("FORCE_TRADE")
                    or _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
                )
                _live_verified_loop_now = _is_live_mode(resolve_runtime_mode_safe(logger))
                if (
                    _force_loop_bypass
                    and _live_verified_loop_now
                    and _sm_loop is not None
                    and _SM_AVAILABLE
                ):
                    try:
                        _fsm_state_now = _sm_loop.get_current_state()
                        if _fsm_state_now != _TradingState.LIVE_ACTIVE:
                            logger.warning(
                                "⚡ [FORCE_TRADE] FSM still %s after supervisor step — "
                                "calling _force_live_active_transition() to unblock order submission. "
                                "LIVE_CAPITAL_VERIFIED=true + FORCE_TRADE=true. cycle=%d",
                                _fsm_state_now.value,
                                cycle,
                            )
                            if hasattr(_sm_loop, "_force_live_active_transition"):
                                _flt_ok = _sm_loop._force_live_active_transition(
                                    f"run_trading_loop FORCE_TRADE safety-net cycle={cycle}"
                                )
                                if _flt_ok:
                                    logger.critical(
                                        "⚡ [FORCE_TRADE] _force_live_active_transition SUCCESS — "
                                        "FSM is now LIVE_ACTIVE. Orders will be submitted. cycle=%d",
                                        cycle,
                                    )
                    except Exception as _flt_err:
                        logger.warning(
                            "[FORCE_TRADE] loop-level _force_live_active_transition failed: %s",
                            _flt_err,
                        )
                # ── End FORCE_TRADE hard-activation safety net ────────────────

                # ── Explicit commit_activation gate ───────────────────────────
                # When the bot is in LIVE_PENDING_CONFIRMATION and the authority
                # heartbeat is confirmed active, call commit_activation() directly
                # so the FSM can transition to LIVE_ACTIVE as soon as all gates
                # converge.  This is a belt-and-suspenders call that runs after
                # _supervisor_step_state_machine() to ensure activation is never
                # silently skipped due to a missed condition in the supervisor path.
                #
                # Conditions checked before calling:
                #   1. State machine is available and in LIVE_PENDING_CONFIRMATION
                #   2. Authority heartbeat is active (NIJA_WRITER_HEARTBEAT_ACTIVE=1)
                #   3. Activation has not already been committed
                try:
                    if (
                        _SM_AVAILABLE
                        and _get_state_machine is not None
                        and _sm_loop is not None
                    ):
                        _pending_state = _sm_loop.get_current_state()
                        _already_committed = bool(_sm_loop.get_activation_committed())
                        _hb_active = os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE", "0").strip() == "1"

                        if (
                            _pending_state == _TradingState.LIVE_PENDING_CONFIRMATION
                            and not _already_committed
                            and _hb_active
                        ):
                            logger.critical(
                                "🔑 COMMIT_ACTIVATION: state=LIVE_PENDING_CONFIRMATION "
                                "heartbeat=OK committed=False — calling commit_activation() "
                                "cycle=%d balance=%.2f",
                                cycle,
                                float(_cycle_balance or 0.0),
                            )
                            try:
                                _direct_committed = bool(
                                    _sm_loop.commit_activation(
                                        cycle_capital=_current_cycle_capital
                                    )
                                )
                                if _direct_committed:
                                    logger.critical(
                                        "✅ COMMIT_ACTIVATION SUCCESS: transitioned to LIVE_ACTIVE "
                                        "cycle=%d",
                                        cycle,
                                    )
                                else:
                                    logger.critical(
                                        "⏳ COMMIT_ACTIVATION PENDING: gates not yet converged "
                                        "cycle=%d state=%s",
                                        cycle,
                                        _sm_loop.get_current_state().value,
                                    )
                            except Exception as _direct_commit_err:
                                logger.warning(
                                    "commit_activation direct call failed: %s",
                                    _direct_commit_err,
                                )
                except Exception as _commit_gate_err:
                    logger.debug("commit_activation gate check failed: %s", _commit_gate_err)
                # ── End explicit commit_activation gate ───────────────────────

                # Single-line blocked diagnostic so operators can immediately
                # see why the loop is monitoring but not fully executing.
                try:
                    if _sm_loop is not None:
                        _state_now = _sm_loop.get_current_state()
                        _committed = bool(_sm_loop.get_activation_committed())
                        _can_dispatch = bool(_sm_loop.can_dispatch_trades())
                        _first_snap = bool(_sm_loop.get_first_snap_accepted())
                        _runtime_mode_cycle = resolve_runtime_mode_safe(logger)
                        _live_verified_now = _is_live_mode(_runtime_mode_cycle)
                        _min_balance = float(os.getenv("MINIMUM_TRADING_BALANCE", "50.0") or 50.0)  # $50 minimum for HF scalp mode (Apr 2026)
                        _balance_ok = float(_cycle_balance or 0.0) >= _min_balance

                        if (not _committed) or (not _can_dispatch):
                            _reasons = []
                            if not _live_verified_now:
                                _reasons.append("LIVE_CAPITAL_VERIFIED=false")
                            if not _first_snap:
                                _reasons.append("first_snap_accepted=false")
                            if not _balance_ok:
                                _reasons.append(f"capital_below_min(${float(_cycle_balance or 0.0):.2f}<{_min_balance:.2f})")
                            if _state_now != _TradingState.LIVE_ACTIVE:
                                _reasons.append(f"state={_state_now.value}")

                            logger.critical(
                                "⛔ EXECUTION BLOCKED | committed=%s dispatch=%s live=%s reasons=%s",
                                _committed,
                                _can_dispatch,
                                _live_verified_now,
                                ", ".join(_reasons) if _reasons else "activation gates not converged",
                            )
                except Exception as _block_diag_err:
                    logger.debug("execution-blocked diagnostic skipped: %s", _block_diag_err)

                # ── Capital pipeline diagnostic block ─────────────────────────
                try:
                    _diag_bm = getattr(strategy, "broker_manager", None)
                    _diag_mabm = None
                    try:
                        from bot.multi_account_broker_manager import (
                            multi_account_broker_manager as _diag_mabm,
                        )
                    except ImportError:
                        try:
                            from multi_account_broker_manager import (  # type: ignore[import]
                                multi_account_broker_manager as _diag_mabm,
                            )
                        except ImportError:
                            pass
                    _diag_ca = None
                    try:
                        from bot.capital_authority import get_capital_authority as _get_diag_ca
                        _diag_ca = _get_diag_ca()
                    except ImportError:
                        try:
                            from capital_authority import get_capital_authority as _get_diag_ca  # type: ignore[import]
                            _diag_ca = _get_diag_ca()
                        except ImportError:
                            pass
                    _diag_ac = None
                    try:
                        from bot.capital.active_capital import get_active_capital as _get_diag_ac
                        _diag_ac = _get_diag_ac()
                    except ImportError:
                        try:
                            from capital.active_capital import get_active_capital as _get_diag_ac  # type: ignore[import]
                            _diag_ac = _get_diag_ac()
                        except ImportError:
                            pass

                    logger.critical("=== CAPITAL PIPELINE DEBUG START ===")
                    logger.critical(
                        "BROKER BALANCES (cached/non-blocking): %s",
                        _cached_broker_balances_for_log(_diag_bm) if _diag_bm is not None else "broker_manager unavailable",
                    )
                    logger.critical(
                        "AGGREGATED STATE: %s",
                        _diag_mabm.get_state() if _diag_mabm is not None else "capital_aggregator unavailable",
                    )
                    logger.critical(
                        "FSM CAPITAL SNAPSHOT: %s",
                        _diag_ca.get_snapshot() if _diag_ca is not None else "capital_fsm unavailable",
                    )
                    logger.critical(
                        "ACTIVE CAPITAL: %s",
                        _diag_ac.get_available_balance() if _diag_ac is not None else "active_capital unavailable",
                    )
                    logger.critical("=== CAPITAL PIPELINE DEBUG END ===")
                except Exception as _diag_err:
                    logger.warning("[DIAG] capital pipeline probe failed: %s", _diag_err)
                # ── End capital pipeline diagnostic block ─────────────────────
                logger.debug(
                    "🔒 [%s] capital snapshot: hydrated=%s total=$%.2f "
                    "valid_brokers=%d brokers_ready=%s",
                    _current_cycle_id,
                    _current_cycle_capital.get("ca_is_hydrated"),
                    _cycle_balance,
                    _current_cycle_capital.get("ca_valid_brokers", 0),
                    _current_cycle_capital.get("mabm_brokers_ready"),
                )

                _rate_limited_critical(
                    "core_loop_heartbeat",
                    "scheduler",
                    30.0,
                    "🔥 TRADE LOOP HEARTBEAT: active=%s",
                    _trading_active,
                )
                _rate_limited_critical(
                    "core_loop_scan_tick",
                    "scheduler",
                    30.0,
                    "🟢 LIVE LOOP TICK — scanning markets",
                )
                if cycle == 1 or (cycle % _tick_log_every == 0):
                    logger.info("🔥 TRADE LOOP HEARTBEAT: active=%s cycle=%s", _trading_active, cycle)
                logger.info("[ScannerLoop] heartbeat")

                logger.debug("🟢 LIVE LOOP TICK — scanning markets")

                # ── Proactive broker liveness check before entering run_cycle ─────
                # If the strategy's broker is disconnected, attempt reconnect here
                # so run_cycle doesn't immediately skip and sleep for cycle_secs.
                # This keeps the bot trading 24/7 even after extended outages.
                _broker = getattr(strategy, 'broker', None)
                _broker_ok = _broker is not None and getattr(_broker, 'connected', False)
                if not _broker_ok:
                    _bm = getattr(strategy, 'broker_manager', None)
                    if _bm is not None:
                        # Try to find any already-connected broker first
                        _candidate = _bm.get_primary_broker()
                        if _candidate is not None and getattr(_candidate, 'connected', False):
                            strategy.broker = _candidate
                            _broker_ok = True
                        else:
                            # No connected broker — attempt reconnect via MABM state machine
                            # (routes through try_reconnect_platform_broker to keep _platform_state
                            # consistent and avoid bypassing the broker graph model).
                            _mabm = getattr(strategy, 'multi_account_manager', None)
                            for _bt, _b in list(getattr(_bm, 'brokers', {}).items()):
                                if _b is None:
                                    continue
                                try:
                                    # Prefer MABM reconnect path for platform brokers
                                    if _mabm is not None and hasattr(_mabm, 'try_reconnect_platform_broker'):
                                        _ok = _mabm.try_reconnect_platform_broker(_bt)
                                    else:
                                        _b.connect()
                                        _ok = getattr(_b, 'connected', False)
                                    if _ok:
                                        strategy.broker = _b
                                        _bm.active_broker = _b
                                        if (hasattr(strategy, 'apex') and strategy.apex
                                                and hasattr(strategy.apex, 'update_broker_client')):
                                            strategy.apex.update_broker_client(_b)
                                        logger.info(
                                            "✅ Loop reconnected broker: %s",
                                            getattr(_bt, 'value', str(_bt)).upper(),
                                        )
                                        _broker_ok = True
                                        break
                                except Exception as _lrc_err:
                                    logger.warning(
                                        "⚠️ Loop reconnect failed for %s: %s",
                                        getattr(_bt, 'value', str(_bt)).upper(), _lrc_err,
                                    )

                if not _broker_ok:
                    _skipped_cycles += 1
                    _sleep_s = _watchdog_backoff_delay(
                        cycle_secs,
                        _skipped_cycles - 1,
                        _watchdog_backoff_enabled,
                        _watchdog_backoff_max_multiplier,
                    )
                    if _skipped_cycles == 1 or _skipped_cycles % _MAX_SKIP_LOG_INTERVAL == 0:
                        logger.warning(
                            "⏸️  Trading paused — no broker connected "
                            "(skipped_cycles=%d, downtime≈%ds). "
                            "Retrying in %.0fs …",
                            _skipped_cycles,
                            _skipped_cycles * cycle_secs,
                            _sleep_s,
                        )
                    time.sleep(_sleep_s)
                    logger.debug("🚧 LOOP BLOCKED PATH REACHED — no broker connected, skipping cycle")
                    continue

                # Broker is alive — run the full trading cycle
                _skipped_cycles = 0

                # ── EXEC TEST MODE ────────────────────────────────────────────────
                # If NIJA_EXEC_TEST_MODE is enabled, fire a single probe order to
                # validate the complete execution stack, then disable itself so the
                # bot continues normal operation on the next cycle.
                # Uses a module-level flag (_exec_test_fired) so the probe only
                # runs once per process lifetime regardless of whether the env var
                # is still set to "true" after the first probe.
                global _exec_test_fired
                if (not _exec_test_fired
                        and os.getenv("NIJA_EXEC_TEST_MODE", "false").lower() == "true"):
                    _on_startup_only = os.getenv("NIJA_EXEC_TEST_ON_STARTUP", "true").lower() == "true"
                    if not _on_startup_only or cycle == 1:
                        logger.info("🧪 EXEC TEST MODE ACTIVE — forcing single execution probe")
                        _probe_result = _exec_test_probe(strategy)
                        logger.info("🧪 EXEC TEST RESULT → %s", _probe_result)
                        _exec_test_fired = True
                        logger.debug("🚧 LOOP BLOCKED PATH REACHED — exec test mode fired, skipping normal cycle")
                        continue

                # Log available capital so operators can spot a $0.00 balance
                # that would silently block all position sizing and entries.
                _cycle_cap = (
                    _current_cycle_capital.get("ca_total_capital", 0.0)
                    if _current_cycle_capital
                    else 0.0
                )

                # Hard gate: never execute strategy cycles until runtime authority
                # has fully converged to dispatch-enabled live execution.
                if _sm_loop is not None:
                    try:
                        _state_gate = _sm_loop.get_current_state()
                        _committed_gate = bool(_sm_loop.get_activation_committed())
                        _dispatch_gate = bool(_sm_loop.can_dispatch_trades())
                        _live_gate = _state_gate == _TradingState.LIVE_ACTIVE
                        _dispatch_reason = ""
                        _runtime_authority = ""
                        try:
                            _auth_snapshot = _sm_loop.get_execution_authority_snapshot()
                            _dispatch_reason = str(
                                _auth_snapshot.get("runtime_authority_reason", "")
                                or _auth_snapshot.get("safety_reason", "")
                                or ""
                            )
                            _runtime_authority = str(
                                _auth_snapshot.get("runtime_authority_state", "") or ""
                            )
                        except Exception:
                            _dispatch_reason = ""
                            _runtime_authority = ""
                    except Exception as _exec_gate_err:
                        logger.warning("Execution gate probe failed; skipping strategy cycle: %s", _exec_gate_err)
                        time.sleep(cycle_secs)
                        continue

                    # FORCE_TRADE / NIJA_FORCE_ACTIVATION bypass: when an operator override
                    # flag is active, allow the strategy cycle to run even before the FSM
                    # has fully converged to LIVE_ACTIVE.  The downstream broker adapter
                    # still enforces can_execute() (which requires LIVE_ACTIVE), so no
                    # orders are placed until activation completes — but market scanning
                    # and signal generation proceed immediately.  This unblocks the pipeline
                    # in deployments where Redis or capital-authority hydration is delayed.
                    # NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK is also included here because
                    # it signals that Redis is not available and the FSM should not be
                    # blocked waiting for distributed lock infrastructure.
                    _force_cycle_bypass = (
                        _env_truthy("FORCE_TRADE")
                        or _env_truthy("NIJA_FORCE_ACTIVATION")
                        or _env_truthy("FORCE_TRADE_MODE")
                        or _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
                    )

                    if (not _committed_gate) or (not _dispatch_gate) or (not _live_gate):
                        _skip_signature = (
                            bool(_committed_gate),
                            bool(_dispatch_gate),
                            getattr(_state_gate, "value", str(_state_gate)),
                        )
                        _activation_retry_sleep_s = min(
                            float(cycle_secs),
                            max(1.0, float(os.getenv("NIJA_ACTIVATION_RETRY_SLEEP_S", "10") or 10.0)),
                        )
                        if _force_cycle_bypass:
                            # Operator override active — run the strategy cycle immediately
                            # even though the FSM has not reached LIVE_ACTIVE yet.  Log once
                            # per signature change so the operator can see the bypass is active.
                            if _skip_signature != _last_cycle_skip_signature:
                                logger.warning(
                                    "⚡ FORCE_TRADE bypass: running strategy cycle despite activation gate "
                                    "| committed=%s dispatch=%s state=%s — orders will be blocked by "
                                    "broker can_execute() until FSM reaches LIVE_ACTIVE",
                                    _committed_gate,
                                    _dispatch_gate,
                                    getattr(_state_gate, "value", str(_state_gate)),
                                )
                                _last_cycle_skip_signature = _skip_signature
                            # Fall through to run_cycle() below.
                        else:
                            if _skip_signature != _last_cycle_skip_signature:
                                logger.warning(
                                    "⏸️ STRATEGY CYCLE SKIPPED | committed=%s dispatch=%s state=%s "
                                    "runtime_authority=%s reason=%s retry_in=%.0fs",
                                    _committed_gate,
                                    _dispatch_gate,
                                    getattr(_state_gate, "value", str(_state_gate)),
                                    _runtime_authority or "unknown",
                                    _dispatch_reason or "not_reported",
                                    _activation_retry_sleep_s,
                                )
                                _last_cycle_skip_signature = _skip_signature
                            else:
                                _rate_limited_critical(
                                    "core_loop_activation_skip",
                                    "dispatch_gate",
                                    60.0,
                                    "⏸️ STRATEGY CYCLE STILL WAITING | state=%s dispatch=%s reason=%s retry_in=%.0fs",
                                    getattr(_state_gate, "value", str(_state_gate)),
                                    _dispatch_gate,
                                    _dispatch_reason or "not_reported",
                                    _activation_retry_sleep_s,
                                )
                            time.sleep(_activation_retry_sleep_s)
                            continue
                    else:
                        _last_cycle_skip_signature = None

                _rate_limited_critical(
                    "core_loop_capital_check",
                    "scheduler",
                    60.0,
                    "💰 CAPITAL CHECK: $%.2f",
                    _cycle_cap,
                )
                _rate_limited_critical(
                    "core_loop_run_cycle",
                    "scheduler",
                    60.0,
                    "🚀 RUNNING TRADE CYCLE",
                )
                logger.info("💰 CAPITAL CHECK: $%.2f", _cycle_cap)
                logger.info("🚀 RUNNING TRADE CYCLE")
                logger.critical(
                    "🚀 [CYCLE_INVOKE] strategy.run_cycle() CALLED | "
                    "cycle=%d capital=$%.2f cycle_id=%s",
                    cycle, _cycle_cap, _current_cycle_id,
                )

                # ── Fix 3: Pre-cycle wiring + symbol pre-warm ──────────────────
                # Ensure strategy components are fully wired BEFORE entering
                # run_cycle() so the cycle spends its time scanning, not
                # re-initializing.  On cycle 1, do an eager symbol pre-load.
                _pre_apex = getattr(strategy, "apex", None)
                _pre_core = getattr(strategy, "nija_core_loop", None)
                if _pre_apex is not None and _pre_core is None:
                    try:
                        if callable(getattr(strategy, "_ensure_nija_wiring", None)):
                            strategy._ensure_nija_wiring()
                            _pre_core = getattr(strategy, "nija_core_loop", None)
                    except Exception as _pre_wire_err:
                        logger.warning(
                            "[PRE_CYCLE] _ensure_nija_wiring failed: %s", _pre_wire_err
                        )
                if cycle == 1:
                    _pre_syms = getattr(strategy, "symbols", None) or []
                    if not _pre_syms:
                        try:
                            if callable(getattr(strategy, "_maybe_refresh_symbols", None)):
                                strategy._maybe_refresh_symbols(force=True)
                                _pre_syms = getattr(strategy, "symbols", None) or []
                                logger.critical(
                                    "🔧 [PRE_CYCLE] Symbol universe pre-loaded: %d symbols",
                                    len(_pre_syms),
                                )
                        except Exception as _pre_sym_err:
                            logger.warning(
                                "[PRE_CYCLE] Symbol pre-load failed: %s", _pre_sym_err
                            )
                # ── End Fix 3 ─────────────────────────────────────────────────

                # ── Fix 4: Backref assertions ──────────────────────────────────
                # Block the cycle with a clear reason if required strategy
                # components are missing, instead of entering a silent no-op.
                _pre_apex = getattr(strategy, "apex", None)
                _pre_core = getattr(strategy, "nija_core_loop", None)
                _pre_broker = getattr(strategy, "broker", None)
                _backref_ok = True

                if _pre_apex is None:
                    _backref_ok = False
                    logger.critical(
                        "⛔ [RUN_CYCLE_BLOCKED_MISSING_REF] strategy.apex is None — "
                        "cycle=%d skipped. Check NIJAApexStrategyV71 init logs.",
                        cycle,
                    )
                    print(
                        f"[NIJA-PRINT] RUN_CYCLE_BLOCKED_MISSING_REF "
                        f"reason=apex_is_None cycle={cycle}",
                        flush=True,
                    )
                else:
                    if _pre_core is None:
                        logger.critical(
                            "⚠️ [PRE_CYCLE] strategy.nija_core_loop is None — "
                            "will fall back to legacy analyze_market path. cycle=%d",
                            cycle,
                        )
                    if _pre_broker is None:
                        logger.critical(
                            "⚠️ [PRE_CYCLE] strategy.broker is None — "
                            "order submission will fail. cycle=%d",
                            cycle,
                        )
                    # Verify phase3 scan is callable on core loop or strategy
                    _phase3_target = _pre_core if _pre_core is not None else strategy
                    if not callable(
                        getattr(_phase3_target, "_phase3_scan_and_enter", None)
                    ):
                        logger.warning(
                            "[PRE_CYCLE] _phase3_scan_and_enter not callable on %s — "
                            "cycle=%d",
                            type(_phase3_target).__name__,
                            cycle,
                        )

                if not _backref_ok:
                    _missing_ref_retry_s = float(
                        os.getenv("NIJA_MISSING_REF_RETRY_S", "15") or 15
                    )
                    time.sleep(_missing_ref_retry_s)
                    continue
                # ── End Fix 4 ─────────────────────────────────────────────────

                _cycle_start_ts = time.time()
                _next_sleep_s = float(cycle_secs)
                update_runtime_correlation(cycle_id=_current_cycle_id)

                # ── Fix 6: Hard stall watchdog around run_cycle() ──────────────
                # Fire RUN_CYCLE_STALLED if run_cycle() does not return (or does
                # not emit RUN_CYCLE_PHASE3_START) within the configured timeout.
                # The timer is cancelled immediately when run_cycle() returns.
                _run_cycle_stall_s = float(
                    os.getenv("NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S", "30") or 30
                )
                _stall_fired = [False]

                def _stall_watchdog_fn(
                    _cy=cycle,
                    _cid=_current_cycle_id,
                    _tout=_run_cycle_stall_s,
                ):
                    _stall_fired[0] = True
                    logger.critical(
                        "⛔ [RUN_CYCLE_STALLED] strategy.run_cycle() still running "
                        "after %.0fs — cycle=%d cycle_id=%s | "
                        "strategy may be stuck before PHASE3_START",
                        _tout,
                        _cy,
                        _cid,
                    )
                    print(
                        f"[NIJA-PRINT] RUN_CYCLE_STALLED "
                        f"stage=pre_phase3_or_unknown "
                        f"elapsed={_tout:.0f}s cycle={_cy}",
                        flush=True,
                    )

                _stall_timer = threading.Timer(_run_cycle_stall_s, _stall_watchdog_fn)
                _stall_timer.daemon = True
                _stall_timer.start()
                # ── End Fix 6 setup ───────────────────────────────────────────

                try:
                    _strategy_next_interval = strategy.run_cycle()
                    _stall_timer.cancel()
                    logger.critical(
                        "✅ [CYCLE_INVOKE] strategy.run_cycle() RETURNED | "
                        "cycle=%d next_interval=%s",
                        cycle, _strategy_next_interval,
                    )
                    logger.info(
                        "✅ [run_trading_loop] strategy.run_cycle() RETURNED | "
                        "cycle=%d next_interval=%s",
                        cycle,
                        _strategy_next_interval,
                    )
                    if isinstance(_strategy_next_interval, (int, float)):
                        _next_sleep_s = max(1.0, float(_strategy_next_interval))
                except Exception as _run_cycle_err:
                    _stall_timer.cancel()
                    logger.critical(
                        "❌ [CYCLE_INVOKE] strategy.run_cycle() RAISED EXCEPTION | "
                        "cycle=%d error=%s",
                        cycle, _run_cycle_err,
                        exc_info=True,
                    )
                    raise
                finally:
                    _stall_timer.cancel()
                    clear_runtime_correlation()
                _cycle_elapsed = time.time() - _cycle_start_ts
                # Retrieve symbol count from strategy for heartbeat diagnostics
                _hb_symbols = 0
                try:
                    _hb_symbols = len(getattr(strategy, "symbols", None) or [])
                except Exception:
                    _hb_symbols = 0
                logger.info(
                    "STRATEGY HEARTBEAT | cycle=%s symbols=%s runtime=%.1fs next_sleep=%.0fs",
                    cycle,
                    _hb_symbols,
                    _cycle_elapsed,
                    _next_sleep_s,
                )
                time.sleep(_next_sleep_s)

            except Exception as _err:
                _activation_retry_count += 1
                logger.critical(
                    "❌ LOOP ERROR: %s",
                    _err,
                    exc_info=True,
                )
                _error_sleep_s = _watchdog_backoff_delay(
                    15.0,
                    _activation_retry_count - 1,
                    _watchdog_backoff_enabled,
                    _watchdog_backoff_max_multiplier,
                )
                time.sleep(_error_sleep_s)

    except Exception as e:
        logger.exception("💥 FATAL ERROR IN TRADING LOOP: %s", e)
        raise
