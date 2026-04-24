"""
NIJA Global Portfolio Engine — Strategy Coordinator
====================================================

The Global Portfolio Engine is the **top-level orchestration layer** that:

1. **Registers** and manages a fleet of named strategies.
2. **Allocates** capital to each strategy based on regime-aware scoring from
   the MetaLearningOptimizer (or equal-weight fallback).
3. **Coordinates** entry requests from all strategies through the
   ``PortfolioMasterEngine`` so that portfolio-level risk limits are always
   respected.
4. **Aggregates** per-strategy performance into a single portfolio performance
   view, including Sharpe, P&L attribution, and win-rate by strategy.
5. **Switches** strategy weights dynamically as the ``AIRegimeEngine``
   detects regime transitions (BULL → BEAR → SIDEWAYS).

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │                  GlobalPortfolioEngine                        │
  │                                                              │
  │  strategies: {name → StrategyRecord}                         │
  │                                                              │
  │  allocate_capital(portfolio_value, regime)                   │
  │      └─► MetaLearningOptimizer.get_regime_weights(regime)    │
  │              └─► {strategy → allocation_usd}                 │
  │                                                              │
  │  request_entry(strategy, symbol, side, size_usd, pv)         │
  │      └─► PortfolioMasterEngine.evaluate_entry(...)           │
  │              └─► PortfolioRiskReport (approved / blocked)    │
  │                                                              │
  │  record_trade(strategy, symbol, pnl_usd, is_win)             │
  │      └─► per-strategy P&L + MetaLearningOptimizer.record     │
  └──────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.global_portfolio_engine import get_global_portfolio_engine

    engine = get_global_portfolio_engine()

    # Register strategies on startup:
    engine.register_strategy("ApexTrend")
    engine.register_strategy("MeanReversion")
    engine.register_strategy("Breakout")

    # Allocate capital for the current session:
    allocations = engine.allocate_capital(
        portfolio_value_usd=50_000.0,
        regime="BULL",
    )
    # → {"ApexTrend": 25000.0, "MeanReversion": 10000.0, "Breakout": 15000.0}

    # Before placing an order on behalf of a strategy:
    report = engine.request_entry(
        strategy="ApexTrend",
        symbol="BTC-USD",
        side="long",
        size_usd=500.0,
        portfolio_value_usd=50_000.0,
    )
    if report.approved:
        execute(size_usd=report.approved_size_usd)

    # After a trade closes:
    engine.record_trade("ApexTrend", "BTC-USD", pnl_usd=42.0, is_win=True)

    # Dashboard:
    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.global_portfolio")

# ---------------------------------------------------------------------------
# Optional subsystem imports
# ---------------------------------------------------------------------------

try:
    from portfolio_master_engine import get_portfolio_master_engine, PortfolioRiskReport
    _PME_AVAILABLE = True
except ImportError:
    try:
        from bot.portfolio_master_engine import get_portfolio_master_engine, PortfolioRiskReport
        _PME_AVAILABLE = True
    except ImportError:
        _PME_AVAILABLE = False
        get_portfolio_master_engine = None  # type: ignore
        PortfolioRiskReport = None  # type: ignore
        logger.warning("PortfolioMasterEngine not available — risk gating disabled")

try:
    from meta_learning_optimizer import get_meta_learning_optimizer
    _MLO_AVAILABLE = True
except ImportError:
    try:
        from bot.meta_learning_optimizer import get_meta_learning_optimizer
        _MLO_AVAILABLE = True
    except ImportError:
        _MLO_AVAILABLE = False
        get_meta_learning_optimizer = None  # type: ignore
        logger.warning("MetaLearningOptimizer not available — using equal-weight allocation")

try:
    from ai_regime_engine import get_ai_regime_engine
    _ARE_AVAILABLE = True
except ImportError:
    try:
        from bot.ai_regime_engine import get_ai_regime_engine
        _ARE_AVAILABLE = True
    except ImportError:
        _ARE_AVAILABLE = False
        get_ai_regime_engine = None  # type: ignore
        logger.warning("AIRegimeEngine not available — regime-aware switching disabled")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StrategyRecord:
    """Per-strategy bookkeeping."""
    name: str
    allocation_usd: float = 0.0
    total_pnl: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    enabled: bool = True
    registered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.trade_count if self.trade_count else 0.0


# ---------------------------------------------------------------------------
# GlobalPortfolioEngine
# ---------------------------------------------------------------------------


class GlobalPortfolioEngine:
    """
    Top-level orchestrator that coordinates all registered strategies.

    Thread-safe; singleton via ``get_global_portfolio_engine()``.
    """

    def __init__(self, min_strategy_allocation_pct: float = 0.05) -> None:
        self._lock = threading.Lock()
        self._min_alloc_pct = min_strategy_allocation_pct

        self._strategies: Dict[str, StrategyRecord] = {}

        # Lazy subsystem handles
        self._pme = None   # PortfolioMasterEngine
        self._mlo = None   # MetaLearningOptimizer
        self._are = None   # AIRegimeEngine

        self._current_regime: str = "UNKNOWN"
        self._total_trades: int = 0
        self._total_pnl: float = 0.0
        self._last_allocation: Dict[str, float] = {}

        logger.info("=" * 60)
        logger.info("🌐 Global Portfolio Engine initialised")
        logger.info("   min_strategy_allocation : %.0f%%", min_strategy_allocation_pct * 100)
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Subsystem accessors
    # ------------------------------------------------------------------

    def _get_pme(self):
        if self._pme is None and _PME_AVAILABLE:
            try:
                self._pme = get_portfolio_master_engine()
            except Exception:
                pass
        return self._pme

    def _get_mlo(self):
        if self._mlo is None and _MLO_AVAILABLE:
            try:
                self._mlo = get_meta_learning_optimizer()
            except Exception:
                pass
        return self._mlo

    def _get_are(self):
        if self._are is None and _ARE_AVAILABLE:
            try:
                self._are = get_ai_regime_engine()
            except Exception:
                pass
        return self._are

    # ------------------------------------------------------------------
    # Strategy registration
    # ------------------------------------------------------------------

    def register_strategy(self, name: str) -> StrategyRecord:
        """Register a new strategy or return the existing record."""
        with self._lock:
            if name not in self._strategies:
                self._strategies[name] = StrategyRecord(name=name)
                logger.info("✅ Strategy registered: %s", name)
            return self._strategies[name]

    def disable_strategy(self, name: str) -> None:
        """Disable a strategy — it will receive zero allocation."""
        with self._lock:
            if name in self._strategies:
                self._strategies[name].enabled = False
                logger.warning("⛔ Strategy disabled: %s", name)

    def enable_strategy(self, name: str) -> None:
        """Re-enable a previously disabled strategy."""
        with self._lock:
            if name in self._strategies:
                self._strategies[name].enabled = True
                logger.info("✅ Strategy re-enabled: %s", name)

    # ------------------------------------------------------------------
    # Capital allocation
    # ------------------------------------------------------------------

    def allocate_capital(
        self,
        portfolio_value_usd: float,
        regime: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Compute USD allocations for each enabled strategy.

        Uses the MetaLearningOptimizer for regime-aware weights when available;
        otherwise falls back to equal-weight distribution.

        Parameters
        ----------
        portfolio_value_usd : float
            Current total portfolio value.
        regime : str, optional
            Current market regime label (e.g. "BULL", "BEAR", "SIDEWAYS").
            If not provided, attempts to read from AIRegimeEngine.

        Returns
        -------
        dict
            ``{strategy_name: allocation_usd}``.
        """
        with self._lock:
            # Resolve regime
            if regime is None:
                are = self._get_are()
                if are is not None:
                    result = are.get_last_result()
                    if result is not None:
                        regime = result.regime
            if regime is not None:
                self._current_regime = regime

            enabled = [s for s in self._strategies.values() if s.enabled]
            if not enabled:
                return {}

            # Get weights
            weights: Dict[str, float] = {}
            mlo = self._get_mlo()
            if mlo is not None and regime is not None:
                try:
                    raw_weights = mlo.get_regime_weights(regime)
                    for strat in enabled:
                        weights[strat.name] = raw_weights.get(strat.name, 1.0)
                except Exception as exc:
                    logger.warning("MetaLearningOptimizer weight fetch failed: %s", exc)

            # Fallback: equal weights
            if not weights:
                weights = {s.name: 1.0 for s in enabled}

            # Normalize
            total_weight = sum(weights.values()) or 1.0
            allocations: Dict[str, float] = {}
            for strat in enabled:
                w = weights.get(strat.name, 0.0) / total_weight
                alloc = portfolio_value_usd * max(w, self._min_alloc_pct)
                allocations[strat.name] = round(alloc, 2)
                strat.allocation_usd = alloc

            self._last_allocation = dict(allocations)
            logger.info(
                "💰 Capital allocated (regime=%s, portfolio=$%.2f): %s",
                self._current_regime, portfolio_value_usd, allocations,
            )
            return allocations

    # ------------------------------------------------------------------
    # Entry coordination
    # ------------------------------------------------------------------

    def request_entry(
        self,
        strategy: str,
        symbol: str,
        side: str,
        size_usd: float,
        portfolio_value_usd: float,
    ) -> Any:
        """
        Gate a strategy's trade request through the PortfolioMasterEngine.

        Returns a ``PortfolioRiskReport`` (approved / blocked).
        If PortfolioMasterEngine is unavailable, returns a simple namespace
        with ``approved=True`` and ``approved_size_usd=size_usd``.
        """
        pme = self._get_pme()
        if pme is not None:
            report = pme.evaluate_entry(
                symbol=symbol,
                side=side,
                proposed_size_usd=size_usd,
                portfolio_value_usd=portfolio_value_usd,
            )
            if report.approved:
                pme.register_position(symbol=symbol, size_usd=report.approved_size_usd, side=side)
            return report

        # Fallback: approve as-is
        class _SimpleApproval:
            approved = True
            approved_size_usd = size_usd
            risk_score = 0.0
            block_reason = None
            gate_verdicts: Dict[str, str] = {}

        return _SimpleApproval()

    def notify_close(
        self,
        strategy: str,
        symbol: str,
        pnl_usd: float = 0.0,
    ) -> None:
        """Notify the portfolio engine that a position has been closed."""
        pme = self._get_pme()
        if pme is not None:
            pme.close_position(symbol=symbol, pnl_usd=pnl_usd)

    # ------------------------------------------------------------------
    # Trade recording
    # ------------------------------------------------------------------

    def record_trade(
        self,
        strategy: str,
        symbol: str,
        pnl_usd: float,
        is_win: bool,
    ) -> None:
        """Record a completed trade outcome for analytics and meta-learning."""
        with self._lock:
            rec = self._strategies.get(strategy)
            if rec is not None:
                rec.total_pnl += pnl_usd
                rec.trade_count += 1
                if is_win:
                    rec.win_count += 1

            self._total_trades += 1
            self._total_pnl += pnl_usd

        # Forward to MetaLearningOptimizer
        mlo = self._get_mlo()
        if mlo is not None:
            try:
                mlo.record_outcome(
                    strategy=strategy,
                    regime=self._current_regime,
                    pnl_pct=pnl_usd,
                    is_win=is_win,
                )
            except Exception as exc:
                logger.debug("MetaLearningOptimizer.record_outcome failed: %s", exc)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of portfolio engine state."""
        with self._lock:
            strategies_info = []
            for name, rec in self._strategies.items():
                strategies_info.append({
                    "strategy": name,
                    "enabled": rec.enabled,
                    "allocation_usd": round(rec.allocation_usd, 2),
                    "total_pnl_usd": round(rec.total_pnl, 2),
                    "trade_count": rec.trade_count,
                    "win_rate": round(rec.win_rate * 100, 1),
                    "avg_pnl_usd": round(rec.avg_pnl, 2),
                })

            return {
                "engine": "GlobalPortfolioEngine",
                "version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "current_regime": self._current_regime,
                "registered_strategies": len(self._strategies),
                "enabled_strategies": sum(1 for s in self._strategies.values() if s.enabled),
                "total_trades": self._total_trades,
                "total_pnl_usd": round(self._total_pnl, 2),
                "last_allocation": self._last_allocation,
                "strategies": strategies_info,
                "subsystems": {
                    "portfolio_master_engine": _PME_AVAILABLE,
                    "meta_learning_optimizer": _MLO_AVAILABLE,
                    "ai_regime_engine": _ARE_AVAILABLE,
                },
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[GlobalPortfolioEngine] = None
_instance_lock = threading.Lock()


def get_global_portfolio_engine(**kwargs) -> GlobalPortfolioEngine:
    """
    Return the process-wide ``GlobalPortfolioEngine`` singleton.

    Keyword arguments are forwarded to the constructor on first call only.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = GlobalPortfolioEngine(**kwargs)
        return _instance


__all__ = [
    "StrategyRecord",
    "GlobalPortfolioEngine",
    "get_global_portfolio_engine",
]
