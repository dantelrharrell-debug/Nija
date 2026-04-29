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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.core_loop")


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
_current_cycle_capital: Dict[str, Any] = {}
_current_cycle_snapshot: Optional["CycleSnapshot"] = None


def get_current_cycle_snapshot() -> Optional["CycleSnapshot"]:
    """Return the frozen CycleSnapshot for the currently-executing cycle.

    Returns ``None`` when called outside of an active run_scan_phase call or
    when the snapshot has not yet been constructed (e.g. during
    _supervisor_step_state_machine which runs before run_scan_phase).

    External callers (CapitalAllocationBrain, MABM helpers) use this to avoid
    duplicate CA / broker reads within a single cycle.
    """
    return _current_cycle_snapshot


def _capture_cycle_capital_state() -> Dict[str, Any]:
    """Read CapitalAuthority + MABM broker state exactly ONCE.

    Called at the top of each cycle in run_trading_loop() BEFORE
    _supervisor_step_state_machine() so both the state-machine activation
    check and the subsequent strategy cycle see the same frozen capital view.

    Returns a plain dict with keys:
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
    """
    result: Dict[str, Any] = {
        "ca_is_hydrated": False,
        "ca_total_capital": 0.0,
        "ca_valid_brokers": 0,
        "mabm_brokers_ready": False,
        "is_post_hydration": False,
        "snapshot_source": "placeholder",
        "aggregation_normalized": True,  # default True (safe: don't block when unknown)
    }

    # ── CapitalAuthority state ────────────────────────────────────────────
    if _CA_LOOP_AVAILABLE and _get_ca is not None:
        try:
            _ca = _get_ca()
            result["ca_is_hydrated"] = bool(_ca.is_hydrated)
            result["ca_total_capital"] = float(getattr(_ca, "total_capital", 0.0) or 0.0)
        except Exception as _ce:
            logger.debug("_capture_cycle_capital_state: CA read failed: %s", _ce)

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
        # Approximate valid_brokers from platform_brokers if available
        _pb = getattr(_mabm_inst, "_platform_brokers", None) if _mabm_inst is not None else None
        if isinstance(_pb, dict):
            result["ca_valid_brokers"] = max(
                result["ca_valid_brokers"], len(_pb)
            )
        # Derive snapshot_source from the MABM's last cached refresh result.
        # "_capital_last_valid_brokers" is updated whenever refresh_capital_authority
        # returns data from a real exchange call.  "live_exchange" mirrors the value
        # MABM sets when at least one connected broker contributed a balance payload.
        _last_vb = int(getattr(_mabm_inst, "_capital_last_valid_brokers", 0) or 0) if _mabm_inst is not None else 0
        result["snapshot_source"] = "live_exchange" if _last_vb > 0 else "placeholder"
    except Exception as _me:
        logger.debug("_capture_cycle_capital_state: MABM read failed: %s", _me)

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
        "mabm_ready=%s | source=%s | aggregation_normalized=%s",
        result.get("ca_is_hydrated"),
        float(result.get("ca_total_capital", 0.0) or 0.0),
        result.get("ca_valid_brokers"),
        result.get("mabm_brokers_ready"),
        result.get("snapshot_source"),
        result.get("aggregation_normalized"),
    )

    return result


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

        _live_verified = os.getenv(
            "LIVE_CAPITAL_VERIFIED", "false"
        ).lower() in ("true", "1", "yes", "enabled")
        _min_balance = float(os.getenv("MINIMUM_TRADING_BALANCE", "1.0") or 1.0)
        _cycle_capital = _current_cycle_capital if isinstance(_current_cycle_capital, dict) else {}
        _balance = float(_cycle_capital.get("ca_total_capital", 0.0) or 0.0)
        _sufficient_balance = _balance >= _min_balance and _balance > 0.0

        logger.critical(
            "SUPERVISOR CYCLE CHECK | state=%s | start_signal=%s | live_verified=%s | balance=%.2f | min=%.2f",
            sm.get_current_state().value,
            TRADING_ENGINE_READY.is_set(),
            _live_verified,
            _balance,
            _min_balance,
        )

        # Missing trigger fix: the supervisor attempts activation every cycle
        # while in OFF, using the same frozen cycle capital snapshot.
        if _live_verified:
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
                        "supervisor arming: LIVE_CAPITAL_VERIFIED + sufficient balance",
                    )
                    logger.critical("🟡 SUPERVISOR ARMING: OFF -> LIVE_PENDING_CONFIRMATION")
                except Exception as _arm_err:
                    logger.warning("Supervisor arming fallback failed: %s", _arm_err)
        elif _balance > 0.0:
            logger.warning(
                "⚠️ Supervisor activation blocked: LIVE_CAPITAL_VERIFIED is false while balance is %.2f",
                _balance,
            )
    except Exception as _sm_err:
        logger.debug("supervisor state machine step failed: %s", _sm_err)

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
# Lowered 25.0 → 20.0 → 14.0 → 11.0 → 8.0 → 5.0 → 3.0 (confirmation-trade mode, Apr 2026).
# Override at runtime with NIJA_CORE_MIN_SCORE env var.
MIN_SCORE_HARD_FLOOR = float(os.environ.get("NIJA_CORE_MIN_SCORE", "3.0"))

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
    from profit_mode_controller import get_profit_mode_controller as _get_pmc  # type: ignore
    _PMC_AVAILABLE = True
except ImportError:
    try:
        from bot.profit_mode_controller import get_profit_mode_controller as _get_pmc  # type: ignore
        _PMC_AVAILABLE = True
    except ImportError:
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
        snapshot = CycleSnapshot(
            balance=balance,
            current_regime=getattr(self.apex, "current_regime", None),
            daily_pnl_usd=getattr(self.apex, "_daily_pnl_usd", 0.0),
            open_positions=open_positions_count,
            cycle_id=_cid,
            ca_is_hydrated=bool(_cap.get("ca_is_hydrated", False)),
            ca_total_capital=float(_cap.get("ca_total_capital", 0.0)),
            ca_valid_brokers=int(_cap.get("ca_valid_brokers", 0)),
            mabm_brokers_ready=bool(_cap.get("mabm_brokers_ready", False)),
            is_post_hydration=bool(_cap.get("is_post_hydration", False)),
        )

        # Publish the fully-constructed snapshot so that CapitalAllocationBrain
        # and MABM helpers can call get_current_cycle_snapshot() and get
        # consistent data for the remainder of this cycle.
        global _current_cycle_snapshot
        _current_cycle_snapshot = snapshot

        logger.info(
            "🟢 Trading loop alive — scanning %d symbols (balance=$%.2f open=%d)",
            len(symbols), snapshot.balance, snapshot.open_positions,
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

        # ── Phase 3: Scan & ranked entry ──────────────────────────────────
        if not user_mode:
            available_slots = max(0, self.max_positions - effective_open)
            if available_slots > 0:
                logger.info(
                    "🔍 Scanning markets — %d symbols | slots=%d open=%d",
                    len(symbols), available_slots, effective_open,
                )
                entries, blocked, scored = self._phase3_scan_and_enter(
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
    ) -> Tuple[int, int, int]:
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

        Returns (entries_taken, entries_blocked, symbols_scored).
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
                _pmc_params = _get_pmc().params
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

        candidates = []        # List[AIEngineSignal | _AISignal]  — AI-scored
        momentum_candidates = []  # collected from relaxed momentum scan
        scored = 0
        blocked = 0

        # Always-on top-volume tracker (feeds volume fallback for any streak)
        _best_volume_symbol: Optional[str] = None
        _best_volume_side: str = "long"
        _best_volume_entry_type: str = "swing"
        _best_volume: float = -1.0

        # Initialise the per-cycle score distribution debugger snapshot.
        _sdd = _get_sdd() if (_SDD_AVAILABLE and _get_sdd is not None) else None
        if _sdd is not None:
            _sdd.start_cycle()

        # ── Score every symbol ────────────────────────────────────────────
        for symbol in symbols:
            # Cap: stop scoring once we have 10× the available slots — enough
            # diversity to find the top-N without scanning every symbol when the
            # market has 700+ pairs.
            if len(candidates) >= available_slots * 10:
                if _sdd is not None:
                    _sdd.record_skip(symbol, "cap_reached")
                break

            try:
                df = self._fetch_df(broker, symbol)
                if df is None or len(df) < 100:
                    if _sdd is not None:
                        _sdd.record_skip(symbol, "data_insufficient")
                    continue

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
                    continue

                # Determine trend from apex market filter
                try:
                    allow, trend, _ = self.apex.check_market_filter(df, indicators)
                    if not allow:
                        blocked += 1
                        if _sdd is not None:
                            _sdd.record_skip(symbol, "market_filter")
                        continue
                except Exception:
                    trend = "uptrend"

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
                        logger.info(
                            "✅ Signal passed — %s score=%.1f threshold=%.1f",
                            symbol, sig.composite_score, sig.threshold_used,
                        )
                        candidates.append(sig)
                elif _AISignal is not None:
                    # Fallback: use apex.analyze_market directly and wrap result
                    analysis = self.apex.analyze_market(df, symbol, snapshot.balance)
                    if analysis.get("action") in ("enter_long", "enter_short"):
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
                        candidates.append(sig)

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
                logger.debug("Phase3 scoring error for %s: %s", symbol, sym_err)
                if _sdd is not None:
                    _sdd.record_skip(symbol, "exception")

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

        # ── Volume fallback: inject top-volume candidate when still empty ─
        # Active whenever _volume_fallback_enabled (always true in dead zone;
        # also true for profit-mode Level 3).
        if not candidates and _volume_fallback_enabled and _best_volume_symbol and _AISignal is not None:
            logger.warning(
                "💰 VOLUME FALLBACK — no candidates after momentum scan; "
                "injecting highest-volume symbol: %s (avg_vol=%.0f)",
                _best_volume_symbol, _best_volume,
            )
            fallback_sig = _AISignal(
                symbol=_best_volume_symbol,
                side=_best_volume_side,
                composite_score=_effective_hard_floor,
                position_multiplier=0.50,               # conservative micro-trade size
                entry_type=_best_volume_entry_type,
                threshold_used=_effective_hard_floor,
                reason="volume_fallback_guaranteed_activity",
                metadata={
                    "profit_mode_level": _pmc_level,
                    "volume_fallback": True,
                    "avg_volume": _best_volume,
                    "bypass_low_quality": True,
                    "dead_zone": _dead_zone,
                },
            )
            candidates.append(fallback_sig)

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
            return 0, blocked, scored

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
        # unconditionally, all quality filters are bypassed, and the flag is
        # immediately reset so exactly one cycle is forced.
        # _FORCE_LOCK ensures the read-and-reset is atomic under concurrent callers.
        global FORCE_NEXT_CYCLE
        with _FORCE_LOCK:
            _force_this_cycle = FORCE_NEXT_CYCLE
            if _force_this_cycle:
                FORCE_NEXT_CYCLE = False  # reset atomically — one-shot only
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
                df = self._fetch_df(broker, sig.symbol)
                if df is None or len(df) < 100:
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
                            _tpe_reason = getattr(_perm, "reason", "trade_permission_engine")
                            emit_cycle_trace(
                                CycleOutcome.ENTRY_VETOED,
                                reason=f"trade_permission_engine({sig.symbol}:{_tpe_reason})",
                            )
                            self._n_vetoed += 1
                            self._record_reject(_tpe_reason)
                            continue
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

                if action not in ("enter_long", "enter_short"):
                    blocked += 1
                    continue

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

            except Exception as exec_err:
                logger.warning("Phase3 execute error for %s: %s", sig.symbol, exec_err)
                blocked += 1

        # ── Emit score histogram for this cycle ──────────────────────────
        if _sdd is not None:
            rank_threshold = selected[0].threshold_used if selected else None
            _sdd.emit_histogram(
                entries_taken=entries,
                candidates_found=len(candidates),
                rank_threshold=rank_threshold,
            )

        return entries, blocked, scored

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
            # Standard broker interface: get_candles(symbol, limit=200)
            if hasattr(broker, "get_candles"):
                result = broker.get_candles(symbol, limit=200)
                if isinstance(result, tuple):
                    df, err = result
                    if err or df is None or len(df) < 10:
                        return None
                    return df
                if isinstance(result, pd.DataFrame) and len(result) >= 10:
                    return result
            return None
        except Exception as exc:
            logger.debug("_fetch_df error for %s: %s", symbol, exc)
            return None


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
# Single deterministic start-signal gate.
# Emitted exactly once by bot.py when BootstrapFSM reaches RUNNING_SUPERVISED.
TRADING_ENGINE_READY = threading.Event()


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

    try:
        result = broker.execute_order(
            symbol=symbol,
            side="buy",
            quantity=size,
            size_type="quote",
            ignore_min_trade=True,
            metadata={"reason": "EXEC_TEST_PROBE"},
        )
    except TypeError:
        # Broker implementation does not accept the metadata kwarg yet —
        # fall back to call without it (still honours ignore_min_trade).
        result = broker.execute_order(
            symbol=symbol,
            side="buy",
            quantity=size,
            size_type="quote",
            ignore_min_trade=True,
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
    t = threading.Thread(
        target=run_trading_loop,
        args=(strategy,),
        name="TradingLoop",
        daemon=True,
    )
    t.start()
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

    global _loop_running, _trading_active
    global _current_cycle_id, _current_cycle_capital, _current_cycle_snapshot

    logger.critical("🔥 ENTERED RUN_TRADING_LOOP FUNCTION")

    _live_verified = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower() == "true"
    if _live_verified and not TRADING_ENGINE_READY.is_set():
        logger.critical(
            "LIVE_CAPITAL_VERIFIED=true detected — bypassing passive activation wait gate"
        )
        TRADING_ENGINE_READY.set()

    logger.critical("🧵 WAITING FOR START SIGNAL")
    TRADING_ENGINE_READY.wait()
    logger.critical("🟢 START SIGNAL RECEIVED — ENTERING LIVE LOOP")

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
        # ── End Trading Loop Entry Anchor ──────────────────────────────────────

        cycle = 0
        _skipped_cycles = 0          # consecutive cycles skipped due to no broker
        _MAX_SKIP_LOG_INTERVAL = 5   # log downtime banner every N skipped cycles
        _activation_idle_since = None
        _activation_idle_timeout_s = float(os.getenv("NIJA_IDLE_ACTIVATION_TIMEOUT_S", "90") or 90)

        while _trading_active:
            try:
                # FIX 4: emit every cycle so a silent dead-bot is immediately visible.
                logger.critical("🟢 LIVE LOOP TICK")

                _live_now = False
                _sm_loop = None
                try:
                    if _SM_AVAILABLE and _get_state_machine is not None:
                        _sm_loop = _get_state_machine()
                        _live_now = bool(_sm_loop.is_live_trading_active())
                except Exception as _sm_loop_err:
                    logger.debug("CORE LOOP live probe failed: %s", _sm_loop_err)
                logger.critical("🧠 CORE LOOP ACTIVE — evaluating activation")
                logger.critical("CORE LOOP TICK | live=%s", _live_now)

                if _sm_loop is not None:
                    _live_verified_loop = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower() in (
                        "true", "1", "yes", "enabled"
                    )
                    try:
                        _current_state_loop = _sm_loop.get_current_state()
                    except Exception:
                        _current_state_loop = None

                    # Production lifecycle: OFF -> ARM (LIVE_PENDING_CONFIRMATION)
                    # before attempting final activation to LIVE_ACTIVE.
                    if (
                        _live_verified_loop
                        and _current_state_loop == _TradingState.OFF
                    ):
                        try:
                            logger.critical("🟡 AUTO-TRANSITION OFF → LIVE_PENDING_CONFIRMATION")
                            _sm_loop.transition_to(
                                _TradingState.LIVE_PENDING_CONFIRMATION,
                                "core loop arming: LIVE_CAPITAL_VERIFIED set",
                            )
                            _current_state_loop = _TradingState.LIVE_PENDING_CONFIRMATION
                        except Exception as _off_exit_err:
                            logger.warning("Core loop OFF->ARM transition failed: %s", _off_exit_err)

                    # Better lifecycle fallback: OFF -> ARMED-like state
                    # (LIVE_PENDING_CONFIRMATION) -> LIVE_ACTIVE via gate checks.
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
                            logger.critical(
                                "🟡 LIFECYCLE ARM: OFF -> LIVE_PENDING_CONFIRMATION"
                            )
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
                    logger.critical("⚡ TRYING TO ACTIVATE")
                    logger.critical("⚡ ATTEMPTING AUTO-ACTIVATION")
                    try:
                        _sm_loop.maybe_auto_activate(cycle_capital=_current_cycle_capital)
                    except Exception as _auto_act_err:
                        logger.warning("Core loop maybe_auto_activate failed: %s", _auto_act_err)

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
                            logger.warning("Idle activation fallback retry failed: %s", _idle_retry_err)
                        finally:
                            _activation_idle_since = time.monotonic()
                else:
                    _activation_idle_since = None

                    # Temporary hard bypass for runtime proof. Enable explicitly via env.
                    if os.getenv("NIJA_FORCE_LIVE_BYPASS", "false").lower() in (
                        "true", "1", "yes", "enabled"
                    ):
                        try:
                            if hasattr(_sm_loop, "force_activate_live"):
                                _sm_loop.force_activate_live(reason="core loop hard bypass")
                                logger.critical("🔥 FORCED LIVE ACTIVATION")
                        except Exception as _force_live_err:
                            logger.warning("force_activate_live failed: %s", _force_live_err)

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
                    _lcv_val = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower().strip()
                    if _lcv_val not in ("true", "1", "yes", "enabled"):
                        logger.critical(
                            "⚠️  OPERATOR ACTION REQUIRED: "
                            "LIVE_CAPITAL_VERIFIED is not set to 'true' (current value=%r). "
                            "Trading is permanently blocked until this env var is set. "
                            "Add 'LIVE_CAPITAL_VERIFIED=true' to your environment / Railway "
                            "variables and redeploy.",
                            _lcv_val,
                        )

                # Shared-cycle snapshot is captured before activation attempts.
                logger.critical("💰 AVAILABLE CAPITAL: %.2f", _cycle_balance)

                # Trigger live-state activation checks using this cycle's frozen
                # capital snapshot before any strategy execution starts.
                _supervisor_step_state_machine()

                # Single-line blocked diagnostic so operators can immediately
                # see why the loop is monitoring but not fully executing.
                try:
                    if _sm_loop is not None:
                        _state_now = _sm_loop.get_current_state()
                        _committed = bool(_sm_loop.get_activation_committed())
                        _can_dispatch = bool(_sm_loop.can_dispatch_trades())
                        _first_snap = bool(_sm_loop.get_first_snap_accepted())
                        _live_verified_now = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower() in (
                            "true", "1", "yes", "enabled"
                        )
                        _min_balance = float(os.getenv("MINIMUM_TRADING_BALANCE", "1.0") or 1.0)
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
                                _live_now,
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
                        "BROKER BALANCES: %s",
                        _diag_bm.get_all_balances() if _diag_bm is not None else "broker_manager unavailable",
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

                logger.critical("🔥 TRADE LOOP HEARTBEAT: active=%s", _trading_active)

                logger.critical("🟢 LIVE LOOP TICK — scanning markets")

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
                    if _skipped_cycles == 1 or _skipped_cycles % _MAX_SKIP_LOG_INTERVAL == 0:
                        logger.warning(
                            "⏸️  Trading paused — no broker connected "
                            "(skipped_cycles=%d, downtime≈%ds). "
                            "Retrying in %ds …",
                            _skipped_cycles,
                            _skipped_cycles * cycle_secs,
                            cycle_secs,
                        )
                    time.sleep(cycle_secs)
                    logger.critical("🚧 LOOP BLOCKED PATH REACHED — no broker connected, skipping cycle")
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
                        logger.critical("🚧 LOOP BLOCKED PATH REACHED — exec test mode fired, skipping normal cycle")
                        continue

                # Log available capital so operators can spot a $0.00 balance
                # that would silently block all position sizing and entries.
                _cycle_cap = (
                    _current_cycle_capital.get("ca_total_capital", 0.0)
                    if _current_cycle_capital
                    else 0.0
                )
                logger.critical("💰 CAPITAL CHECK: $%.2f", _cycle_cap)
                logger.critical("🚀 RUNNING TRADE CYCLE")
                strategy.run_cycle()
                time.sleep(cycle_secs)

            except Exception as _err:
                logger.critical(
                    "❌ LOOP ERROR: %s",
                    _err,
                    exc_info=True,
                )
                time.sleep(15)

    except Exception as e:
        logger.exception("💥 FATAL ERROR IN TRADING LOOP: %s", e)
        raise
