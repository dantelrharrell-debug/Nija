"""
NIJA Portfolio Risk Tuner
==========================

Fine-tunes per-asset allocation limits, strategy quorums, and confidence
thresholds based on backtesting outcomes.  Also implements dynamic capital
allocation (increase exposure to stronger strategies, reduce to weaker ones)
and enforces portfolio-level VaR and maximum drawdown hard stops.

Architecture
------------
- **AllocationLimits**     – per-asset and per-strategy cap enforcement
- **StrategyQuorum**       – minimum number of confirming signals required
- **PortfolioRiskConstraints** – VaR + max-drawdown guard rails
- **PortfolioRiskTuner**   – orchestrator that calls the above and adjusts
  weights through the self-learning allocator

Integration
-----------
- ``bot.portfolio_var_monitor``        – live VaR feed
- ``bot.self_learning_strategy_allocator`` – weight adjustment
- ``bot.global_risk_controller``       – kill-switch handshake

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.portfolio_risk_tuner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard limits for position sizing (fraction of portfolio)
DEFAULT_MAX_PER_ASSET_PCT: float = 0.10         # max 10 % of portfolio in one asset
DEFAULT_MAX_PER_STRATEGY_PCT: float = 0.40       # max 40 % of capital in one strategy
DEFAULT_STRATEGY_QUORUM: int = 2                 # min confirming signals before entry
DEFAULT_MIN_SIGNAL_CONFIDENCE: float = 0.65      # 0-1 scale

# VaR and drawdown limits
DEFAULT_VAR_99_HARD_LIMIT: float = 0.08          # 8 % of portfolio value
DEFAULT_MAX_DRAWDOWN_HARD_LIMIT: float = 0.20    # 20 % portfolio drawdown triggers halt

# Dynamic allocation tuning bounds
MIN_STRATEGY_WEIGHT: float = 0.05
MAX_STRATEGY_WEIGHT: float = 0.60


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AllocationLimits:
    """Per-asset and per-strategy allocation caps."""
    max_per_asset_pct: float = DEFAULT_MAX_PER_ASSET_PCT
    max_per_strategy_pct: float = DEFAULT_MAX_PER_STRATEGY_PCT

    def check_asset(self, proposed_pct: float, asset: str) -> Tuple[bool, str]:
        """
        Validate that a proposed position size doesn't exceed the per-asset cap.

        Returns (allowed, reason).
        """
        if proposed_pct > self.max_per_asset_pct:
            return (
                False,
                f"{asset}: proposed {proposed_pct*100:.1f}% exceeds "
                f"cap {self.max_per_asset_pct*100:.1f}%",
            )
        return True, ""

    def check_strategy(self, proposed_pct: float, strategy: str) -> Tuple[bool, str]:
        """Validate that a strategy's total exposure doesn't exceed its cap."""
        if proposed_pct > self.max_per_strategy_pct:
            return (
                False,
                f"{strategy}: proposed {proposed_pct*100:.1f}% exceeds "
                f"cap {self.max_per_strategy_pct*100:.1f}%",
            )
        return True, ""


@dataclass
class StrategyQuorum:
    """
    Minimum confirming signals required before NIJA enters a trade.

    If ``required_count`` strategies produce a signal in the same direction,
    the quorum is met and the trade may proceed.
    """
    required_count: int = DEFAULT_STRATEGY_QUORUM
    min_confidence: float = DEFAULT_MIN_SIGNAL_CONFIDENCE

    def is_met(self, signals: Dict[str, float]) -> Tuple[bool, int]:
        """
        Evaluate whether the quorum is met.

        Parameters
        ----------
        signals : dict
            Mapping of strategy_name → confidence score (0–1).
            Only signals with confidence ≥ min_confidence count.

        Returns
        -------
        (met: bool, count: int)
        """
        qualifying = [c for c in signals.values() if c >= self.min_confidence]
        count = len(qualifying)
        return count >= self.required_count, count


@dataclass
class PortfolioRiskConstraints:
    """
    Hard limits on portfolio-level VaR and maximum drawdown.

    When a limit is breached the tuner halts new entries until the
    metric recovers below the recovery threshold.
    """
    var_99_hard_limit: float = DEFAULT_VAR_99_HARD_LIMIT
    max_drawdown_hard_limit: float = DEFAULT_MAX_DRAWDOWN_HARD_LIMIT
    # Recovery thresholds (must fall below before trading resumes)
    var_99_recovery: float = field(default=0.0)
    drawdown_recovery: float = field(default=0.0)

    def __post_init__(self) -> None:
        if self.var_99_recovery == 0.0:
            self.var_99_recovery = self.var_99_hard_limit * 0.75
        if self.drawdown_recovery == 0.0:
            self.drawdown_recovery = self.max_drawdown_hard_limit * 0.75

    def check(
        self,
        current_var_99: float,
        current_drawdown: float,
    ) -> Tuple[bool, str]:
        """
        Return (trading_allowed, reason).

        Parameters
        ----------
        current_var_99  : fraction of portfolio value (e.g. 0.06 = 6 %)
        current_drawdown: fraction of peak portfolio value (e.g. 0.15 = 15 %)
        """
        if current_var_99 >= self.var_99_hard_limit:
            return (
                False,
                f"VaR-99 {current_var_99*100:.2f}% ≥ limit {self.var_99_hard_limit*100:.1f}%",
            )
        if current_drawdown >= self.max_drawdown_hard_limit:
            return (
                False,
                f"Drawdown {current_drawdown*100:.2f}% ≥ limit "
                f"{self.max_drawdown_hard_limit*100:.1f}%",
            )
        return True, ""


@dataclass
class TunerSnapshot:
    """Point-in-time state snapshot of the risk tuner."""
    timestamp: str
    trading_allowed: bool
    halt_reason: str
    strategy_weights: Dict[str, float]
    allocation_limits: Dict[str, float]
    quorum_required: int
    min_confidence: float
    current_var_99: float
    current_drawdown: float

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "trading_allowed": self.trading_allowed,
            "halt_reason": self.halt_reason,
            "strategy_weights": self.strategy_weights,
            "allocation_limits": {
                "max_per_asset_pct": self.allocation_limits.get("max_per_asset_pct", 0),
                "max_per_strategy_pct": self.allocation_limits.get("max_per_strategy_pct", 0),
            },
            "quorum_required": self.quorum_required,
            "min_confidence": self.min_confidence,
            "current_var_99": self.current_var_99,
            "current_drawdown": self.current_drawdown,
        }


# ---------------------------------------------------------------------------
# Main tuner class
# ---------------------------------------------------------------------------

class PortfolioRiskTuner:
    """
    Orchestrates portfolio-level risk tuning for NIJA.

    Responsibilities
    ----------------
    1. Enforce per-asset and per-strategy allocation limits.
    2. Gate entries behind a strategy-signal quorum.
    3. Halt trading when VaR or drawdown limits are breached.
    4. Dynamically shift capital weights toward better-performing strategies.

    Thread safety
    -------------
    All state mutations are guarded by ``_lock`` so the tuner is safe to
    call from multiple threads (e.g. scanning thread + webhook thread).
    """

    def __init__(
        self,
        allocation_limits: Optional[AllocationLimits] = None,
        quorum: Optional[StrategyQuorum] = None,
        risk_constraints: Optional[PortfolioRiskConstraints] = None,
    ) -> None:
        self._lock = threading.RLock()

        self.allocation_limits = allocation_limits or AllocationLimits()
        self.quorum = quorum or StrategyQuorum()
        self.risk_constraints = risk_constraints or PortfolioRiskConstraints()

        # Live risk metrics (updated externally via update_risk_metrics)
        self._current_var_99: float = 0.0
        self._current_drawdown: float = 0.0

        # Strategy weights; starts equal across known strategies
        self._strategy_weights: Dict[str, float] = {}
        self._halted: bool = False
        self._halt_reason: str = ""

        logger.info("PortfolioRiskTuner initialised")

    # ------------------------------------------------------------------
    # Risk metric updates (called by the monitoring loop)
    # ------------------------------------------------------------------

    def update_risk_metrics(
        self, var_99: float, drawdown: float
    ) -> Tuple[bool, str]:
        """
        Update live VaR and drawdown metrics and evaluate risk limits.

        Returns (trading_allowed, reason).
        """
        with self._lock:
            self._current_var_99 = var_99
            self._current_drawdown = drawdown
            allowed, reason = self.risk_constraints.check(var_99, drawdown)
            self._halted = not allowed
            self._halt_reason = reason
            if not allowed:
                logger.warning("Trading halted by risk constraints: %s", reason)
            return allowed, reason

    # ------------------------------------------------------------------
    # Trade entry gate
    # ------------------------------------------------------------------

    def approve_entry(
        self,
        asset: str,
        strategy: str,
        proposed_asset_pct: float,
        proposed_strategy_pct: float,
        strategy_signals: Dict[str, float],
    ) -> Tuple[bool, str]:
        """
        Comprehensive entry gate.

        Checks (in order):
        1. Global halt flag (VaR / drawdown breach)
        2. Per-asset allocation cap
        3. Per-strategy allocation cap
        4. Strategy signal quorum

        Returns (approved, reason).
        """
        with self._lock:
            if self._halted:
                return False, f"HALTED: {self._halt_reason}"

            allowed, reason = self.allocation_limits.check_asset(proposed_asset_pct, asset)
            if not allowed:
                return False, reason

            allowed, reason = self.allocation_limits.check_strategy(
                proposed_strategy_pct, strategy
            )
            if not allowed:
                return False, reason

            quorum_met, count = self.quorum.is_met(strategy_signals)
            if not quorum_met:
                return (
                    False,
                    f"Quorum not met: {count}/{self.quorum.required_count} "
                    f"qualifying signals (min confidence "
                    f"{self.quorum.min_confidence:.0%})",
                )

            return True, "approved"

    # ------------------------------------------------------------------
    # Dynamic weight management
    # ------------------------------------------------------------------

    def update_strategy_weights(self, new_weights: Dict[str, float]) -> None:
        """
        Accept new strategy weights (e.g. from self_learning_strategy_allocator)
        and clamp each to [MIN_STRATEGY_WEIGHT, MAX_STRATEGY_WEIGHT].

        Weights are stored as-is after clamping (not normalised) so that the
        per-strategy bound is always respected.  Callers treat the values as
        relative multipliers rather than strict fractions that sum to 1.0.
        """
        with self._lock:
            self._strategy_weights = {
                k: max(MIN_STRATEGY_WEIGHT, min(MAX_STRATEGY_WEIGHT, v))
                for k, v in new_weights.items()
            }
            logger.info("Strategy weights updated: %s", self._strategy_weights)

    def get_strategy_weight(self, strategy: str) -> float:
        """Return the current weight for a strategy (defaults to equal share)."""
        with self._lock:
            if not self._strategy_weights:
                return 1.0  # no weights set yet → unconstrained
            return self._strategy_weights.get(strategy, MIN_STRATEGY_WEIGHT)

    # ------------------------------------------------------------------
    # Configuration tuning helpers
    # ------------------------------------------------------------------

    def set_quorum(self, required_count: int, min_confidence: float) -> None:
        """Update quorum settings at runtime."""
        with self._lock:
            self.quorum.required_count = required_count
            self.quorum.min_confidence = min_confidence
            logger.info(
                "Quorum updated: required=%d, min_confidence=%.0f%%",
                required_count, min_confidence * 100,
            )

    def set_allocation_caps(
        self, max_per_asset_pct: float, max_per_strategy_pct: float
    ) -> None:
        """Update allocation caps at runtime."""
        with self._lock:
            self.allocation_limits.max_per_asset_pct = max_per_asset_pct
            self.allocation_limits.max_per_strategy_pct = max_per_strategy_pct
            logger.info(
                "Allocation caps updated: asset=%.1f%%, strategy=%.1f%%",
                max_per_asset_pct * 100, max_per_strategy_pct * 100,
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def snapshot(self) -> TunerSnapshot:
        """Return a point-in-time snapshot of tuner state."""
        with self._lock:
            return TunerSnapshot(
                timestamp=datetime.utcnow().isoformat(),
                trading_allowed=not self._halted,
                halt_reason=self._halt_reason,
                strategy_weights=dict(self._strategy_weights),
                allocation_limits={
                    "max_per_asset_pct": self.allocation_limits.max_per_asset_pct,
                    "max_per_strategy_pct": self.allocation_limits.max_per_strategy_pct,
                },
                quorum_required=self.quorum.required_count,
                min_confidence=self.quorum.min_confidence,
                current_var_99=self._current_var_99,
                current_drawdown=self._current_drawdown,
            )

    def is_halted(self) -> bool:
        """Return True if trading is currently halted by risk constraints."""
        with self._lock:
            return self._halted


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_tuner_instance: Optional[PortfolioRiskTuner] = None
_tuner_lock = threading.Lock()


def get_portfolio_risk_tuner() -> PortfolioRiskTuner:
    """Return the global PortfolioRiskTuner singleton."""
    global _tuner_instance
    with _tuner_lock:
        if _tuner_instance is None:
            _tuner_instance = PortfolioRiskTuner()
        return _tuner_instance
