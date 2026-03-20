"""
NIJA Capital Concentration Engine
===================================

Six interrelated capital-routing features that work together to push capital
toward winning conditions, away from underperforming accounts, and surface
everything on a live dashboard:

  1. Capital Concentration Mode  — when an account's rolling win-rate exceeds
     70 %, the engine returns a size multiplier > 1.0 so more capital flows
     into the hot condition.  Automatically reverts when win-rate drops back.

  2. Account Performance Ranking — sorts all registered accounts by cumulative
     net P&L so the trade router can prefer the top performers.  Returns an
     ordered ``List[AccountRank]`` with full per-account stats.

  3. Kill Weak Accounts — when an account's current drawdown from its equity
     peak exceeds 10 %, the engine linearly reduces its allocation multiplier
     toward 0.0, protecting capital from further erosion.

  4. Multi-Account Live Execution Verifier — checks each known account for
     paper-trading / dry-run flags and returns a ``LiveStatus`` per account so
     the operator can confirm that real money is being deployed.

  5. Growth-Optimised Allocation — uses a half-Kelly formula to compute the
     mathematically-optimal position size given each account's current win-rate
     and average win/loss ratio, then applies the concentration multiplier on top
     for maximum compounding.

  6. Real-Time Dashboard Routes — registers Flask REST endpoints under
     ``/api/v1/capital-concentration/…`` that any dashboard or monitoring tool
     can poll to *see the money working* in real time.

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │                   CapitalConcentrationEngine                         │
    │                                                                      │
    │  record_trade(account_id, pnl_usd, is_win, equity_usd=None)         │
    │    → updates rolling win-rate window, drawdown, and Kelly stats      │
    │                                                                      │
    │  update_equity(account_id, equity_usd)                               │
    │    → refreshes drawdown without recording a trade                    │
    │                                                                      │
    │  get_concentration_multiplier(account_id) → float                   │
    │    → > 1.0 when hot (concentration mode)                             │
    │    → 1.0 when normal                                                 │
    │    → < 1.0 when weakened by drawdown (kill mode)                     │
    │                                                                      │
    │  get_optimal_position_usd(account_id, balance_usd,                   │
    │                           base_risk_pct=0.02) → float               │
    │    → half-Kelly size × concentration multiplier                      │
    │                                                                      │
    │  get_ranked_accounts() → List[AccountRank]                           │
    │    → accounts sorted by net P&L (best first)                         │
    │                                                                      │
    │  get_top_accounts(n=3) → List[str]                                   │
    │    → top-n account_ids by P&L                                        │
    │                                                                      │
    │  verify_live_execution(brokers: dict) → Dict[str, LiveStatus]        │
    │    → checks each broker for paper/dry-run mode                       │
    │                                                                      │
    │  get_report() → dict                                                 │
    │    → full snapshot for dashboards / logging                           │
    └──────────────────────────────────────────────────────────────────────┘

Flask routes (registered via ``register_capital_concentration_routes(app)``):
    GET /api/v1/capital-concentration/dashboard   – full snapshot
    GET /api/v1/capital-concentration/ranking     – ranked account list
    GET /api/v1/capital-concentration/multipliers – per-account multipliers
    GET /api/v1/capital-concentration/live-status – live-execution verification
    GET /api/v1/capital-concentration/health      – engine health check

Usage
-----
::

    from bot.capital_concentration_engine import get_capital_concentration_engine

    engine = get_capital_concentration_engine()

    # After every closed trade:
    engine.record_trade("coinbase", pnl_usd=42.0, is_win=True, equity_usd=10_500.0)

    # Before sizing a new position:
    multiplier = engine.get_concentration_multiplier("coinbase")
    position_usd = base_usd * multiplier

    # Or use the all-in-one optimal sizer:
    position_usd = engine.get_optimal_position_usd("coinbase", balance_usd=10_500.0)

    # Route new trades to best accounts:
    top = engine.get_top_accounts(n=2)   # ["coinbase", "kraken"]

    # Verify live execution before deploying capital:
    statuses = engine.verify_live_execution({"coinbase": broker_obj})

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("nija.capital_concentration")

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

WIN_RATE_WINDOW = 20            # rolling trades used for win-rate calculation
WIN_RATE_THRESHOLD = 0.70       # 70 % triggers Capital Concentration Mode
MAX_CONCENTRATION_BOOST = 1.50  # max size multiplier when hot  (+50 %)
MIN_TRADES_FOR_ACTIVATION = 5   # trades needed before concentration is active

KILL_DRAWDOWN_THRESHOLD = 0.10  # 10 % drawdown begins allocation reduction
KILL_DRAWDOWN_FLOOR = 0.20      # 20 % drawdown → allocation fully zeroed

HALF_KELLY_FRACTION = 0.50      # safety fraction applied on top of Kelly formula
MIN_KELLY_POSITION_PCT = 0.005  # floor: 0.5 % of balance
MAX_KELLY_POSITION_PCT = 0.10   # ceiling: 10 % of balance

_MIN_AVG_SIZE = 1e-6            # floor for EMA win/loss sizes to avoid division by zero


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class ConcentrationConfig:
    """Tunable parameters for the Capital Concentration Engine."""
    win_rate_window: int = WIN_RATE_WINDOW
    win_rate_threshold: float = WIN_RATE_THRESHOLD
    max_concentration_boost: float = MAX_CONCENTRATION_BOOST
    min_trades_for_activation: int = MIN_TRADES_FOR_ACTIVATION
    kill_drawdown_threshold: float = KILL_DRAWDOWN_THRESHOLD
    kill_drawdown_floor: float = KILL_DRAWDOWN_FLOOR
    half_kelly_fraction: float = HALF_KELLY_FRACTION
    min_kelly_position_pct: float = MIN_KELLY_POSITION_PCT
    max_kelly_position_pct: float = MAX_KELLY_POSITION_PCT


# ---------------------------------------------------------------------------
# LiveStatus
# ---------------------------------------------------------------------------

class ExecutionMode(str, Enum):
    LIVE = "LIVE"
    PAPER = "PAPER"
    UNKNOWN = "UNKNOWN"


@dataclass
class LiveStatus:
    """Result of the live-execution verification check for one account."""
    account_id: str
    mode: ExecutionMode
    is_live: bool
    details: str
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        return {
            "account_id": self.account_id,
            "mode": self.mode.value,
            "is_live": self.is_live,
            "details": self.details,
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# AccountRank
# ---------------------------------------------------------------------------

@dataclass
class AccountRank:
    """Ranking entry returned by ``get_ranked_accounts``."""
    rank: int
    account_id: str
    net_pnl_usd: float
    rolling_win_rate_pct: float
    current_drawdown_pct: float
    allocation_multiplier: float
    mode: str                   # "HOT 🔥" | "KILLED ☠️" | "NORMAL"
    total_trades: int

    def to_dict(self) -> Dict:
        return {
            "rank": self.rank,
            "account_id": self.account_id,
            "net_pnl_usd": self.net_pnl_usd,
            "rolling_win_rate_pct": self.rolling_win_rate_pct,
            "current_drawdown_pct": self.current_drawdown_pct,
            "allocation_multiplier": self.allocation_multiplier,
            "mode": self.mode,
            "total_trades": self.total_trades,
        }


# ---------------------------------------------------------------------------
# Per-account internal state
# ---------------------------------------------------------------------------

@dataclass
class _AccountState:
    """Internal rolling state tracked for each account."""
    account_id: str
    net_pnl_usd: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    current_drawdown_pct: float = 0.0
    allocation_multiplier: float = 1.0
    # Rolling window of win/loss outcomes (bool)
    _win_window: Deque[bool] = field(
        default_factory=lambda: deque(maxlen=WIN_RATE_WINDOW)
    )
    # EMA-based win/loss sizes for Kelly calculation
    _ema_win_size: float = 1.0    # avg win as fraction of position
    _ema_loss_size: float = 1.0   # avg loss as fraction of position
    _ema_alpha: float = 0.20      # EMA smoothing factor
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def rolling_win_rate(self) -> float:
        if not self._win_window:
            return 0.0
        return sum(self._win_window) / len(self._win_window)

    @property
    def total_trades(self) -> int:
        return len(self._win_window)

    def update_kelly_stats(self, pnl_usd: float, is_win: bool, position_usd: float) -> None:
        """Update EMA win/loss sizes used for Kelly calculation."""
        if position_usd <= 0:
            return
        size = abs(pnl_usd) / position_usd
        if is_win:
            self._ema_win_size = (
                self._ema_alpha * size + (1 - self._ema_alpha) * self._ema_win_size
            )
        else:
            self._ema_loss_size = (
                self._ema_alpha * size + (1 - self._ema_alpha) * self._ema_loss_size
            )


# ---------------------------------------------------------------------------
# CapitalConcentrationEngine
# ---------------------------------------------------------------------------

class CapitalConcentrationEngine:
    """
    Unified capital-routing engine that:

    - Boosts allocation to hot accounts (win_rate > 70 %).
    - Reduces / kills allocation to drawdown-stressed accounts (DD > 10 %).
    - Ranks all accounts by P&L for trade routing.
    - Verifies each account is in live (not paper) mode.
    - Computes growth-optimal (half-Kelly) position sizes.
    - Exposes a Flask dashboard for real-time monitoring.
    """

    def __init__(self, config: Optional[ConcentrationConfig] = None) -> None:
        self._config = config or ConcentrationConfig()
        self._accounts: Dict[str, _AccountState] = {}
        self._lock = threading.Lock()

    def _get_or_create_state(self, account_id: str) -> _AccountState:
        """Return (or create) the ``_AccountState`` for *account_id*.

        Must be called under ``self._lock``.  Ensures the rolling win-rate
        window respects the currently configured ``win_rate_window`` size.
        """
        if account_id not in self._accounts:
            state = _AccountState(account_id=account_id)
            # Override the default-factory deque with the config-aware window size
            state._win_window = deque(maxlen=self._config.win_rate_window)
            self._accounts[account_id] = state
        return self._accounts[account_id]

    def get_account_ids(self) -> List[str]:
        """Return the list of account_ids currently tracked by the engine."""
        with self._lock:
            return list(self._accounts.keys())

    # ── Trade recording ───────────────────────────────────────────────────────

    def record_trade(
        self,
        account_id: str,
        pnl_usd: float,
        is_win: bool,
        equity_usd: Optional[float] = None,
        position_usd: Optional[float] = None,
    ) -> None:
        """
        Record a closed trade and update concentration state for *account_id*.

        Args:
            account_id:   Broker / account identifier (e.g. ``"coinbase"``).
            pnl_usd:      Net P&L of the closed trade in USD.
            is_win:       True if the trade was profitable.
            equity_usd:   Current total account equity (optional, for drawdown).
            position_usd: Size of the closed trade in USD (optional, for Kelly).
        """
        with self._lock:
            state = self._get_or_create_state(account_id)
            state.net_pnl_usd += pnl_usd
            state._win_window.append(is_win)

            if position_usd:
                state.update_kelly_stats(pnl_usd, is_win, position_usd)

            if equity_usd is not None:
                self._refresh_equity(state, equity_usd)

            state.allocation_multiplier = self._compute_multiplier(state)
            state.last_updated = datetime.now(timezone.utc).isoformat()

        logger.debug(
            "[CCEngine] %s trade recorded pnl=%.2f win=%s multiplier=%.2f",
            account_id, pnl_usd, is_win, state.allocation_multiplier,
        )

    def update_equity(self, account_id: str, equity_usd: float) -> None:
        """Refresh equity / drawdown for *account_id* without recording a trade."""
        with self._lock:
            state = self._get_or_create_state(account_id)
            self._refresh_equity(state, equity_usd)
            state.allocation_multiplier = self._compute_multiplier(state)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _refresh_equity(state: _AccountState, equity_usd: float) -> None:
        state.current_equity = equity_usd
        if equity_usd > state.peak_equity:
            state.peak_equity = equity_usd
        if state.peak_equity > 0:
            state.current_drawdown_pct = (
                (state.peak_equity - equity_usd) / state.peak_equity * 100.0
            )

    def _compute_multiplier(self, state: _AccountState) -> float:
        """
        Compute the allocation multiplier for *state*.

        Priority:
        1. Kill Weak Accounts  — drawdown ≥ threshold → linear decay to 0.
        2. Capital Concentration — enough trades + win_rate > threshold → boost.
        3. Default 1.0.
        """
        cfg = self._config
        dd_fraction = state.current_drawdown_pct / 100.0

        # ── Rule 1: Kill weak accounts ────────────────────────────────────────
        if dd_fraction >= cfg.kill_drawdown_threshold:
            band = cfg.kill_drawdown_floor - cfg.kill_drawdown_threshold
            if band <= 0:
                return 0.0
            excess = dd_fraction - cfg.kill_drawdown_threshold
            decay = min(excess / band, 1.0)
            return round(max(1.0 - decay, 0.0), 4)

        # ── Rule 2: Capital concentration boost ───────────────────────────────
        if state.total_trades >= cfg.min_trades_for_activation:
            wr = state.rolling_win_rate
            if wr > cfg.win_rate_threshold:
                max_excess = 1.0 - cfg.win_rate_threshold
                boost_fraction = (
                    (wr - cfg.win_rate_threshold) / max_excess
                    if max_excess > 0 else 1.0
                )
                boost = 1.0 + (cfg.max_concentration_boost - 1.0) * boost_fraction
                return round(min(boost, cfg.max_concentration_boost), 4)

        return 1.0

    # ── Feature 1 & 3: Multiplier access ─────────────────────────────────────

    def get_concentration_multiplier(self, account_id: str) -> float:
        """
        Return the current allocation multiplier for *account_id*.

        - ``> 1.0`` → Capital Concentration Mode active (hot account).
        - ``1.0``   → Normal.
        - ``< 1.0`` → Drawdown reduction (Kill Weak Accounts).
        - ``0.0``   → Fully killed; no new capital should be sent here.
        """
        with self._lock:
            state = self._accounts.get(account_id)
            return state.allocation_multiplier if state else 1.0

    def is_hot(self, account_id: str) -> bool:
        """True when *account_id* is in Capital Concentration Mode."""
        return self.get_concentration_multiplier(account_id) > 1.0

    def is_killed(self, account_id: str) -> bool:
        """True when *account_id*'s allocation has been cut due to drawdown."""
        return self.get_concentration_multiplier(account_id) < 1.0

    # ── Feature 2: Account Performance Ranking ────────────────────────────────

    def get_ranked_accounts(self) -> List[AccountRank]:
        """
        Return all accounts sorted by net P&L (best first).

        Each entry includes P&L, win rate, drawdown, multiplier, and mode label.
        """
        with self._lock:
            sorted_states = sorted(
                self._accounts.values(),
                key=lambda s: s.net_pnl_usd,
                reverse=True,
            )
            result: List[AccountRank] = []
            for i, state in enumerate(sorted_states, start=1):
                m = state.allocation_multiplier
                mode = (
                    "HOT 🔥" if m > 1.0
                    else "KILLED ☠️" if m < 1.0
                    else "NORMAL"
                )
                result.append(AccountRank(
                    rank=i,
                    account_id=state.account_id,
                    net_pnl_usd=round(state.net_pnl_usd, 4),
                    rolling_win_rate_pct=round(state.rolling_win_rate * 100, 2),
                    current_drawdown_pct=round(state.current_drawdown_pct, 2),
                    allocation_multiplier=m,
                    mode=mode,
                    total_trades=state.total_trades,
                ))
            return result

    def get_top_accounts(self, n: int = 3) -> List[str]:
        """Return the account_ids of the top *n* performers by P&L."""
        return [r.account_id for r in self.get_ranked_accounts()[:n]]

    # ── Feature 4: Multi-account live execution verifier ─────────────────────

    def verify_live_execution(
        self, brokers: Dict[str, Any]
    ) -> Dict[str, LiveStatus]:
        """
        Verify that each broker account in *brokers* is executing live trades
        (not in paper-trading or dry-run mode).

        Args:
            brokers: ``{account_id: broker_object}`` mapping.  The broker object
                     is inspected for common paper-trading flags.

        Returns:
            ``{account_id: LiveStatus}`` — one entry per broker.
        """
        results: Dict[str, LiveStatus] = {}
        for account_id, broker in brokers.items():
            results[account_id] = self._check_broker_live(account_id, broker)
        return results

    @staticmethod
    def _check_broker_live(account_id: str, broker: Any) -> LiveStatus:
        """Inspect *broker* for paper/dry-run mode indicators."""
        # Attributes that signal paper / simulation mode when truthy
        paper_flags = (
            "paper_trading",
            "is_paper",
            "dry_run",
            "simulation_mode",
            "test_mode",
            "sandbox",
            "is_sandbox",
            "demo_mode",
        )
        # Attributes that confirm live mode when truthy
        live_flags = (
            "is_live",
            "live_trading",
            "live_mode",
        )

        if broker is None:
            return LiveStatus(
                account_id=account_id,
                mode=ExecutionMode.UNKNOWN,
                is_live=False,
                details="Broker object is None — cannot verify.",
            )

        for flag in paper_flags:
            val = getattr(broker, flag, None)
            if val:
                return LiveStatus(
                    account_id=account_id,
                    mode=ExecutionMode.PAPER,
                    is_live=False,
                    details=f"Broker attribute '{flag}' is truthy ({val!r}) — PAPER mode detected.",
                )

        for flag in live_flags:
            val = getattr(broker, flag, None)
            if val:
                return LiveStatus(
                    account_id=account_id,
                    mode=ExecutionMode.LIVE,
                    is_live=True,
                    details=f"Broker attribute '{flag}' is truthy ({val!r}) — LIVE confirmed.",
                )

        # Fall back: if the broker has an API key set and no paper flag, assume live
        has_key = bool(
            getattr(broker, "api_key", None)
            or getattr(broker, "_api_key", None)
            or getattr(broker, "key", None)
        )
        if has_key:
            return LiveStatus(
                account_id=account_id,
                mode=ExecutionMode.LIVE,
                is_live=True,
                details="API key present and no paper-trading flags detected — presumed LIVE.",
            )

        return LiveStatus(
            account_id=account_id,
            mode=ExecutionMode.UNKNOWN,
            is_live=False,
            details="No paper or live flags found; no API key detected — status UNKNOWN.",
        )

    # ── Feature 5: Growth-optimised (half-Kelly) position sizing ──────────────

    def get_optimal_position_usd(
        self,
        account_id: str,
        balance_usd: float,
        base_risk_pct: float = 0.02,
    ) -> float:
        """
        Return the growth-optimal position size in USD for *account_id*.

        The size is computed as:
            1. Half-Kelly fraction based on rolling win-rate and avg win/loss.
            2. Clamped to ``[min_kelly_pct, max_kelly_pct]`` of *balance_usd*.
            3. Multiplied by the concentration multiplier (boost hot / shrink weak).

        Args:
            account_id:    Account to size for.
            balance_usd:   Current account balance in USD.
            base_risk_pct: Fallback risk fraction when Kelly cannot be computed.

        Returns:
            Recommended position size in USD.
        """
        cfg = self._config
        with self._lock:
            state = self._accounts.get(account_id)

        if balance_usd <= 0:
            return 0.0

        if state is None or state.total_trades < cfg.min_trades_for_activation:
            # Not enough history — use the base risk pct as the position size
            raw_pct = base_risk_pct
        else:
            win_rate = state.rolling_win_rate
            avg_win = max(state._ema_win_size, _MIN_AVG_SIZE)
            avg_loss = max(state._ema_loss_size, _MIN_AVG_SIZE)

            # Kelly formula: f* = (W*b - L) / b  where b = avg_win/avg_loss
            b = avg_win / avg_loss
            f_star = max(0.0, (win_rate * b - (1.0 - win_rate)) / b)
            raw_pct = f_star * cfg.half_kelly_fraction

        clamped_pct = max(
            cfg.min_kelly_position_pct,
            min(raw_pct, cfg.max_kelly_position_pct),
        )

        multiplier = (
            state.allocation_multiplier
            if state is not None
            else 1.0
        )
        position_usd = balance_usd * clamped_pct * multiplier
        return round(position_usd, 4)

    # ── Full report ───────────────────────────────────────────────────────────

    def get_report(self) -> Dict:
        """Return a full snapshot suitable for dashboards and logging."""
        ranked = self.get_ranked_accounts()
        with self._lock:
            hot = [r.account_id for r in ranked if r.allocation_multiplier > 1.0]
            killed = [r.account_id for r in ranked if r.allocation_multiplier < 1.0]
        return {
            "accounts": [r.to_dict() for r in ranked],
            "summary": {
                "total_accounts": len(ranked),
                "hot_accounts": hot,
                "killed_accounts": killed,
                "top_account": ranked[0].account_id if ranked else None,
            },
            "config": {
                "win_rate_threshold_pct": self._config.win_rate_threshold * 100,
                "max_concentration_boost": self._config.max_concentration_boost,
                "kill_drawdown_threshold_pct": self._config.kill_drawdown_threshold * 100,
                "kill_drawdown_floor_pct": self._config.kill_drawdown_floor * 100,
                "half_kelly_fraction": self._config.half_kelly_fraction,
                "win_rate_window": self._config.win_rate_window,
                "min_trades_for_activation": self._config.min_trades_for_activation,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_ENGINE: Optional[CapitalConcentrationEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_capital_concentration_engine(
    config: Optional[ConcentrationConfig] = None,
) -> CapitalConcentrationEngine:
    """Return the process-wide ``CapitalConcentrationEngine`` singleton."""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = CapitalConcentrationEngine(config=config)
            logger.info(
                "[CCEngine] singleton created "
                "(win_rate_threshold=%.0f%%, kill_drawdown=%.0f%%, max_boost=%.1fx) — "
                "concentration + ranking + kill-weak + live-verify + Kelly + dashboard active",
                WIN_RATE_THRESHOLD * 100,
                KILL_DRAWDOWN_THRESHOLD * 100,
                MAX_CONCENTRATION_BOOST,
            )
    return _ENGINE


# ---------------------------------------------------------------------------
# Feature 6: Flask dashboard routes
# ---------------------------------------------------------------------------

def register_capital_concentration_routes(app: Any) -> None:
    """
    Register real-time capital concentration REST endpoints on a Flask *app*.

    Endpoints
    ---------
    GET /api/v1/capital-concentration/dashboard   – full real-time snapshot
    GET /api/v1/capital-concentration/ranking     – accounts ranked by P&L
    GET /api/v1/capital-concentration/multipliers – per-account multipliers
    GET /api/v1/capital-concentration/live-status – live-execution verification
    GET /api/v1/capital-concentration/health      – engine health check

    Args:
        app: A Flask application instance.
    """
    try:
        from flask import jsonify
    except ImportError:
        logger.warning("[CCEngine] Flask not available — dashboard routes not registered")
        return

    engine = get_capital_concentration_engine()

    @app.route("/api/v1/capital-concentration/dashboard", methods=["GET"])
    def cc_dashboard():
        """Full real-time capital concentration snapshot."""
        try:
            return jsonify({"success": True, "data": engine.get_report()})
        except Exception as exc:
            logger.error("[CCEngine] dashboard endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/v1/capital-concentration/ranking", methods=["GET"])
    def cc_ranking():
        """Accounts ranked by net P&L (best first)."""
        try:
            ranked = [r.to_dict() for r in engine.get_ranked_accounts()]
            return jsonify({"success": True, "data": ranked})
        except Exception as exc:
            logger.error("[CCEngine] ranking endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/v1/capital-concentration/multipliers", methods=["GET"])
    def cc_multipliers():
        """Per-account allocation multipliers."""
        try:
            report = engine.get_report()
            multipliers = {
                a["account_id"]: {
                    "multiplier": a["allocation_multiplier"],
                    "mode": a["mode"],
                }
                for a in report["accounts"]
            }
            return jsonify({"success": True, "data": multipliers})
        except Exception as exc:
            logger.error("[CCEngine] multipliers endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/v1/capital-concentration/live-status", methods=["GET"])
    def cc_live_status():
        """
        Multi-account live-execution verification.

        Inspects broker objects currently known to the running strategy.
        Falls back to reporting the engine's tracked accounts if no broker
        objects can be retrieved.
        """
        try:
            import sys
            brokers: Dict[str, Any] = {}

            # Attempt to pull live broker objects from the running strategy
            strategy_mod = sys.modules.get("trading_strategy") or sys.modules.get("bot.trading_strategy")
            if strategy_mod is not None:
                strategy = getattr(strategy_mod, "_strategy_instance", None)
                if strategy is not None and hasattr(strategy, "broker") and strategy.broker:
                    broker_id = getattr(strategy.broker, "broker_type", "primary")
                    brokers[str(broker_id)] = strategy.broker

            if not brokers:
                # Build synthetic entries for tracked accounts (no broker object)
                for aid in engine.get_account_ids():
                    brokers[aid] = None

            statuses = engine.verify_live_execution(brokers)
            return jsonify({
                "success": True,
                "data": {k: v.to_dict() for k, v in statuses.items()},
            })
        except Exception as exc:
            logger.error("[CCEngine] live-status endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @app.route("/api/v1/capital-concentration/health", methods=["GET"])
    def cc_health():
        """Engine health check."""
        try:
            report = engine.get_report()
            return jsonify({
                "success": True,
                "status": "healthy",
                "tracked_accounts": report["summary"]["total_accounts"],
                "hot_accounts": report["summary"]["hot_accounts"],
                "killed_accounts": report["summary"]["killed_accounts"],
                "generated_at": report["generated_at"],
            })
        except Exception as exc:
            logger.error("[CCEngine] health endpoint error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    logger.info(
        "[CCEngine] ✅ Flask routes registered — "
        "/api/v1/capital-concentration/{dashboard,ranking,multipliers,live-status,health}"
    )
