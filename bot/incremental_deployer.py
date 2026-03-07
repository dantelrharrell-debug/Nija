"""
Incremental Capital Deployer
==============================

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
        drawdown_pct  : current portfolio drawdown percentage (0–100).
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

_deployer_instance: Optional[IncrementalDeployer] = None
_deployer_lock = threading.Lock()


def get_incremental_deployer(
    target_capital: float = 10_000.0,
    state_path: str = "data/incremental_deployer_state.json",
    **kwargs: Any,
) -> IncrementalDeployer:
    """Return the process-wide IncrementalDeployer singleton."""
    global _deployer_instance
    with _deployer_lock:
        if _deployer_instance is None:
            _deployer_instance = IncrementalDeployer(
                target_capital=target_capital,
                state_path=state_path,
                **kwargs,
            )
    return _deployer_instance


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
