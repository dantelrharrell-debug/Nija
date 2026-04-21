"""
NIJA Capital Allocation Brain - Fund Grade
===========================================

AI-powered portfolio management system with dynamic capital allocation.

Features:
1. Dynamic Portfolio Weighting - Allocate capital based on performance
2. Multi-Strategy Allocation - Route capital to best strategies
3. Multi-Broker Allocation - Distribute across brokers optimally
4. Multi-Asset Allocation - Diversify across assets
5. Risk-Based Allocation - Sharpe, Drawdown, Volatility, Correlation

This creates fund-grade, institutional-quality portfolio management.

Expected improvements:
- Better risk-adjusted returns
- Lower portfolio volatility
- Higher Sharpe ratio
- Improved diversification

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import threading
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import json

logger = logging.getLogger("nija.capital_brain")

# ---------------------------------------------------------------------------
# Startup barrier helper — resolved at call-time to handle both direct
# execution (``python capital_allocation_brain.py``) and package imports
# (``from bot.capital_allocation_brain import …``).
# ---------------------------------------------------------------------------

def _wait_for_capital_hydrated(timeout: float = 30.0) -> bool:
    """Thin wrapper around :func:`capital_authority.wait_for_capital_hydrated`.

    Blocks until the CapitalAuthority has received its first snapshot (even a
    zero-balance one).  This is the correct gate for Capital Brain init (FIX 4):
    the brain must not start before the balance pipeline has run once, but it
    should not be permanently blocked just because the account balance is zero.
    """
    try:
        from bot.capital_authority import wait_for_capital_hydrated  # type: ignore[import]
    except ImportError:
        from capital_authority import wait_for_capital_hydrated  # type: ignore[import]
    return wait_for_capital_hydrated(timeout=timeout)


def _notify_state_machine_first_snap_accepted(snapshot: dict) -> None:
    """Propagate first-snap acceptance to the TradingStateMachine singleton.

    Validates that *snapshot* satisfies **all** live-data requirements before
    calling ``set_first_snap_accepted(True)``.  This function is the single
    enforcement point — callers must not bypass it by calling the setter
    directly.

    Conditions checked (all must hold):
        1. ``snapshot["valid_brokers"] > 0``     — at least one broker contributed
        2. ``snapshot["snapshot_source"] == "live_exchange"`` — real exchange data,
           not a placeholder produced when no brokers are connected
        3. ``CapitalAuthority.is_hydrated`` is True — coordinator has run and
           the CA is not in a fallback/stale state

    Errors are logged as warnings but never raised so the caller's flow is
    not disrupted — the hard gate in ``maybe_auto_activate()`` will surface any
    remaining issue as a ``RuntimeError`` at activation time.
    """
    # ── Condition 1: valid_brokers > 0 ────────────────────────────────────
    _vb = _safe_int(snapshot.get("valid_brokers", 0), 0)
    if _vb <= 0:
        logger.warning(
            "[CAPITAL_BRAIN] _notify_state_machine_first_snap_accepted: "
            "rejected — valid_brokers=%d (must be > 0). "
            "Broker data is not flowing; snapshot is not live.",
            _vb,
        )
        return

    # ── Condition 2: snapshot_source == "live_exchange" ───────────────────
    _src = str(snapshot.get("snapshot_source", ""))
    if _src != "live_exchange":
        logger.warning(
            "[CAPITAL_BRAIN] _notify_state_machine_first_snap_accepted: "
            "rejected — snapshot_source=%r (must be 'live_exchange'). "
            "Placeholder snapshots cannot activate live trading.",
            _src,
        )
        return

    # ── Condition 3: CapitalAuthority is hydrated ─────────────────────────
    try:
        try:
            from bot.capital_authority import get_capital_authority as _get_ca
        except ImportError:
            from capital_authority import get_capital_authority as _get_ca  # type: ignore[import]
        _ca = _get_ca()
        if not _ca.is_hydrated:
            logger.warning(
                "[CAPITAL_BRAIN] _notify_state_machine_first_snap_accepted: "
                "rejected — CapitalAuthority.is_hydrated=False. "
                "Hydration is not real (fallback state); cannot activate.",
            )
            return
    except ImportError:
        # CA module absent — skip hydration check (graceful degradation for
        # deployments without the full capital stack).
        logger.debug(
            "[CAPITAL_BRAIN] _notify_state_machine_first_snap_accepted: "
            "CapitalAuthority module unavailable — skipping hydration check"
        )

    # ── All conditions met — propagate to TradingStateMachine ─────────────
    logger.critical(
        "[CAPITAL_BRAIN] FIRST_SNAP_ACCEPTED_PROPAGATING: "
        "valid_brokers=%d snapshot_source=%s",
        _vb,
        _src,
    )
    try:
        try:
            from bot.trading_state_machine import get_state_machine as _get_sm
        except ImportError:
            from trading_state_machine import get_state_machine as _get_sm  # type: ignore[import]
        _get_sm().set_first_snap_accepted(True)
    except Exception as _sm_err:
        logger.warning(
            "[CAPITAL_BRAIN] could not propagate first_snap_accepted "
            "to TradingStateMachine: %s",
            _sm_err,
        )


def _safe_int(value: Any, default: int) -> int:
    """Parse int config values safely with fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    """Parse float config values safely with fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AllocationMethod(Enum):
    """Capital allocation methods"""
    EQUAL_WEIGHT = "equal_weight"  # 1/N allocation
    SHARPE_WEIGHTED = "sharpe_weighted"  # Weight by Sharpe ratio
    RISK_PARITY = "risk_parity"  # Equal risk contribution
    KELLY = "kelly"  # Kelly criterion
    MAX_SHARPE = "max_sharpe"  # Maximum Sharpe optimization
    MIN_VARIANCE = "min_variance"  # Minimum variance
    MEAN_VARIANCE = "mean_variance"  # Mean-variance optimization


@dataclass
class AllocationTarget:
    """Represents an allocation target (strategy, broker, asset)"""
    target_id: str
    target_type: str  # 'strategy', 'broker', 'asset'
    
    # Performance metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 1.0
    win_rate: float = 0.5
    avg_return: float = 0.0
    volatility: float = 0.0
    max_drawdown: float = 0.0
    
    # Allocation
    current_capital: float = 0.0
    target_allocation_pct: float = 0.0
    min_allocation_pct: float = 0.0
    max_allocation_pct: float = 1.0
    
    # Constraints
    is_active: bool = True
    allocation_priority: int = 1  # 1=high, 5=low
    
    # Returns history for correlation
    returns_history: List[float] = field(default_factory=list)
    
    last_updated: datetime = field(default_factory=datetime.now)
    
    def update_metrics(self, metrics: Dict):
        """Update performance metrics"""
        self.sharpe_ratio = metrics.get('sharpe_ratio', self.sharpe_ratio)
        self.sortino_ratio = metrics.get('sortino_ratio', self.sortino_ratio)
        self.profit_factor = metrics.get('profit_factor', self.profit_factor)
        self.win_rate = metrics.get('win_rate', self.win_rate)
        self.avg_return = metrics.get('avg_return', self.avg_return)
        self.volatility = metrics.get('volatility', self.volatility)
        self.max_drawdown = metrics.get('max_drawdown', self.max_drawdown)
        
        if 'returns' in metrics:
            self.returns_history.extend(metrics['returns'])
            # Keep only last 100 returns
            self.returns_history = self.returns_history[-100:]
        
        self.last_updated = datetime.now()


@dataclass
class AllocationPlan:
    """Capital allocation plan.

    Note on ``total_capital == 0.0``
    ---------------------------------
    A plan with ``total_capital=0.0`` and an empty ``allocations`` dict can
    mean one of three things:

    1. **System not ready** — the global startup lock has not been released
       yet (broker stabilization in progress).  :meth:`create_allocation_plan`
       returns a zero plan in this case and logs a startup-lock message.
    2. **Legitimately zero balance** — all registered brokers reported $0.
    3. **No active targets** — :attr:`~CapitalAllocationBrain.targets` is
       empty or all targets are inactive.

    Callers that need to distinguish case 1 should check
    ``get_startup_lock().is_set()`` from :mod:`bot.capital_authority` before
    requesting a plan.
    """
    timestamp: datetime = field(default_factory=datetime.now)
    total_capital: float = 0.0
    method: AllocationMethod = AllocationMethod.SHARPE_WEIGHTED
    
    # Allocations
    allocations: Dict[str, float] = field(default_factory=dict)  # target_id -> capital
    allocation_pcts: Dict[str, float] = field(default_factory=dict)  # target_id -> percentage
    
    # Portfolio metrics
    expected_return: float = 0.0
    expected_volatility: float = 0.0
    expected_sharpe: float = 0.0
    diversification_score: float = 0.0
    
    # Rebalancing
    rebalancing_actions: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'total_capital': self.total_capital,
            'method': self.method.value,
            'allocations': self.allocations,
            'allocation_pcts': self.allocation_pcts,
            'expected_metrics': {
                'return': self.expected_return,
                'volatility': self.expected_volatility,
                'sharpe': self.expected_sharpe,
                'diversification': self.diversification_score,
            },
            'rebalancing_actions': self.rebalancing_actions,
        }


class CapitalAllocationBrain:
    """
    AI-Powered Capital Allocation Brain
    
    Fund-grade portfolio management with dynamic allocation across:
    - Multiple strategies
    - Multiple brokers
    - Multiple assets
    
    Optimizes based on:
    - Sharpe ratio
    - Drawdown
    - Volatility
    - Correlation
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize capital allocation brain

        CapitalAuthority must be ready (total_capital > 0 and at least one
        registered broker source) before this brain can operate.  When the
        caller does not supply an explicit ``total_capital`` in *config*, the
        constructor calls :func:`~bot.capital_authority.wait_for_capital_ready`
        which blocks until the authority is ready (up to
        ``authority_startup_timeout_s`` seconds, default 30 s).

        Args:
            config: Configuration dictionary

        Raises:
            AssertionError: If no brokers have been registered in ``broker_registry``
                before initialization is attempted.  At least one broker must be
                registered so the capital bootstrap sequence has a data source.
        """
        # Invariant: at least one broker must be registered in the global
        # broker_registry before CapitalAllocationBrain can initialize.
        # Without this guard the brain starts with no capital source, causing
        # _force_minimal_capital_snapshot to collect an empty balance dict and
        # log "[BOOTSTRAP] balances collected: {}".
        try:
            from bot.broker_registry import broker_registry as _br
        except ImportError:
            from broker_registry import broker_registry as _br  # type: ignore[import]
        assert len(_br) > 0, (
            "CapitalAllocationBrain requires at least one broker registered in "
            "broker_registry before initialization.  Register a platform broker "
            "via MultiAccountBrokerManager.register_platform_broker() first."
        )

        self.config = config or {}
        # Pin disabled: always sync from CapitalAuthority regardless of whether
        # total_capital was supplied in config.  This allows the live observed
        # equity to override any stale config value so CABrain always reads the
        # correct balance (e.g. $103.98) rather than a pinned/stale figure.
        self._explicit_total_capital = False
        
        # When true, caller explicitly pinned total_capital in config and runtime
        # auto-sync from CapitalAuthority must not overwrite that value.
        self._explicit_total_capital = "total_capital" in self.config

        # Acquire the CapitalAuthority singleton once at construction time so
        # every subsequent read goes to the same object that the coordinator
        # and broker-manager are updating.  Storing the reference here makes
        # the instance_id visible in logs / assertions and avoids the
        # "different CA instance" bug where a dynamic _get_ca() call returned
        # a newly-created (empty) singleton instead of the already-hydrated one.
        try:
            from bot.capital_authority import get_capital_authority as _get_ca_init
        except ImportError:
            try:
                from capital_authority import get_capital_authority as _get_ca_init  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "CapitalAllocationBrain: cannot import get_capital_authority — "
                    "ensure capital_authority.py is on sys.path"
                ) from exc
        self.capital_authority = _get_ca_init()
        logger.info("[CapitalAllocationBrain] acquired CA instance_id=%d", id(self.capital_authority))

        # Acquire the process-wide startup lock so that evaluation methods can
        # gate on it without doing a module-level import each time.
        try:
            from bot.capital_authority import get_startup_lock as _get_sl
        except ImportError:
            from capital_authority import get_startup_lock as _get_sl  # type: ignore[import]
        self._startup_lock = _get_sl()

        # When the caller explicitly pins a capital value (testing / paper-trade
        # overrides), store it here.  The total_capital property returns this
        # value instead of reading from the CA so the pinned figure is stable.
        self._pinned_capital: Optional[float] = (
            float(self.config["total_capital"]) if self._explicit_total_capital else None
        )

        # Allocation parameters
        self.reserve_pct = self.config.get('reserve_pct', 0.1)  # 10% reserve
        self.rebalance_threshold = self.config.get('rebalance_threshold', 0.05)  # 5%
        self.rebalance_frequency_hours = self.config.get('rebalance_frequency_hours', 24)
        
        # Default allocation method
        self.default_method = AllocationMethod(
            self.config.get('default_method', 'sharpe_weighted')
        )
        
        # Risk parameters
        self.max_position_pct = self.config.get('max_position_pct', 0.25)  # 25% max
        self.min_position_pct = self.config.get('min_position_pct', 0.02)  # 2% min
        self.target_volatility = self.config.get('target_volatility', 0.15)  # 15% annual
        
        # Allocation targets
        self.targets: Dict[str, AllocationTarget] = {}
        
        # Current allocation plan
        self.current_plan: Optional[AllocationPlan] = None
        self.last_rebalance: Optional[datetime] = None
        
        # Performance tracking
        self.allocation_history: List[AllocationPlan] = []
        self.performance_history: List[Dict] = []
        self._authority_bootstrap_lock = threading.Lock()
        self._authority_bootstrap_thread: Optional[threading.Thread] = None
        self._authority_bootstrap_attempts = max(
            1, _safe_int(self.config.get("authority_bootstrap_attempts", 30), 30)
        )
        self._authority_bootstrap_interval_s = max(
            0.25,
            _safe_float(self.config.get("authority_bootstrap_interval_s", 1.0), 1.0),
        )
        # Bootstrap escape-hatch phase flag: True until the first snapshot has
        # been forced via refresh_authority()'s bootstrap path.  Set to False
        # once CA confirms hydration so that subsequent calls skip the forced
        # snapshot logic and follow the normal coordinator refresh path.
        self._bootstrap_phase: bool = True

        # Hard startup dependency barrier: CapitalAllocationBrain must NOT
        # initialize until CapitalAuthority has been hydrated (FIX 4).
        # Block until the coordinator has published at least one snapshot —
        # even a zero-balance snapshot qualifies, because a zero balance is a
        # valid confirmed state.  The old gate (_wait_for_capital_ready, which
        # required real_capital > 0) permanently blocked initialization for
        # genuinely empty accounts.
        if not self._explicit_total_capital:
            startup_timeout_s = _safe_float(
                self.config.get("authority_startup_timeout_s", 30.0), 30.0
            )
            try:
                _wait_for_capital_hydrated(timeout=startup_timeout_s)
            except RuntimeError as exc:
                logger.warning(
                    "[CapitalAllocationBrain] %s — brain will initialize with $0 capital "
                    "and recover asynchronously once the authority becomes hydrated "
                    "(e.g. delayed broker connect).",
                    exc,
                )
                # NOTE: initialization continues with $0 capital in this
                # branch.  The async bootstrap thread will retry until the
                # authority becomes ready.  Callers that require a hard
                # guarantee (no $0 capital) should treat this path as an error.
                self._start_async_authority_bootstrap()
            else:
                self.refresh_authority()
        
        logger.info(
            f"🧠 Capital Allocation Brain initialized: "
            f"capital=${self.total_capital:,.2f}, "
            f"method={self.default_method.value}"
        )

    @property
    def total_capital(self) -> float:
        """
        Live total capital — always read directly from CapitalAuthority.

        When the caller explicitly pinned a capital value in *config*
        (``_pinned_capital is not None``) that fixed value is returned so
        tests and paper-trade overrides remain stable.  In all other cases
        the value is read from the CapitalAuthority singleton, which is the
        single source of truth for every live trading module.

        No caching is performed here: every read goes straight to
        ``self.capital_authority.total_capital`` to prevent stale-value bugs
        where a locally-cached copy diverges from the authoritative figure.
        """
        if self._pinned_capital is not None:
            return self._pinned_capital
        return self.capital_authority.total_capital

    def refresh_authority(self) -> float:
        """
        Fail-safe auto-refresh of unified CapitalAuthority.

        When called during an active NijaCoreLoop cycle the method first checks
        whether ``nija_core_loop.get_current_cycle_snapshot()`` has already
        captured a frozen capital snapshot for this cycle.  If it has, and
        CapitalAuthority is confirmed hydrated, the method returns the
        cycle-snapshot capital figure immediately — avoiding a duplicate MABM
        refresh that could produce a different number than the one
        TradingStateMachine and MABM readiness checks are using.

        Falls back to the full MABM refresh when:
          • No cycle snapshot is available (called outside run_trading_loop)
          • CA is not yet hydrated (bootstrap phase — must run the full path)

        Returns:
            Latest observed total capital (>= 0).
        """
        # ── Fast path: use frozen cycle snapshot when available ───────────
        # Only valid AFTER bootstrap (ca_is_hydrated must be True in the snap).
        if getattr(self, "_bootstrap_phase", True) is False:
            try:
                try:
                    from nija_core_loop import get_current_cycle_snapshot as _get_snap  # type: ignore[import]
                except ImportError:
                    from bot.nija_core_loop import get_current_cycle_snapshot as _get_snap  # type: ignore[import]
                _snap = _get_snap()
                if _snap is not None and _snap.ca_is_hydrated:
                    logger.debug(
                        "[CapitalAllocationBrain] refresh_authority fast-path: "
                        "using frozen cycle snapshot cycle_id=%s total=$%.2f",
                        _snap.cycle_id,
                        _snap.ca_total_capital,
                    )
                    return max(0.0, _snap.ca_total_capital)
            except Exception as _sp_err:
                logger.debug(
                    "[CapitalAllocationBrain] cycle snapshot fast-path failed: %s", _sp_err
                )

        # --- BOOTSTRAP ESCAPE HATCH (CRITICAL) ---
        # If CA is not yet hydrated and we are still in bootstrap phase, force
        # MABM to build and publish the initial snapshot regardless of startup
        # lock state.  This breaks the initialization deadlock where the lock
        # won't be set until CA is hydrated and CA won't be hydrated until the
        # lock-gated refresh path is allowed to run.
        if not self.capital_authority.is_hydrated and getattr(self, "_bootstrap_phase", True):
            logger.warning(
                "[BOOTSTRAP] CA not hydrated — forcing initial snapshot (lock bypass enabled)"
            )
            # _first_snap_accepted tracks whether the first snapshot passed the
            # live-exchange guard.  It is only set to True after validating that
            # the snapshot (a) has at least one valid broker and (b) came from a
            # live exchange source — not a placeholder produced when all brokers
            # report balance=0.0 due to exchange placeholder data.
            _first_snap_accepted = False
            try:
                try:
                    from bot.multi_account_broker_manager import multi_account_broker_manager as _mabm_bs
                except ImportError:
                    from multi_account_broker_manager import multi_account_broker_manager as _mabm_bs  # type: ignore[import]
                if _mabm_bs is not None and hasattr(_mabm_bs, "refresh_capital_authority"):
                    # SECOND GATE: block bootstrap snapshot until MABM confirms all
                    # registered platform brokers are fully ready (connected + payload).
                    # Without this gate, refresh_capital_authority() could be called when
                    # brokers are not yet connected, producing a $0 capital snapshot that
                    # permanently blocks entry execution after the bootstrap handoff.
                    if hasattr(_mabm_bs, "all_brokers_fully_ready") and not _mabm_bs.all_brokers_fully_ready():
                        logger.warning(
                            "[CAPITAL_BRAIN] MABM not ready — blocking CA bootstrap "
                            "(not all_brokers_fully_ready)"
                        )
                    else:
                        _first_snap = _mabm_bs.refresh_capital_authority(trigger="bootstrap_force")
                        # THIRD GATE: validate first snapshot when all brokers are confirmed
                        # ready.  A broker marked "fully ready" can still return balance=0.0
                        # if the exchange API responded with placeholder data.  Require the
                        # first accepted snapshot to have (a) valid_brokers > 0 and (b)
                        # snapshot_source == "live_exchange".
                        # Use all_brokers_fully_ready presence as a version gate:
                        # older MABM instances that don't expose this method skip the
                        # snapshot-source validation so backward compatibility is preserved.
                        if hasattr(_mabm_bs, "all_brokers_fully_ready") and isinstance(_first_snap, dict):
                            _vb = int(float(_first_snap.get("valid_brokers", 0)))
                            _src = str(_first_snap.get("snapshot_source", ""))
                            if _vb > 0 and _src == "live_exchange":
                                _first_snap_accepted = True
                                logger.critical(
                                    "FIRST_VALID_CAPITAL_SNAPSHOT_ACCEPTED "
                                    "valid_brokers=%d snapshot_source=%s total=$%.2f",
                                    _vb,
                                    _src,
                                    float(_first_snap.get("total_capital", 0.0)),
                                )
                                # Propagate to the trading state machine so the hard
                                # activation gate in maybe_auto_activate() passes.
                                # Pass the snapshot so the function validates all
                                # live-data requirements itself.
                                _notify_state_machine_first_snap_accepted(_first_snap)
                            else:
                                logger.critical(
                                    "[CAPITAL_BRAIN] FIRST_VALID_CAPITAL_SNAPSHOT_REJECTED — "
                                    "valid_brokers=%d snapshot_source=%r. "
                                    "Blocking bootstrap acceptance (expected valid_brokers>0 "
                                    "and snapshot_source='live_exchange').",
                                    _vb,
                                    _src,
                                )
                        else:
                            # all_brokers_fully_ready not supported or snapshot is not a
                            # dict: legacy MABM path — pass snapshot if available so the
                            # validated propagator can still enforce live-data checks.
                            # If snapshot is not a dict, skip propagation entirely
                            # (the hard gate in maybe_auto_activate will block if needed).
                            _first_snap_accepted = True
                            if isinstance(_first_snap, dict):
                                _notify_state_machine_first_snap_accepted(_first_snap)
                            else:
                                logger.warning(
                                    "[CAPITAL_BRAIN] legacy MABM snapshot is not a dict "
                                    "(%r) — skipping first_snap propagation; "
                                    "hard gate in maybe_auto_activate will enforce.",
                                    type(_first_snap).__name__,
                                )
            except Exception as _bs_exc:
                logger.warning("[BOOTSTRAP] forced snapshot attempt failed: %s", _bs_exc)
            if self.capital_authority.is_hydrated and _first_snap_accepted:
                self._bootstrap_phase = False
                logger.info("[BOOTSTRAP] initial snapshot published → hydration unlocked")
                return float(self.capital_authority.total_capital)

        # PHASE 2/3: no lock dependency — if CA is already hydrated, proceed
        # immediately regardless of startup lock state.  Blocking on the lock
        # when CA is hydrated is wrong: it prevents the brain from reading a
        # valid capital figure that the coordinator has already published.
        # Only skip the refresh entirely when the lock is NOT set AND CA is
        # also not hydrated (system is mid-bootstrap and snapshot seed is
        # still in progress — allow through so MABM can complete the seed).
        if not self._startup_lock.is_set() and not self.capital_authority.is_hydrated:
            logger.info(
                "[CapitalAllocationBrain] Startup lock not released and CA not hydrated — "
                "allowing refresh to bootstrap CA hydration (PHASE 2 bypass)"
            )
        try:
            # Event-driven refresh path (preferred): ask multi-account manager to
            # rebuild authority from currently connected healthy brokers.
            try:
                from bot.multi_account_broker_manager import multi_account_broker_manager as _mabm
            except ImportError:
                from multi_account_broker_manager import multi_account_broker_manager as _mabm  # type: ignore[import]
            if _mabm is not None and hasattr(_mabm, "refresh_capital_authority"):
                logger.info(
                    "[CapitalAllocationBrain] Triggering CapitalAuthority refresh via MABM"
                )
                _snapshot = _mabm.refresh_capital_authority(trigger="capital_allocation_brain")
                if isinstance(_snapshot, dict):
                    logger.info(
                        "[CapitalAllocationBrain] MABM refresh result: ready=%s total=$%.2f "
                        "valid_brokers=%d kraken_capital=$%.2f",
                        bool(_snapshot.get("ready", False)),
                        float(_snapshot.get("total_capital", 0.0)),
                        int(_snapshot.get("valid_brokers", 0)),
                        float(_snapshot.get("kraken_capital", 0.0)),
                    )
                else:
                    logger.warning(
                        "[CapitalAllocationBrain] MABM refresh returned non-dict snapshot: %r",
                        _snapshot,
                    )
        except Exception as exc:
            logger.warning(
                "[CapitalAllocationBrain] MABM CapitalAuthority refresh failed: %s",
                exc,
            )

        # Now read capital from the persistent CA reference.  Using
        # self.capital_authority (set once at __init__) guarantees we are
        # reading from the same singleton instance that the coordinator and
        # broker-manager are writing to.
        ca = self.capital_authority

        # PHASE 3: gate on ca.is_hydrated, not on CAPITAL_SYSTEM_READY.
        # CAPITAL_SYSTEM_READY requires real_capital > 0 (ACTIVE_CAPITAL state),
        # which permanently blocks the brain for genuinely empty or zero-balance
        # accounts at startup.  is_hydrated fires as soon as any snapshot has been
        # published — capital = 0.0 is a valid startup state and must not block
        # Brain initialization.
        _system_ready = ca.is_hydrated
        if not _system_ready:
            logger.warning(
                "[CapitalAllocationBrain] CA not yet hydrated — deferring bootstrap validation"
            )
            return 0.0

        total_capital = ca.total_capital
        logger.info(
            "[CapitalAllocationBrain] CapitalAuthority total_capital read: $%.2f",
            total_capital,
        )

        # ------------------------------------------------------------------ #
        # DEBUG: surface exactly what snapshot / pin state produced this value.
        # Remove once the capital-read discrepancy is confirmed resolved.
        # ------------------------------------------------------------------ #
        try:
            _snapshot_debug = getattr(ca, "_last_typed_snapshot", None)
            logger.info(
                "[CABrain DEBUG] "
                "pinned=%s | "
                "snapshot_exists=%s | "
                "snapshot_value=%s | "
                "property_value=%s",
                self._explicit_total_capital,
                _snapshot_debug is not None,
                getattr(_snapshot_debug, "real_capital", None),
                ca.total_capital,
            )
        except Exception as _dbg_exc:
            logger.debug("[CABrain DEBUG] introspection failed: %s", _dbg_exc)

        return max(0.0, total_capital)

    def _start_async_authority_bootstrap(self) -> None:
        """
        Start a short-lived background refresh loop to close startup timing gaps.

        This prevents the brain from staying at 0 when CapitalAuthority is polled
        before brokers complete connection and initial balance publication.
        """
        if self._explicit_total_capital:
            return
        with self._authority_bootstrap_lock:
            if (
                self._authority_bootstrap_thread is not None
                and self._authority_bootstrap_thread.is_alive()
            ):
                return

            self._authority_bootstrap_thread = threading.Thread(
                target=self._authority_bootstrap_worker,
                name="capital-authority-bootstrap",
                daemon=True,
            )
            self._authority_bootstrap_thread.start()

    def _authority_bootstrap_worker(self) -> None:
        """Retry CapitalAuthority refresh until non-zero capital is observed."""
        for attempt in range(1, self._authority_bootstrap_attempts + 1):
            try:
                latest_total = self.refresh_authority()
            except ValueError as exc:
                logger.warning(
                    "[CapitalAllocationBrain] bootstrap attempt=%d CA validation error: %s",
                    attempt,
                    exc,
                )
                latest_total = 0.0
            if latest_total > 0.0:
                logger.info(
                    "[CapitalAllocationBrain] async CapitalAuthority bootstrap succeeded "
                    "attempt=%d total=$%.2f",
                    attempt,
                    latest_total,
                )
                return
            if attempt < self._authority_bootstrap_attempts:
                time.sleep(self._authority_bootstrap_interval_s)
        logger.warning(
            "[CapitalAllocationBrain] async CapitalAuthority bootstrap exhausted "
            "attempts=%d (CA id=%d capital=$%.2f)",
            self._authority_bootstrap_attempts,
            id(self.capital_authority),
            self.capital_authority.total_capital,
        )

    # Backward-compatible aliases requested by ops runbooks
    def _rebuild_capital_authority(self) -> float:
        """Legacy alias for :meth:`refresh_authority`."""
        return self.refresh_authority()

    def _sync_broker_balances(self) -> float:
        """Legacy alias for :meth:`refresh_authority`."""
        return self.refresh_authority()
    
    def add_target(
        self,
        target_id: str,
        target_type: str,
        initial_metrics: Dict = None
    ):
        """
        Add allocation target (strategy, broker, or asset)
        
        Args:
            target_id: Unique identifier
            target_type: 'strategy', 'broker', or 'asset'
            initial_metrics: Initial performance metrics
        """
        target = AllocationTarget(
            target_id=target_id,
            target_type=target_type
        )
        
        if initial_metrics:
            target.update_metrics(initial_metrics)
        
        self.targets[target_id] = target
        logger.info(f"➕ Added allocation target: {target_id} ({target_type})")
    
    def update_target_performance(
        self,
        target_id: str,
        metrics: Dict
    ):
        """
        Update performance metrics for a target
        
        Args:
            target_id: Target identifier
            metrics: Performance metrics
        """
        if target_id not in self.targets:
            logger.warning(f"Target {target_id} not found, adding it")
            self.add_target(target_id, metrics.get('type', 'strategy'), metrics)
            return
        
        self.targets[target_id].update_metrics(metrics)
    
    def calculate_correlation_matrix(
        self,
        target_ids: List[str]
    ) -> np.ndarray:
        """
        Calculate correlation matrix for targets
        
        Args:
            target_ids: List of target IDs
        
        Returns:
            Correlation matrix
        """
        # Collect returns histories
        returns_data = []
        
        for target_id in target_ids:
            if target_id in self.targets:
                returns = self.targets[target_id].returns_history
                if len(returns) >= 10:  # Minimum data points
                    returns_data.append(returns)
                else:
                    # Pad with zeros if insufficient data
                    returns_data.append([0.0] * 10)
            else:
                returns_data.append([0.0] * 10)
        
        if not returns_data:
            return np.eye(len(target_ids))
        
        # Ensure all have same length (use minimum)
        min_length = min(len(r) for r in returns_data)
        returns_data = [r[-min_length:] for r in returns_data]
        
        # Calculate correlation
        if min_length >= 2:
            returns_df = pd.DataFrame(returns_data).T
            corr_matrix = returns_df.corr().values
            
            # Handle NaN values
            corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
            
            # Ensure valid correlation matrix
            np.fill_diagonal(corr_matrix, 1.0)
        else:
            # Default to identity matrix
            corr_matrix = np.eye(len(target_ids))
        
        return corr_matrix
    
    def allocate_equal_weight(
        self,
        target_ids: List[str],
        available_capital: float
    ) -> Dict[str, float]:
        """
        Equal weight allocation (1/N)
        
        Args:
            target_ids: List of target IDs
            available_capital: Capital to allocate
        
        Returns:
            Dictionary of allocations
        """
        n = len(target_ids)
        if n == 0:
            return {}
        
        allocation_per_target = available_capital / n
        
        return {
            target_id: allocation_per_target
            for target_id in target_ids
        }
    
    def allocate_sharpe_weighted(
        self,
        target_ids: List[str],
        available_capital: float
    ) -> Dict[str, float]:
        """
        Sharpe ratio weighted allocation
        
        Args:
            target_ids: List of target IDs
            available_capital: Capital to allocate
        
        Returns:
            Dictionary of allocations
        """
        # Get Sharpe ratios
        sharpes = []
        valid_targets = []
        
        for target_id in target_ids:
            if target_id in self.targets:
                target = self.targets[target_id]
                if target.is_active and target.sharpe_ratio > 0:
                    sharpes.append(max(0.1, target.sharpe_ratio))  # Floor at 0.1
                    valid_targets.append(target_id)
        
        if not valid_targets:
            # Fall back to equal weight
            return self.allocate_equal_weight(target_ids, available_capital)
        
        # Calculate weights proportional to Sharpe
        total_sharpe = sum(sharpes)
        weights = [s / total_sharpe for s in sharpes]
        
        # Apply min/max constraints
        allocations = {}
        for target_id, weight in zip(valid_targets, weights):
            target = self.targets[target_id]
            
            # Apply constraints
            weight = max(target.min_allocation_pct, weight)
            weight = min(target.max_allocation_pct, weight)
            
            allocations[target_id] = available_capital * weight
        
        # Normalize to ensure we use all capital
        total_allocated = sum(allocations.values())
        if total_allocated > 0:
            scale = available_capital / total_allocated
            allocations = {k: v * scale for k, v in allocations.items()}
        
        return allocations
    
    def allocate_risk_parity(
        self,
        target_ids: List[str],
        available_capital: float
    ) -> Dict[str, float]:
        """
        Risk parity allocation (equal risk contribution)
        
        Args:
            target_ids: List of target IDs
            available_capital: Capital to allocate
        
        Returns:
            Dictionary of allocations
        """
        # Get volatilities
        volatilities = []
        valid_targets = []
        
        for target_id in target_ids:
            if target_id in self.targets:
                target = self.targets[target_id]
                if target.is_active and target.volatility > 0:
                    volatilities.append(target.volatility)
                    valid_targets.append(target_id)
        
        if not valid_targets:
            return self.allocate_equal_weight(target_ids, available_capital)
        
        # Weight inversely proportional to volatility
        inv_vols = [1.0 / v for v in volatilities]
        total_inv_vol = sum(inv_vols)
        weights = [iv / total_inv_vol for iv in inv_vols]
        
        # Create allocations
        allocations = {}
        for target_id, weight in zip(valid_targets, weights):
            target = self.targets[target_id]
            
            # Apply constraints
            weight = max(target.min_allocation_pct, weight)
            weight = min(target.max_allocation_pct, weight)
            
            allocations[target_id] = available_capital * weight
        
        # Normalize
        total_allocated = sum(allocations.values())
        if total_allocated > 0:
            scale = available_capital / total_allocated
            allocations = {k: v * scale for k, v in allocations.items()}
        
        return allocations
    
    def allocate_kelly(
        self,
        target_ids: List[str],
        available_capital: float
    ) -> Dict[str, float]:
        """
        Kelly criterion allocation
        
        Args:
            target_ids: List of target IDs
            available_capital: Capital to allocate
        
        Returns:
            Dictionary of allocations
        """
        kelly_fractions = []
        valid_targets = []
        
        for target_id in target_ids:
            if target_id in self.targets:
                target = self.targets[target_id]
                if target.is_active:
                    # Kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
                    # Simplified: use Sharpe as proxy
                    kelly = min(0.25, max(0.01, target.sharpe_ratio / 10.0))
                    kelly_fractions.append(kelly)
                    valid_targets.append(target_id)
        
        if not valid_targets:
            return self.allocate_equal_weight(target_ids, available_capital)
        
        # Normalize Kelly fractions
        total_kelly = sum(kelly_fractions)
        if total_kelly > 1.0:
            kelly_fractions = [k / total_kelly for k in kelly_fractions]
        
        # Create allocations
        allocations = {}
        for target_id, kelly in zip(valid_targets, kelly_fractions):
            allocations[target_id] = available_capital * kelly
        
        return allocations
    
    def calculate_portfolio_metrics(
        self,
        allocations: Dict[str, float],
        target_ids: List[str]
    ) -> Tuple[float, float, float]:
        """
        Calculate expected portfolio metrics
        
        Args:
            allocations: Capital allocations
            target_ids: List of target IDs
        
        Returns:
            Tuple of (expected_return, expected_volatility, expected_sharpe)
        """
        # Collect weights, returns, and volatilities
        weights = []
        returns = []
        volatilities = []
        
        total_capital = sum(allocations.values())
        
        for target_id in target_ids:
            if target_id in allocations and target_id in self.targets:
                target = self.targets[target_id]
                weight = allocations[target_id] / total_capital if total_capital > 0 else 0
                
                weights.append(weight)
                returns.append(target.avg_return)
                volatilities.append(target.volatility)
        
        if not weights:
            return 0.0, 0.0, 0.0
        
        weights = np.array(weights)
        returns_arr = np.array(returns)
        vols_arr = np.array(volatilities)
        
        # Expected return
        expected_return = np.dot(weights, returns_arr)
        
        # Expected volatility (simplified - assumes no correlation)
        # For full accuracy, would need covariance matrix
        expected_volatility = np.sqrt(np.dot(weights**2, vols_arr**2))
        
        # Expected Sharpe
        expected_sharpe = expected_return / expected_volatility if expected_volatility > 0 else 0.0
        
        return expected_return, expected_volatility, expected_sharpe
    
    def calculate_diversification_score(
        self,
        allocations: Dict[str, float],
        target_ids: List[str]
    ) -> float:
        """
        Calculate portfolio diversification score (0-1)
        
        Uses correlation matrix and Herfindahl index.
        
        Args:
            allocations: Capital allocations
            target_ids: List of target IDs
        
        Returns:
            Diversification score (higher is better)
        """
        if len(target_ids) <= 1:
            return 0.0
        
        total_capital = sum(allocations.values())
        if total_capital == 0:
            return 0.0
        
        # Herfindahl index (concentration measure)
        weights = np.array([
            allocations.get(tid, 0) / total_capital
            for tid in target_ids
        ])
        herfindahl = np.sum(weights ** 2)
        
        # Diversification from Herfindahl (1/N is maximum diversification)
        max_diversification = 1.0 / len(target_ids)
        diversification = (1.0 - herfindahl) / (1.0 - max_diversification) if max_diversification < 1.0 else 0.0
        
        # Get correlation matrix
        corr_matrix = self.calculate_correlation_matrix(target_ids)
        
        # Average correlation (excluding diagonal)
        n = len(target_ids)
        if n > 1:
            avg_corr = (np.sum(corr_matrix) - n) / (n * (n - 1))
            
            # Adjust diversification by correlation
            # Lower correlation = better diversification
            diversification *= (1.0 - avg_corr)
        
        return max(0.0, min(1.0, diversification))
    
    def create_allocation_plan(
        self,
        method: AllocationMethod = None,
        target_filter: Dict = None
    ) -> AllocationPlan:
        """
        Create capital allocation plan
        
        Args:
            method: Allocation method (uses default if None)
            target_filter: Filter targets (e.g., {'type': 'strategy'})
        
        Returns:
            AllocationPlan
        """
        # HARD BLOCK — startup lock not yet released AND CA not hydrated.
        # Skip allocation only when both conditions are true: lock not set AND
        # the authority has not yet published any snapshot.  If CA is hydrated,
        # allow the plan to proceed even before the startup lock is set — the
        # lock may be released asynchronously after the first snapshot, and
        # blocking here when real capital data is already available is wrong.
        if not self._startup_lock.is_set() and not self.capital_authority.is_hydrated:
            logger.info(
                "[CapitalAllocationBrain] Startup lock not released and CA not hydrated — "
                "skipping create_allocation_plan (no snapshot, no refresh)"
            )
            return AllocationPlan(
                total_capital=0.0,
                method=method or self.default_method,
            )

        # Critical guard: never allocate when total capital is non-positive.
        # refresh_authority() triggers a broker-manager refresh cycle so the
        # CA snapshot is up-to-date before we read self.total_capital below.
        try:
            self.refresh_authority()
        except ValueError as exc:
            logger.error(
                "⛔ Capital allocation blocked: CA validation error — %s", exc
            )
            return AllocationPlan(
                total_capital=0.0,
                method=method or self.default_method,
            )

        method = method or self.default_method

        if self.total_capital <= 0.0:
            logger.error(
                "⛔ Capital allocation blocked: total_capital <= 0.0 "
                "(total_capital=$%.2f)",
                self.total_capital,
            )
            return AllocationPlan(
                total_capital=self.total_capital,
                method=method,
            )
        
        # Filter targets
        target_ids = []
        for target_id, target in self.targets.items():
            if not target.is_active:
                continue
            
            if target_filter:
                if 'type' in target_filter and target.target_type != target_filter['type']:
                    continue
                # Add more filter conditions as needed
            
            target_ids.append(target_id)
        
        if not target_ids:
            logger.warning("No active targets for allocation")
            return AllocationPlan(
                total_capital=self.total_capital,
                method=method
            )
        
        # Calculate available capital (after reserve)
        available_capital = self.total_capital * (1.0 - self.reserve_pct)
        
        # Allocate based on method
        if method == AllocationMethod.EQUAL_WEIGHT:
            allocations = self.allocate_equal_weight(target_ids, available_capital)
        elif method == AllocationMethod.SHARPE_WEIGHTED:
            allocations = self.allocate_sharpe_weighted(target_ids, available_capital)
        elif method == AllocationMethod.RISK_PARITY:
            allocations = self.allocate_risk_parity(target_ids, available_capital)
        elif method == AllocationMethod.KELLY:
            allocations = self.allocate_kelly(target_ids, available_capital)
        else:
            # Default to Sharpe weighted
            allocations = self.allocate_sharpe_weighted(target_ids, available_capital)
        
        # Calculate allocation percentages
        allocation_pcts = {
            target_id: (capital / self.total_capital)
            for target_id, capital in allocations.items()
        }
        
        # Calculate portfolio metrics
        expected_return, expected_vol, expected_sharpe = self.calculate_portfolio_metrics(
            allocations, target_ids
        )
        
        # Calculate diversification
        diversification = self.calculate_diversification_score(allocations, target_ids)
        
        # Create plan
        plan = AllocationPlan(
            total_capital=self.total_capital,
            method=method,
            allocations=allocations,
            allocation_pcts=allocation_pcts,
            expected_return=expected_return,
            expected_volatility=expected_vol,
            expected_sharpe=expected_sharpe,
            diversification_score=diversification,
        )
        
        # Calculate rebalancing actions if we have a current plan
        if self.current_plan:
            plan.rebalancing_actions = self._calculate_rebalancing_actions(plan)
        
        return plan
    
    def _calculate_rebalancing_actions(
        self,
        new_plan: AllocationPlan
    ) -> List[Dict]:
        """
        Calculate rebalancing actions
        
        Args:
            new_plan: New allocation plan
        
        Returns:
            List of rebalancing actions
        """
        actions = []
        
        for target_id in set(self.current_plan.allocations.keys()) | set(new_plan.allocations.keys()):
            current_allocation = self.current_plan.allocations.get(target_id, 0.0)
            new_allocation = new_plan.allocations.get(target_id, 0.0)
            
            diff = new_allocation - current_allocation
            diff_pct = abs(diff) / self.total_capital if self.total_capital > 0 else 0
            
            # Only create action if difference exceeds threshold
            if diff_pct >= self.rebalance_threshold:
                action = {
                    'target_id': target_id,
                    'action': 'increase' if diff > 0 else 'decrease',
                    'current_capital': current_allocation,
                    'target_capital': new_allocation,
                    'change': diff,
                    'change_pct': (diff / self.total_capital) if self.total_capital > 0 else 0,
                }
                actions.append(action)
        
        return actions
    
    def should_rebalance(self) -> bool:
        """
        Check if portfolio should be rebalanced
        
        Returns:
            True if rebalancing is needed
        """
        # No current plan
        if self.current_plan is None:
            return True
        
        # Time-based rebalancing
        if self.last_rebalance is None:
            return True
        
        hours_since_rebalance = (
            datetime.now() - self.last_rebalance
        ).total_seconds() / 3600
        
        if hours_since_rebalance >= self.rebalance_frequency_hours:
            return True
        
        # Threshold-based rebalancing
        # Check if any allocation drifted significantly
        for target_id, target in self.targets.items():
            if not target.is_active:
                continue
            
            current_pct = self.current_plan.allocation_pcts.get(target_id, 0.0)
            target_pct = target.target_allocation_pct
            
            if abs(current_pct - target_pct) >= self.rebalance_threshold:
                return True
        
        return False
    
    def execute_rebalancing(self, plan: AllocationPlan):
        """
        Execute rebalancing plan
        
        Args:
            plan: Allocation plan to execute
        """
        logger.info(
            f"💰 Executing rebalancing: "
            f"{len(plan.rebalancing_actions)} actions, "
            f"expected Sharpe={plan.expected_sharpe:.2f}"
        )
        
        # Log actions
        for action in plan.rebalancing_actions:
            logger.info(
                f"  {action['action'].upper()} {action['target_id']}: "
                f"${action['current_capital']:.2f} → ${action['target_capital']:.2f} "
                f"({action['change_pct']*100:+.1f}%)"
            )
        
        # Update current plan
        self.current_plan = plan
        self.last_rebalance = datetime.now()
        
        # Store in history
        self.allocation_history.append(plan)
        
        # Update target allocations
        for target_id, allocation in plan.allocations.items():
            if target_id in self.targets:
                self.targets[target_id].current_capital = allocation
                self.targets[target_id].target_allocation_pct = plan.allocation_pcts[target_id]
    
    def get_allocation_summary(self) -> Dict:
        """
        Get comprehensive allocation summary
        
        Returns:
            Summary dictionary
        """
        if self.current_plan is None:
            return {'status': 'no_plan'}
        
        return {
            'total_capital': self.total_capital,
            'allocated_capital': sum(self.current_plan.allocations.values()),
            'reserve_capital': self.total_capital * self.reserve_pct,
            'method': self.current_plan.method.value,
            'num_targets': len(self.current_plan.allocations),
            'allocations': self.current_plan.allocations,
            'allocation_pcts': self.current_plan.allocation_pcts,
            'expected_metrics': {
                'return': self.current_plan.expected_return,
                'volatility': self.current_plan.expected_volatility,
                'sharpe': self.current_plan.expected_sharpe,
                'diversification': self.current_plan.diversification_score,
            },
            'last_rebalance': self.last_rebalance.isoformat() if self.last_rebalance else None,
            'rebalancing_needed': self.should_rebalance(),
        }

    # ── Advisory interface for CapitalDecisionEngine ─────────────────────────

    def advise(self, usable_capital: float) -> Dict:
        """
        Advisory-only interface consumed by :class:`CapitalDecisionEngine`.

        Returns a read-only advice dict without writing any budgets directly.
        Callers must not use this to size positions — only
        ``CapitalDecisionEngine`` translates the advice into final budgets.

        Args:
            usable_capital: Current usable capital from CapitalAuthority.

        Returns:
            Dict with keys:
                ``strategy_weights``  – {strategy_id: fraction}
                ``allocation_pcts``   – {target_id: pct}   (from current plan)
                ``method``            – allocation method name
                ``rebalance_needed``  – bool
        """
        try:
            if self.current_plan is not None:
                return {
                    "strategy_weights": {
                        tid: pct
                        for tid, pct in self.current_plan.allocation_pcts.items()
                    },
                    "allocation_pcts": dict(self.current_plan.allocation_pcts),
                    "method": self.current_plan.method.value,
                    "rebalance_needed": self.should_rebalance(),
                }
        except Exception as exc:
            logger.debug("[CapitalAllocationBrain] advise() error: %s", exc)
        return {
            "strategy_weights": {},
            "allocation_pcts": {},
            "method": "unavailable",
            "rebalance_needed": False,
        }
