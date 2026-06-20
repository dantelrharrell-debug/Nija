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
# Start-signal gate — defined here (before any function that references it)
# so the name is always in module scope when _supervisor_step_state_machine()
# runs, regardless of call order.
# Emitted exactly once by bot.py when BootstrapFSM reaches RUNNING_SUPERVISED.
# ---------------------------------------------------------------------------
TRADING_ENGINE_READY = threading.Event()
# ── FORCE_TRADE: pre-set the start gate so run_trading_loop() never waits ────
if os.environ.get("FORCE_TRADE", "").strip().lower() in ("1", "true", "yes", "on", "enabled") \
        or os.environ.get("FORCE_TRADE_MODE", "").strip().lower() in ("1", "true", "yes", "on", "enabled"):
    logger.warning(
        "⚡ FORCE_TRADE: TRADING_ENGINE_READY pre-set at module load — "
        "trading loop will not wait for bootstrap FSM"
    )
    TRADING_ENGINE_READY.set()


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
        _force_activation_sv = (
            _env_truthy("FORCE_TRADE")
            or _env_truthy("NIJA_FORCE_ACTIVATION")
            or _env_truthy("FORCE_TRADE_MODE")
        )
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
        # Canonical balance source-of-truth:
        # - Once CA is hydrated, always use cycle-captured CA capital
        #   (including legitimate 0.0) so all gates/signals share one value.
        # - Before hydration, fall back to caller-supplied balance.
        _canonical_balance = _ca_total_capital if _ca_hydrated else float(balance)
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
        logger.info(
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
        if not user_mode:
            available_slots = max(0, self.max_positions - effective_open)
            if available_slots > 0:
                logger.info(
                    "🔍 Scanning markets — %d symbols | slots=%d open=%d",
                    len(symbols), available_slots, effective_open,
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
                logger.info(
                    "📊 [GATE_REJECTIONS] cycle=%d | "
                    "confidence_gate_rejected=%d | adx_gate_rejected=%d | "
                    "volume_gate_rejected=%d | momentum_filter_rejected=%d | "
                    "ai_gate_rejected=%d | notional_gate_rejected=%d | "
                    "capital_gate_rejected=%d | risk_gate_rejected=%d | "
                    "market_filter_rejected=%d | data_insufficient=%d",
                    self._total_cycles,
                    _gate_rejections.get("confidence_gate_rejected", 0),
                    _gate_rejections.get("adx_gate_rejected", 0),
                    _gate_rejections.get("volume_gate_rejected", 0),
                    _gate_rejections.get("momentum_filter_rejected", 0),
                    _gate_rejections.get("ai_gate_rejected", 0),
                    _gate_rejections.get("notional_gate_rejected", 0),
                    _gate_rejections.get("capital_gate_rejected", 0),
                    _gate_rejections.get("risk_gate_rejected", 0),
                    _gate_rejections.get("market_filter_rejected", 0),
                    _gate_rejections.get("data_insufficient", 0),
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
            logger.info("🔒 Core loop: entries blocked (user_mode)")
            # ── Entry-to-Order Trace: pre-scan veto ──────────────────────
            # user_mode can be True for two distinct reasons:
            #   1. Safety gate fired (can_enter=False) → report the specific safety reason.
            #   2. Caller explicitly passed user_mode=True (can_enter still True) → report "user_mode".
            # These are mutually exclusive: the safety gate sets user_mode=True only when
            # can_enter is False, so the inner check is not redundant.
            _prescan_reason = safety_reason if not can_enter else "user_mode"
            emit_cycle_trace(
                CycleOutcome.ENTRY_VETOED,
                reason=_prescan_reason,
            )
            self._n_vetoed += 1
            self._record_veto(_prescan_reason)

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
            print(f"⏱ Trade allowed: {can_trade}")
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
        funnel_traces: Dict[str, Dict[str, Tuple[str, str]]] = {}
        for _symbol_idx, symbol in enumerate(symbols):
            _funnel = funnel_traces.setdefault(symbol, {})
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
                df = self._fetch_df(broker, symbol)
                if df is None or len(df) < 100:
                    if _sdd is not None:
                        _sdd.record_skip(symbol, "data_insufficient")
                    _funnel["market_data"] = ("FAIL", "DATA_INSUFFICIENT")
                    _gate_rejections["data_insufficient"] += 1
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
                    continue

                # Determine trend from apex market filter
                try:
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
                        continue
                    _market_filter_passes += 1
                    _funnel["regime"] = ("PASS", "")
                except Exception:
                    trend = "uptrend"
                    _funnel["regime"] = ("PASS", "MARKET_FILTER_FALLBACK")
                    _market_filter_checks += 1
                    _market_filter_passes += 1

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
                    logger.info("🔎 Evaluating market — %s (%s)", symbol, side)
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
                        _funnel["signal"] = ("PASS", "")
                        logger.info(
                            "✅ Signal passed — %s score=%.1f threshold=%.1f",
                            symbol, sig.composite_score, sig.threshold_used,
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

        logger.info("[Scanner] candidates_found=%d", len(candidates))

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
        if not candidates:
            logger.info(
                "🔍 Core loop Phase 3: scored=%d symbols, no candidates above floor=%.0f",
                scored, _effective_hard_floor,
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

        # ── Execute selected entries ──────────────────────────────────────
        entries = 0
        for sig in selected:
            if entries >= MAX_ENTRIES_PER_CYCLE:
                break
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
                        _funnel["ai_gate"] = ("PASS", "")
                    except Exception as _tpe_err:
                        logger.debug(
                            "TradePermissionEngine error for %s (non-fatal): %s",
                            sig.symbol, _tpe_err,
                        )

                # Re-run full apex.analyze_market (handles SL/TP/sizing etc.)
                analysis = self.apex.analyze_market(df, sig.symbol, snapshot.balance)
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

                if action not in ("enter_long", "enter_short"):
                    blocked += 1
                    _funnel["profitability"] = ("FAIL", analysis.get("reason", "NO_PROFITABLE_ACTION"))
                    continue
                _funnel["profitability"] = ("PASS", "")

                # Apply AI engine position multiplier to analysis size hint
                if "position_size" in analysis and sig.position_multiplier != 1.0:
                    original = analysis["position_size"]
                    analysis["position_size"] = original * sig.position_multiplier
                    logger.info(
                        "   🤖 AI multiplier ×%.2f applied to %s size: $%.2f → $%.2f",
                        sig.position_multiplier, sig.symbol,
                        original, analysis["position_size"],
                    )

                success = self.apex.execute_action(analysis, sig.symbol)
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
                logger.warning("Phase3 execute error for %s: %s", sig.symbol, exec_err)
                blocked += 1
                _funnel = funnel_traces.setdefault(sig.symbol, {})
                _funnel["profitability"] = ("FAIL", f"EXECUTION_EXCEPTION:{exec_err}")
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
        take_profit_pct = (0.60, 1.00, 1.60)
        trailing_stop_pct = 0.75
        try:
            from bot.competitive_profitability_policy import get_competitive_profitability_policy

            competitive_profile = get_competitive_profitability_policy().profile_entry(
                df=df,
                side="short" if action == "enter_short" else "long",
            )
            if not competitive_profile.liquidity_ok:
                raise ValueError(
                    "competitive profitability policy blocked illiquid fallback entry: "
                    f"{competitive_profile.liquidity_reason}"
                )
            risk_fraction = competitive_profile.risk_fraction
            stop_loss_pct = min(float(competitive_profile.stop_loss_pct), 3.0)
            raw_tp = tuple(float(pct) for pct in competitive_profile.take_profit_pct)
            tp1 = max(raw_tp[0] if len(raw_tp) > 0 else 0.0, 0.85)
            tp2 = max(raw_tp[1] if len(raw_tp) > 1 else tp1, tp1 + 0.20)
            tp3 = max(raw_tp[2] if len(raw_tp) > 2 else tp2, tp2 + 0.25)
            take_profit_pct = (tp1, tp2, tp3)
            stop_loss_pct = competitive_profile.stop_loss_pct
            take_profit_pct = competitive_profile.take_profit_pct
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
        size_cap = max(min(balance * 0.05, balance), 0.0)
        position_size = min(max(min_notional, size_cap), balance)

        if action == "enter_short":
            stop_loss = price * 1.012
            take_profit = [price * 0.994, price * 0.990, price * 0.984]
        else:
            stop_loss = price * 0.988
            take_profit = [price * 1.006, price * 1.010, price * 1.016]

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
            "reason": reason,
            "fallback_entry": True,
            "forced_fallback": True,
        }

    def _fetch_df(self, broker: Any, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV DataFrame from the broker.

        When ``broker`` is None the method falls back to ``apex.broker_client``
        so per-symbol fetches never silently return None when the caller omits
        the broker argument.

        Returns ``None`` when the broker call fails or returns no data.
        """
        try:
            if broker is None:
                broker = getattr(self.apex, "broker_client", None)
            if broker is None:
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
            return None
        except Exception as exc:
            logger.debug("_fetch_df error for %s: %s", symbol, exc)
            return None

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
# here — the earlier definition (including FORCE_TRADE pre-set logic) is the
# canonical one.


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

    _runtime_mode = resolve_runtime_mode_safe(logger)
    _live_verified = _is_live_mode(_runtime_mode)
    if _live_verified and not TRADING_ENGINE_READY.is_set():
        logger.critical(
            "LIVE_CAPITAL_VERIFIED=true detected — bypassing passive activation wait gate"
        )
        TRADING_ENGINE_READY.set()

    logger.critical("🧵 WAITING FOR START SIGNAL")
    while not TRADING_ENGINE_READY.is_set():
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
        if not TRADING_ENGINE_READY.wait(timeout=30):
            logger.critical("TIMEOUT_WAITING_FOR_TRADING_ENGINE_READY")
            try:
                from bot.bootstrap_utils import dump_startup_state
            except ImportError:
                try:
                    from bootstrap_utils import dump_startup_state  # type: ignore[import]
                except ImportError:
                    dump_startup_state = None  # type: ignore[assignment]
            if dump_startup_state is not None:
                dump_startup_state("trading_engine_ready_wait")
    logger.critical("🟢 START SIGNAL RECEIVED — ENTERING LIVE LOOP")
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
                    with _loop_guard:
                        _loop_running = False
                    return
            else:
                logger.critical(
                    "🚫 execution_authority not set and BootstrapFSM has no _execution_authority "
                    "attribute — trading loop cannot start safely."
                )
                with _loop_guard:
                    _loop_running = False
                return


    # Supervisor-mode hard gate: only block execution when supervisor mode is
    # enabled AND live trading is not active.
    _supervisor_mode = os.getenv("SUPERVISOR_MODE", "false").lower() in (
        "true", "1", "yes", "enabled"
    )
    if _supervisor_mode:
        _live_active_now = False
        try:
            if _SM_AVAILABLE and _get_state_machine is not None:
                _live_active_now = bool(_get_state_machine().is_live_trading_active())
        except Exception as _sm_probe_err:
            logger.debug("Supervisor mode live-state probe failed: %s", _sm_probe_err)

        if not _live_active_now:
            logger.critical(
                "SUPERVISOR_MODE enabled while live mode is inactive — "
                "blocking run_trading_loop startup"
            )
            return

    # ── Strategy existence guard ────────────────────────────────────────────
    # Must be checked BEFORE acquiring _loop_guard / setting _loop_running so
    # that a None strategy never permanently blocks future valid start attempts.
    # A None strategy here means the caller violated the contract (strategy must
    # exist before TradingCoreLoop starts) — refuse to proceed.
    if strategy is None:
        logger.critical(
            "🚫 run_trading_loop called with strategy=None — "
            "refusing to start; _loop_running NOT set so the loop can be "
            "started correctly once strategy is available."
        )
        return

    try:
        logger.critical(f"LOOP START CHECK — _loop_running={_loop_running}")
        with _loop_guard:
            if _loop_running:
                logger.critical("🚧 LOOP BLOCKED PATH REACHED — duplicate start guard triggered")
                logger.info("🟡 Core trading loop already active — skipping duplicate start")
                return
            _loop_running = True

        logger.info("🟢 Trading loop alive (INITIAL START)")

        # ── Capital Hydration Barrier (FIX 1) ─────────────────────────────────
        # Block until CapitalAuthority has received at least one broker snapshot.
        # This prevents the race where the strategy loop evaluates capital before
        # any broker balance has been fetched (returning $0.00), which caused the
        # "Balance $0.00 below minimum / AUTO mode fallback" log pattern.
        # Timeout: 30 s (configurable via NIJA_HYDRATION_BARRIER_TIMEOUT).
        _hydration_timeout = float(
            os.getenv("NIJA_HYDRATION_BARRIER_TIMEOUT", "30")
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
                logger.critical(
                    "🚨 [HYDRATION_BARRIER] CAPITAL INTEGRITY ERROR: %s — "
                    "trading loop aborted. Bot will not trade until capital is hydrated.",
                    _hb_err,
                )
                with _loop_guard:
                    _loop_running = False
                return
        except (ImportError, Exception) as _hb_exc:
            logger.warning(
                "⚠️ [HYDRATION_BARRIER] Could not enforce hydration barrier (%s) — "
                "proceeding without guarantee. Check capital_authority module.",
                _hb_exc,
            )
        # ── End Capital Hydration Barrier ──────────────────────────────────────

        # ── CSM v2 Ready Barrier ───────────────────────────────────────────────
        # Block until CapitalCSMv2 transitions to READY state.  This is the
        # second hard barrier (after hydration) and ensures that all readiness
        # criteria (LIVE_CAPITAL_VERIFIED, positive balance, confidence score,
        # fresh snapshot) are satisfied before the first strategy cycle runs.
        _csm_timeout = float(os.getenv("NIJA_CSM_READY_TIMEOUT", "30"))
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
            logger.critical("CSM PRE-WAIT STATE: %s", _csm.state)
            _csm_ready = _csm.wait_for_ready(timeout=_csm_timeout)
            logger.critical("CSM POST-WAIT STATE: %s", _csm.state)
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
                        logger.critical(
                            "❌ CSM BLOCKED — TRADING LOOP ABORTED. reason=%s",
                            _csm.blocked_reason,
                        )
                        with _loop_guard:
                            _loop_running = False
                        raise _CsmIntegrityErr("CSM BLOCKED: " + _csm.blocked_reason)
                else:
                    # INITIALIZING after timeout — treat as DEGRADED, let loop proceed.
                    logger.critical(
                        "⚠️ CSM NOT READY (state=%s) — proceeding anyway after timeout",
                        _csm_state_now.value,
                    )
            else:
                logger.critical(
                    "✅ CAPITAL READY — STARTING TRADING LOOP"
                )
        except _CsmIntegrityErr as _csm_err:
            logger.critical(
                "🚨 [CSM-BARRIER] CAPITAL NOT READY: %s — "
                "trading loop aborted. Bot will not trade until CSM reaches READY state.",
                _csm_err,
            )
            with _loop_guard:
                _loop_running = False
            return
        except (ImportError, Exception) as _csm_exc:
            logger.warning(
                "⚠️ [CSM-BARRIER] Could not enforce CSM ready barrier (%s) — "
                "proceeding without guarantee. Check capital_csm_v2 module.",
                _csm_exc,
            )
        # ── End CSM v2 Ready Barrier ───────────────────────────────────────────

        # ── Trading Loop Entry Anchor (FIX 1) ─────────────────────────────────
        # Both hydration and CSM barriers have passed.  Arm the trading-active
        # flag HERE and verify it before entering the loop — this is the single
        # authoritative gate.  If the assert fires something above cleared the
        # flag unexpectedly; that is a logic bug that must be surfaced loudly.
        _trading_active = True
        if not _trading_active:
            logger.critical("💥 _trading_active failed to set — logic error, aborting")
            raise RuntimeError("_trading_active must be True before entering trading loop")
        logger.critical("🚀 ENTERING TRADING LOOP - FINAL GATE PASSED")
        print("🚀 ENTERING TRADING LOOP - FINAL GATE PASSED — all barriers cleared", flush=True)
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
                        with _loop_guard:
                            _loop_running = False
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
                    with _loop_guard:
                        _loop_running = False
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
                    if (
                        _live_verified_loop
                        and _current_state_loop == _TradingState.OFF
                        and not _live_now
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
                    _force_trade_val = os.getenv("FORCE_TRADE", "false").lower().strip()
                    _force_trade_mode_val = os.getenv("FORCE_TRADE_MODE", "false").lower().strip()
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
                    _force_cycle_bypass = (
                        _env_truthy("FORCE_TRADE")
                        or _env_truthy("NIJA_FORCE_ACTIVATION")
                        or _env_truthy("FORCE_TRADE_MODE")
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
                _cycle_start_ts = time.time()
                _next_sleep_s = float(cycle_secs)
                update_runtime_correlation(cycle_id=_current_cycle_id)
                try:
                    _strategy_next_interval = strategy.run_cycle()
                    if isinstance(_strategy_next_interval, (int, float)):
                        _next_sleep_s = max(1.0, float(_strategy_next_interval))
                finally:
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
