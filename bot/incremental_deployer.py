"""
Incremental Capital Deployer

Manages phased live deployment of real capital, graduating through
risk tiers as performance criteria are met:

  Phase 0 – PAPER   (0 % of target capital – simulation only)
  Phase 1 – MICRO   (1 % of target capital)
  Phase 2 – SMALL   (5 % of target capital)
  Phase 3 – MEDIUM  (15% of target capital)
  Phase 4 – FULL    (40% of target capital)

Advancement criteria (all must be satisfied to advance):
  • win_rate     ≥ phase threshold  (default 55 / 58 / 62 / 65 %)
  • profit_factor ≥ phase threshold  (default 1.3 / 1.5 / 1.8 / 2.0)
  • max_drawdown  ≤ phase limit      (default 8 / 6 / 5 / 4 %)
  • min_trades   completed in phase  (default 20 / 30 / 50 / 100)

Regression demotion: if drawdown exceeds 1.5× the phase limit while
in a live phase the deployer drops back one phase automatically.

Persistence: phase state is stored in JSON so restarts resume the
same phase without resetting trade history.

Usage
-----
    from bot.incremental_deployer import get_incremental_deployer

    deployer = get_incremental_deployer(target_capital=50_000)
    info      = deployer.deployment_info()
    allocated = deployer.allocated_capital(total_balance=50_000)
    deployer.record_trade(pnl=120.0, won=True, drawdown_pct=2.1)
    deployer.maybe_advance()
NIJA Incremental Live Deployer

Manages the phased transition from paper trading to live trading with real
capital, following a conservative risk budget:

Phase 0 — Paper Only    (0 % real capital)
Phase 1 — Micro Live    (1 % of total risk budget)
Phase 2 — Small Live    (5 % of total risk budget)
Phase 3 — Medium Live   (15 % of total risk budget)
Phase 4 — Full Live     (40 % of total risk budget)

Progression is gated by hard criteria evaluated over a configurable
evaluation window:
- Minimum number of live trades completed
- Win rate ≥ threshold
- Profit factor ≥ threshold
- Maximum drawdown ≤ threshold
- No active kill-switch events

Every trade is audited in ``trade_ledger`` and outcomes are fed back into
the AdaptiveLearningLoop / RLFeedbackAdapter via callbacks.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.incremental_deployer")

# ─────────────────────────────────────────────────────────────────────────────
# Phase definitions
# ─────────────────────────────────────────────────────────────────────────────

class DeploymentPhase(str, Enum):
    PAPER  = "PAPER"
    MICRO  = "MICRO"
    SMALL  = "SMALL"
    MEDIUM = "MEDIUM"
    FULL   = "FULL"

_PHASE_ORDER: List[DeploymentPhase] = [
    DeploymentPhase.PAPER,
    DeploymentPhase.MICRO,
    DeploymentPhase.SMALL,
    DeploymentPhase.MEDIUM,
    DeploymentPhase.FULL,
]


@dataclass
class PhaseConfig:
    """Criteria that must be met to *stay in* or *advance from* this phase."""
    allocation_pct:    float   # fraction of target capital to deploy
    min_win_rate:      float   # minimum win-rate to advance
    min_profit_factor: float   # minimum profit-factor to advance
    max_drawdown_pct:  float   # maximum drawdown allowed in phase
    min_trades:        int     # minimum trade count before advance is evaluated


_DEFAULT_PHASE_CONFIG: Dict[DeploymentPhase, PhaseConfig] = {
    DeploymentPhase.PAPER:  PhaseConfig(0.00, 0.55, 1.30, 8.0, 20),
    DeploymentPhase.MICRO:  PhaseConfig(0.01, 0.58, 1.50, 6.0, 30),
    DeploymentPhase.SMALL:  PhaseConfig(0.05, 0.62, 1.80, 5.0, 50),
    DeploymentPhase.MEDIUM: PhaseConfig(0.15, 0.65, 2.00, 4.0, 100),
    DeploymentPhase.FULL:   PhaseConfig(0.40, 0.70, 2.20, 3.0, 200),
}

# Regression multiplier: drop one phase if drawdown > limit × factor
_REGRESSION_FACTOR = 1.5


# ─────────────────────────────────────────────────────────────────────────────
# Phase statistics tracking
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PhaseStats:
    phase: str = DeploymentPhase.PAPER.value
    trades: int = 0
    wins: int = 0
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.incremental_deployer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DATA_PATH: str = "deployer_state.json"

# Minimum evaluation period per phase (number of live trades)
MIN_TRADES_PER_PHASE: Dict[str, int] = {
    "MICRO": 20,
    "SMALL": 50,
    "MEDIUM": 100,
    "FULL": 200,
}

# Gating criteria for advancing to the next phase
PHASE_ADVANCE_CRITERIA: Dict[str, Dict] = {
    "MICRO": {"min_win_rate": 0.45, "min_profit_factor": 1.1, "max_drawdown": 0.10},
    "SMALL": {"min_win_rate": 0.48, "min_profit_factor": 1.2, "max_drawdown": 0.12},
    "MEDIUM": {"min_win_rate": 0.50, "min_profit_factor": 1.3, "max_drawdown": 0.15},
    "FULL":   {"min_win_rate": 0.52, "min_profit_factor": 1.5, "max_drawdown": 0.20},
}


# ---------------------------------------------------------------------------
# Enums and data classes
# ---------------------------------------------------------------------------

class DeployPhase(str, Enum):
    PAPER = "PAPER"
    MICRO = "MICRO"      # 1 %
    SMALL = "SMALL"      # 5 %
    MEDIUM = "MEDIUM"    # 15 %
    FULL = "FULL"        # 40 %

    @property
    def capital_fraction(self) -> float:
        return {
            "PAPER": 0.00,
            "MICRO": 0.01,
            "SMALL": 0.05,
            "MEDIUM": 0.15,
            "FULL": 0.40,
        }[self.value]

    def next_phase(self) -> Optional["DeployPhase"]:
        order = [DeployPhase.PAPER, DeployPhase.MICRO, DeployPhase.SMALL,
                 DeployPhase.MEDIUM, DeployPhase.FULL]
        idx = order.index(self)
        return order[idx + 1] if idx + 1 < len(order) else None


@dataclass
class LiveTradeAudit:
    """Immutable audit record for a single live trade."""
    trade_id: str
    phase: str
    symbol: str
    side: str
    size_usd: float
    entry_price: float
    exit_price: float
    pnl_usd: float
    return_pct: float
    is_win: bool
    strategy: str
    venue: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    notes: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PhaseStats:
    """Running statistics for one deployment phase."""
    phase: str
    trade_count: int = 0
    win_count: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    max_drawdown_pct: float = 0.0
    started_at: str = ""
    advanced_at: str = ""

    # ── derived ──────────────────────────────────────────────────────────────
    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        return (self.gross_profit / self.gross_loss
                if self.gross_loss > 0 else float("inf"))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["win_rate"] = self.win_rate
        d["profit_factor"] = self.profit_factor if self.profit_factor != float("inf") else 99.0
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class IncrementalDeployer:
    """
    Phased capital deployment controller.

    Parameters
    ----------
    target_capital : float
        Full target capital amount.  Allocated amounts are fractions
        of this value per phase.
    state_path : str
        JSON file that persists phase progress across restarts.
    phase_configs : dict, optional
        Override any PhaseConfig entries.
    trough_equity: float = 0.0
    start_equity: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gross_profit / max(self.gross_loss, 1e-9)

    @property
    def max_drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.trough_equity) / self.peak_equity

    def to_dict(self) -> Dict:
        return {
            "phase": self.phase,
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "win_rate": round(self.win_rate, 4),
            "total_pnl": round(self.total_pnl, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown": round(self.max_drawdown, 4),
        }


@dataclass
class DeployerState:
    """Persistent state of the incremental deployer."""
    current_phase: str = DeployPhase.PAPER.value
    total_live_trades: int = 0
    phase_stats: Dict[str, Dict] = field(default_factory=dict)
    phase_history: List[Dict] = field(default_factory=list)  # phase transition log
    kill_switch_active: bool = False
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ---------------------------------------------------------------------------
# Main deployer class
# ---------------------------------------------------------------------------

class IncrementalDeployer:
    """
    Manages phased live-capital deployment for NIJA.

    Parameters
    ----------
    total_risk_budget : float
        Total capital NIJA may risk across all strategies (in USD).
    data_path : str
        Path to JSON file for persistent state.
    on_phase_advance : Callable | None
        Optional callback invoked when a phase advance occurs.
        Signature: ``(old_phase: DeployPhase, new_phase: DeployPhase) -> None``
    on_trade_feedback : Callable | None
        Optional callback for each trade audit (feeds RL / adaptive loops).
        Signature: ``(audit: LiveTradeAudit) -> None``
    """

    def __init__(
        self,
        target_capital: float = 10_000.0,
        state_path: str = "data/incremental_deployer_state.json",
        phase_configs: Optional[Dict[DeploymentPhase, PhaseConfig]] = None,
    ) -> None:
        self.target_capital = max(1.0, target_capital)
        self.state_path     = state_path
        self._lock          = threading.RLock()

        # Merge caller overrides with defaults
        self._configs = dict(_DEFAULT_PHASE_CONFIG)
        if phase_configs:
            self._configs.update(phase_configs)

        self._phase: DeploymentPhase = DeploymentPhase.PAPER
        self._stats: PhaseStats = PhaseStats(
            phase=DeploymentPhase.PAPER.value,
            started_at=_now(),
        )
        self._history: List[Dict[str, Any]] = []

        self._load_state()
        logger.info(
            "📈 IncrementalDeployer ready | phase=%s | target_capital=$%.2f",
            self._phase.value, self.target_capital,
        )

    # ── public interface ──────────────────────────────────────────────────────

    @property
    def current_phase(self) -> DeploymentPhase:
        with self._lock:
            return self._phase

    @property
    def is_live(self) -> bool:
        """True when any real capital is allocated (not PAPER)."""
        return self.current_phase != DeploymentPhase.PAPER

    def allocated_capital(self, total_balance: Optional[float] = None) -> float:
        """Return the dollar amount allocated under the current phase."""
        with self._lock:
            base = total_balance if total_balance is not None else self.target_capital
            return base * self._configs[self._phase].allocation_pct

    def deployment_info(self) -> Dict[str, Any]:
        """Return a full status snapshot suitable for dashboards."""
        with self._lock:
            cfg   = self._configs[self._phase]
            stats = self._stats.to_dict()
            idx   = _PHASE_ORDER.index(self._phase)
            next_phase = (_PHASE_ORDER[idx + 1].value
                          if idx + 1 < len(_PHASE_ORDER) else "FULL (max)")
            return {
                "phase":              self._phase.value,
                "next_phase":         next_phase,
                "allocation_pct":     cfg.allocation_pct * 100,
                "allocated_capital":  self.allocated_capital(),
                "target_capital":     self.target_capital,
                "phase_stats":        stats,
                "advance_criteria": {
                    "min_win_rate":      cfg.min_win_rate,
                    "min_profit_factor": cfg.min_profit_factor,
                    "max_drawdown_pct":  cfg.max_drawdown_pct,
                    "min_trades":        cfg.min_trades,
                },
                "is_live": self.is_live,
            }

    def record_trade(
        self,
        pnl: float,
        won: bool,
        drawdown_pct: float = 0.0,
        equity: Optional[float] = None,
    ) -> None:
        """
        Record a completed trade outcome and update running statistics.

        Parameters
        ----------
        pnl           : trade P&L in dollars (positive = profit).
        won           : True if the trade was profitable.
        drawdown_pct  : current portfolio drawdown percentage (0-100).
        equity        : current portfolio equity (used to track peak/drawdown).
        """
        with self._lock:
            s = self._stats
            s.trades     += 1
            s.wins       += int(won)
            s.total_pnl  += pnl
            if pnl > 0:
                s.gross_profit += pnl
            else:
                s.gross_loss   += abs(pnl)

            if equity is not None:
                if equity > s.peak_equity:
                    s.peak_equity = equity
                s.current_equity = equity
                if s.peak_equity > 0:
                    dd = (s.peak_equity - equity) / s.peak_equity * 100
                    if dd > s.max_drawdown_pct:
                        s.max_drawdown_pct = dd
            else:
                if drawdown_pct > s.max_drawdown_pct:
                    s.max_drawdown_pct = drawdown_pct

            self._save_state()

        # Check regression trigger on every trade
        self._maybe_regress()

    def maybe_advance(self) -> bool:
        """
        Evaluate advancement criteria and advance one phase if all are met.

        Returns True if the phase was advanced.
        """
        with self._lock:
            if self._phase == DeploymentPhase.FULL:
                return False   # already at maximum deployment

            cfg   = self._configs[self._phase]
            s     = self._stats

            if s.trades < cfg.min_trades:
                logger.debug(
                    "[Deployer] Advance denied: trades=%d < min=%d",
                    s.trades, cfg.min_trades,
                )
                return False

            criteria_met = (
                s.win_rate      >= cfg.min_win_rate
                and s.profit_factor >= cfg.min_profit_factor
                and s.max_drawdown_pct <= cfg.max_drawdown_pct
            )

            if not criteria_met:
                logger.info(
                    "[Deployer] Advance criteria not met | "
                    "wr=%.1f%% (need %.1f%%) | pf=%.2f (need %.2f) | "
                    "dd=%.1f%% (max %.1f%%)",
                    s.win_rate * 100, cfg.min_win_rate * 100,
                    s.profit_factor, cfg.min_profit_factor,
                    s.max_drawdown_pct, cfg.max_drawdown_pct,
                )
                return False

            return self._advance_phase()

    def force_phase(self, phase: DeploymentPhase) -> None:
        """Override the current phase (admin/testing use only)."""
        with self._lock:
            old = self._phase
            self._phase = phase
            self._reset_stats(phase)
            logger.warning(
                "⚠️  [Deployer] Phase forced: %s → %s", old.value, phase.value
            )
            self._save_state()

    # ── internal helpers ─────────────────────────────────────────────────────

    def _advance_phase(self) -> bool:
        """Promote to the next phase.  Caller must hold self._lock."""
        idx = _PHASE_ORDER.index(self._phase)
        if idx + 1 >= len(_PHASE_ORDER):
            return False

        old_phase = self._phase
        new_phase = _PHASE_ORDER[idx + 1]

        # Archive outgoing stats
        archived = self._stats.to_dict()
        archived["advanced_at"] = _now()
        self._history.append(archived)

        self._phase = new_phase
        self._reset_stats(new_phase)

        logger.info(
            "🚀 [Deployer] PHASE ADVANCE: %s → %s | "
            "allocation %.0f%% → %.0f%%",
            old_phase.value, new_phase.value,
            self._configs[old_phase].allocation_pct * 100,
            self._configs[new_phase].allocation_pct * 100,
        )
        self._save_state()
        return True

    def _maybe_regress(self) -> None:
        """Drop one phase if drawdown exceeds regression threshold."""
        with self._lock:
            if self._phase == DeploymentPhase.PAPER:
                return

            cfg = self._configs[self._phase]
            s   = self._stats
            limit = cfg.max_drawdown_pct * _REGRESSION_FACTOR

            if s.max_drawdown_pct > limit:
                idx = _PHASE_ORDER.index(self._phase)
                if idx == 0:
                    return
                new_phase = _PHASE_ORDER[idx - 1]
                logger.warning(
                    "🔴 [Deployer] REGRESSION: %s → %s "
                    "(drawdown %.1f%% > regression limit %.1f%%)",
                    self._phase.value, new_phase.value,
                    s.max_drawdown_pct, limit,
                )
                archived = self._stats.to_dict()
                archived["regressed_at"] = _now()
                self._history.append(archived)
                self._phase = new_phase
                self._reset_stats(new_phase)
                self._save_state()

    def _reset_stats(self, phase: DeploymentPhase) -> None:
        """Start fresh statistics for the given phase.  Caller must hold lock."""
        self._stats = PhaseStats(phase=phase.value, started_at=_now())

    def _load_state(self) -> None:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path) as fh:
                    data = json.load(fh)
                phase_val = data.get("phase", DeploymentPhase.PAPER.value)
                self._phase = DeploymentPhase(phase_val)
                stats_data  = data.get("stats", {})
                self._stats = PhaseStats(**{
                    k: v for k, v in stats_data.items()
                    if k in PhaseStats.__dataclass_fields__
                })
                self._history = data.get("history", [])
                logger.info(
                    "[Deployer] State restored | phase=%s | trades=%d",
                    self._phase.value, self._stats.trades,
                )
        except Exception as exc:
            logger.warning("[Deployer] Could not load state (%s) – starting fresh.", exc)

    def _save_state(self) -> None:
        """Persist phase state to disk.  Caller should hold lock."""
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "w") as fh:
                json.dump(
                    {
                        "phase":   self._phase.value,
                        "stats":   self._stats.to_dict(),
                        "history": self._history,
                        "saved_at": _now(),
                    },
                    fh,
                    indent=2,
                )
        except Exception as exc:
            logger.warning("[Deployer] Could not persist state: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────
        total_risk_budget: float = 10_000.0,
        data_path: str = DEFAULT_DATA_PATH,
        on_phase_advance: Optional[Callable] = None,
        on_trade_feedback: Optional[Callable] = None,
    ) -> None:
        self._lock = threading.RLock()
        self.total_risk_budget = total_risk_budget
        self._data_path = Path(data_path)
        self._on_phase_advance = on_phase_advance
        self._on_trade_feedback = on_trade_feedback

        # Phase stats objects
        self._phase_stats: Dict[str, PhaseStats] = {
            p.value: PhaseStats(phase=p.value) for p in DeployPhase
        }

        # Audit ledger (in-memory; also appended to disk)
        self._ledger: List[LiveTradeAudit] = []
        self._ledger_path = self._data_path.parent / "trade_ledger.jsonl"

        # Load or initialise state
        self._state = self._load_state()
        # Restore phase stats from saved state
        for phase_key, stats_dict in self._state.phase_stats.items():
            if phase_key in self._phase_stats:
                ps = self._phase_stats[phase_key]
                ps.trade_count = stats_dict.get("trade_count", 0)
                ps.win_count = stats_dict.get("win_count", 0)
                ps.total_pnl = stats_dict.get("total_pnl", 0.0)
                ps.gross_profit = stats_dict.get("gross_profit", 0.0)
                ps.gross_loss = stats_dict.get("gross_loss", 0.0)
                ps.peak_equity = stats_dict.get("peak_equity", 0.0)
                ps.trough_equity = stats_dict.get("trough_equity", 0.0)
                ps.start_equity = stats_dict.get("start_equity", 0.0)

        logger.info(
            "IncrementalDeployer initialised — phase=%s, risk_budget=$%.2f",
            self._state.current_phase, total_risk_budget,
        )

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> DeployerState:
        if self._data_path.exists():
            try:
                data = json.loads(self._data_path.read_text())
                return DeployerState(**data)
            except Exception as exc:
                logger.warning("Could not load deployer state: %s — starting fresh", exc)
        return DeployerState()

    def _save_state(self) -> None:
        state_dict = {
            "current_phase": self._state.current_phase,
            "total_live_trades": self._state.total_live_trades,
            "phase_stats": {k: v.to_dict() for k, v in self._phase_stats.items()},
            "phase_history": self._state.phase_history,
            "kill_switch_active": self._state.kill_switch_active,
            "last_updated": datetime.utcnow().isoformat(),
        }
        try:
            self._data_path.parent.mkdir(parents=True, exist_ok=True)
            self._data_path.write_text(json.dumps(state_dict, indent=2))
        except OSError as exc:
            logger.error("Could not save deployer state: %s", exc)

    # ------------------------------------------------------------------
    # Capital allocation
    # ------------------------------------------------------------------

    @property
    def current_phase(self) -> DeployPhase:
        with self._lock:
            return DeployPhase(self._state.current_phase)

    def get_live_capital(self) -> float:
        """Return the current live capital allocation in USD."""
        with self._lock:
            return self.total_risk_budget * self.current_phase.capital_fraction

    def get_position_size_usd(self, base_size_usd: float) -> float:
        """
        Scale a proposed position size by the current deployment fraction.

        In PAPER phase, returns 0 (no real capital).
        """
        fraction = self.current_phase.capital_fraction
        return base_size_usd * fraction

    # ------------------------------------------------------------------
    # Trade recording and audit
    # ------------------------------------------------------------------

    def record_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        size_usd: float,
        entry_price: float,
        exit_price: float,
        pnl_usd: float,
        strategy: str,
        venue: str,
        notes: str = "",
    ) -> LiveTradeAudit:
        """
        Record a completed live trade, update phase statistics, and optionally
        trigger a phase-advance evaluation.

        Returns the LiveTradeAudit for further processing.
        """
        with self._lock:
            return_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
            if side == "sell":
                return_pct = -return_pct

            is_win = pnl_usd > 0
            audit = LiveTradeAudit(
                trade_id=trade_id,
                phase=self._state.current_phase,
                symbol=symbol,
                side=side,
                size_usd=size_usd,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_usd=pnl_usd,
                return_pct=return_pct,
                is_win=is_win,
                strategy=strategy,
                venue=venue,
                notes=notes,
            )

            self._ledger.append(audit)
            self._append_to_ledger_file(audit)

            # Update phase stats
            ps = self._phase_stats[self._state.current_phase]
            ps.trade_count += 1
            if is_win:
                ps.win_count += 1
            ps.total_pnl += pnl_usd
            if pnl_usd > 0:
                ps.gross_profit += pnl_usd
            else:
                ps.gross_loss += abs(pnl_usd)

            self._state.total_live_trades += 1
            self._save_state()

        # Callbacks outside lock
        if self._on_trade_feedback:
            try:
                self._on_trade_feedback(audit)
            except Exception as exc:
                logger.error("Trade feedback callback error: %s", exc)

        # Evaluate phase advance
        self._evaluate_phase_advance()

        return audit

    def _append_to_ledger_file(self, audit: LiveTradeAudit) -> None:
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self._ledger_path.open("a") as fh:
                fh.write(json.dumps(audit.to_dict()) + "\n")
        except OSError as exc:
            logger.error("Could not write to trade ledger: %s", exc)

    # ------------------------------------------------------------------
    # Phase advancement
    # ------------------------------------------------------------------

    def _evaluate_phase_advance(self) -> None:
        """Check if current phase criteria are met and advance if so."""
        with self._lock:
            if self._state.kill_switch_active:
                return

            phase = self.current_phase
            if phase == DeployPhase.FULL:
                return  # already at maximum deployment

            next_phase = phase.next_phase()
            if next_phase is None:
                return

            ps = self._phase_stats[phase.value]
            criteria = PHASE_ADVANCE_CRITERIA.get(phase.value, {})
            min_trades = MIN_TRADES_PER_PHASE.get(phase.value, 999)

            if ps.trade_count < min_trades:
                return

            # Check gating criteria
            if (
                ps.win_rate >= criteria.get("min_win_rate", 0)
                and ps.profit_factor >= criteria.get("min_profit_factor", 0)
                and ps.max_drawdown <= criteria.get("max_drawdown", 1)
            ):
                old_phase = phase
                self._state.current_phase = next_phase.value
                self._state.phase_history.append({
                    "from": old_phase.value,
                    "to": next_phase.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "trade_count": ps.trade_count,
                    "win_rate": round(ps.win_rate, 4),
                    "profit_factor": round(ps.profit_factor, 4),
                    "max_drawdown": round(ps.max_drawdown, 4),
                })
                self._save_state()
                logger.info(
                    "🚀 Phase advance: %s → %s (win_rate=%.1f%%, pf=%.2f, dd=%.1f%%)",
                    old_phase.value, next_phase.value,
                    ps.win_rate * 100, ps.profit_factor, ps.max_drawdown * 100,
                )
                if self._on_phase_advance:
                    try:
                        self._on_phase_advance(old_phase, next_phase)
                    except Exception as exc:
                        logger.error("Phase advance callback error: %s", exc)

    def can_advance(self) -> Tuple[bool, str]:
        """Check whether the current phase meets criteria for advancement."""
        with self._lock:
            phase = self.current_phase
            if phase == DeployPhase.FULL:
                return False, "Already at FULL deployment"

            ps = self._phase_stats[phase.value]
            criteria = PHASE_ADVANCE_CRITERIA.get(phase.value, {})
            min_trades = MIN_TRADES_PER_PHASE.get(phase.value, 999)

            issues = []
            if ps.trade_count < min_trades:
                issues.append(f"trades {ps.trade_count}/{min_trades}")
            if ps.win_rate < criteria.get("min_win_rate", 0):
                issues.append(
                    f"win_rate {ps.win_rate:.1%} < {criteria['min_win_rate']:.1%}"
                )
            if ps.profit_factor < criteria.get("min_profit_factor", 0):
                issues.append(
                    f"profit_factor {ps.profit_factor:.2f} < {criteria['min_profit_factor']:.2f}"
                )
            if ps.max_drawdown > criteria.get("max_drawdown", 1):
                issues.append(
                    f"drawdown {ps.max_drawdown:.1%} > {criteria['max_drawdown']:.1%}"
                )

            if issues:
                return False, "; ".join(issues)
            return True, "all criteria met"

    # ------------------------------------------------------------------
    # Kill-switch integration
    # ------------------------------------------------------------------

    def activate_kill_switch(self, reason: str) -> None:
        """Halt all live deployment and reset to PAPER phase."""
        with self._lock:
            self._state.kill_switch_active = True
            prev_phase = self._state.current_phase
            self._state.current_phase = DeployPhase.PAPER.value
            self._save_state()
            logger.critical(
                "🛑 IncrementalDeployer kill-switch activated: %s (was %s)",
                reason, prev_phase,
            )

    def deactivate_kill_switch(self) -> None:
        """Re-enable live deployment (manual recovery only)."""
        with self._lock:
            self._state.kill_switch_active = False
            self._save_state()
            logger.info("✅ IncrementalDeployer kill-switch deactivated")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def status(self) -> Dict:
        """Return a status dictionary for monitoring dashboards."""
        with self._lock:
            phase = self.current_phase
            ps = self._phase_stats[phase.value]
            can_adv, reason = self.can_advance()
            return {
                "current_phase": phase.value,
                "capital_fraction": phase.capital_fraction,
                "live_capital_usd": self.total_risk_budget * phase.capital_fraction,
                "total_live_trades": self._state.total_live_trades,
                "phase_stats": ps.to_dict(),
                "can_advance": can_adv,
                "advance_blockers": reason if not can_adv else "",
                "kill_switch_active": self._state.kill_switch_active,
                "phase_history": list(self._state.phase_history),
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_deployer_instance: Optional[IncrementalDeployer] = None
_deployer_lock = threading.Lock()


def get_incremental_deployer(
    target_capital: float = 10_000.0,
    state_path: str = "data/incremental_deployer_state.json",
    **kwargs: Any,
) -> IncrementalDeployer:
    """Return the global IncrementalDeployer singleton."""
    global _deployer_instance
    with _deployer_lock:
        if _deployer_instance is None:
            _deployer_instance = IncrementalDeployer(
                target_capital=target_capital,
                state_path=state_path,
                **kwargs,
            )
    return _deployer_instance
