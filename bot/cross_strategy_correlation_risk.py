"""
NIJA Cross-Strategy Correlation Risk Control
=============================================

Prevents capital concentration in strategies that are behaving identically
by tracking rolling return correlations across all active strategies and
gating new entries when cross-strategy correlation is too high.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │             CrossStrategyCorrelationRisk                      │
  │                                                               │
  │  1. Return History Store  – rolling trade returns per         │
  │     strategy (deque, configurable lookback)                   │
  │                                                               │
  │  2. Correlation Matrix   – recalculated lazily on each        │
  │     approve_entry() call when dirty                           │
  │                                                               │
  │  3. Three-Gate Approval                                       │
  │       Gate A: max pairwise correlation vs any active peer     │
  │       Gate B: average portfolio-wide strategy correlation     │
  │       Gate C: per-strategy open-position count cap            │
  │                                                               │
  │  4. Proportional Size Reduction  – even approved entries      │
  │     are scaled down when peer correlation is elevated         │
  │                                                               │
  │  5. Audit Log            – every decision appended as         │
  │     JSON-lines to data/cross_strategy_correlation.jsonl       │
  └──────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.cross_strategy_correlation_risk import (
        get_cross_strategy_correlation_risk,
    )

    cscr = get_cross_strategy_correlation_risk()

    # After each strategy trade closes, record the return:
    cscr.record_return(strategy="RSI_9", pnl_pct=0.023)
    cscr.record_return(strategy="RSI_14", pnl_pct=0.019)

    # Before opening a new position:
    decision = cscr.approve_entry(
        strategy="RSI_9",
        symbol="BTC-USD",
        proposed_size_usd=500.0,
        active_strategies={"RSI_14": 800.0, "MACD": 300.0},
        portfolio_value=10_000.0,
    )
    if not decision.allowed:
        logger.warning("Cross-strategy gate blocked: %s", decision.reason)
        return

    # After the position closes:
    cscr.close_position("RSI_9")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.cross_strategy_correlation_risk")

# ---------------------------------------------------------------------------
# Constants – all overridable via constructor kwargs
# ---------------------------------------------------------------------------

DEFAULT_LOOKBACK: int = 50            # trade returns to keep per strategy
DEFAULT_MIN_HISTORY: int = 10         # minimum returns before correlation is used
DEFAULT_MAX_PORTFOLIO_CORR: float = 0.70  # block if avg strategy corr > this
DEFAULT_MAX_PEER_CORR: float = 0.85       # block if candidate corr > this with any peer
DEFAULT_SIZE_REDUCTION_SLOPE: float = 0.5 # fraction of size to shed at max_peer_corr
DEFAULT_MAX_CONCURRENT: int = 10      # max strategies with open positions simultaneously

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class CrossStrategyDecision:
    """Result returned by :meth:`CrossStrategyCorrelationRisk.approve_entry`."""

    allowed: bool
    reason: str
    strategy: str
    symbol: str
    proposed_size_usd: float
    adjusted_size_usd: float
    strategy_corr_score: float   # avg abs corr of requesting strategy vs active peers
    max_peer_corr: float         # highest pairwise corr vs any active peer
    active_peers: List[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class CrossStrategyStatus:
    """Snapshot returned by :meth:`CrossStrategyCorrelationRisk.get_status`."""

    num_tracked_strategies: int
    num_active_strategies: int
    portfolio_corr_score: float       # average abs pairwise corr across all active peers
    top_pairs: List[Tuple[str, str, float]]  # (strategy_a, strategy_b, corr)
    matrix_age_trades: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CrossStrategyCorrelationRisk:
    """
    Online cross-strategy correlation tracker and trade gate.

    Each strategy's rolling trade-return history is maintained internally.
    When a new position is requested the engine checks whether the requesting
    strategy's recent returns are highly correlated with those of any currently
    active strategy, and blocks or scales back the proposed size accordingly.

    Parameters
    ----------
    lookback : int
        Number of trade returns to retain per strategy (default 50).
    min_history : int
        Minimum returns required before correlation is estimated (default 10).
    max_portfolio_corr : float
        Average absolute correlation across all active strategy pairs that
        triggers a block (default 0.70).
    max_peer_corr : float
        Correlation of the candidate strategy vs any single active peer
        that triggers a block (default 0.85).
    size_reduction_slope : float
        Controls how aggressively position size is reduced when correlation
        is elevated (default 0.5 → up to 50 % reduction at max_peer_corr).
    max_concurrent : int
        Maximum number of strategies allowed to hold open positions
        simultaneously (default 10).
    """

    def __init__(
        self,
        lookback: int = DEFAULT_LOOKBACK,
        min_history: int = DEFAULT_MIN_HISTORY,
        max_portfolio_corr: float = DEFAULT_MAX_PORTFOLIO_CORR,
        max_peer_corr: float = DEFAULT_MAX_PEER_CORR,
        size_reduction_slope: float = DEFAULT_SIZE_REDUCTION_SLOPE,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    ) -> None:
        self.lookback = lookback
        self.min_history = min_history
        self.max_portfolio_corr = max_portfolio_corr
        self.max_peer_corr = max_peer_corr
        self.size_reduction_slope = size_reduction_slope
        self.max_concurrent = max_concurrent

        # return history: strategy → deque of pnl_pct floats
        self._returns: Dict[str, Deque[float]] = {}
        # active positions: strategy → size_usd
        self._positions: Dict[str, float] = {}
        # cached correlation matrix (recalculated lazily)
        self._corr_matrix: Optional[np.ndarray] = None
        self._corr_strategies: List[str] = []
        self._matrix_dirty: bool = True
        self._matrix_age_trades: int = 0

        self._lock = threading.RLock()

        # Ensure data directory exists
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = DATA_DIR / "cross_strategy_correlation.jsonl"

        logger.info(
            "CrossStrategyCorrelationRisk initialised "
            "(max_peer_corr=%.2f, max_portfolio_corr=%.2f, lookback=%d)",
            max_peer_corr,
            max_portfolio_corr,
            lookback,
        )

    # ------------------------------------------------------------------
    # Return ingestion
    # ------------------------------------------------------------------

    def record_return(self, strategy: str, pnl_pct: float) -> None:
        """
        Record a completed trade return for *strategy*.

        Call this after every trade closes to keep the correlation matrix
        current.  The deque is capped at ``lookback`` to maintain a rolling
        window.

        Parameters
        ----------
        strategy : str
            Unique strategy name (e.g. ``"RSI_9"``, ``"MACD_cross"``).
        pnl_pct : float
            Realised P&L as a fraction of the position (e.g. ``0.023``
            for +2.3 %).
        """
        with self._lock:
            if strategy not in self._returns:
                self._returns[strategy] = deque(maxlen=self.lookback)
            self._returns[strategy].append(float(pnl_pct))
            self._matrix_dirty = True
            self._matrix_age_trades += 1
            logger.debug(
                "CSCR: recorded return %.4f for %s (%d history)",
                pnl_pct,
                strategy,
                len(self._returns[strategy]),
            )

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def open_position(self, strategy: str, size_usd: float) -> None:
        """Register that *strategy* has opened a position of *size_usd*."""
        with self._lock:
            self._positions[strategy] = float(size_usd)
            logger.info("CSCR: position opened %s $%.2f", strategy, size_usd)

    def close_position(self, strategy: str) -> None:
        """Signal that *strategy*'s position has been fully closed."""
        with self._lock:
            self._positions.pop(strategy, None)
            logger.info("CSCR: position closed %s", strategy)

    def update_position_size(self, strategy: str, new_size_usd: float) -> None:
        """Update the recorded size for an existing open position."""
        with self._lock:
            if strategy in self._positions:
                self._positions[strategy] = float(new_size_usd)

    # ------------------------------------------------------------------
    # Core gate
    # ------------------------------------------------------------------

    def approve_entry(
        self,
        strategy: str,
        symbol: str,
        proposed_size_usd: float,
        active_strategies: Dict[str, float],
        portfolio_value: float,
    ) -> CrossStrategyDecision:
        """
        Decide whether a new position from *strategy* is acceptable given
        current cross-strategy correlation.

        Parameters
        ----------
        strategy : str
            The strategy requesting a new entry.
        symbol : str
            The instrument the strategy wants to trade.
        proposed_size_usd : float
            Requested position size in USD.
        active_strategies : Dict[str, float]
            Currently active strategies and their exposure ``{name: size_usd}``.
        portfolio_value : float
            Total portfolio value in USD (used for weight calculations).

        Returns
        -------
        CrossStrategyDecision
            Rich result with ``allowed`` flag, ``adjusted_size_usd``,
            and diagnostics.
        """
        with self._lock:
            # Sync internal position state with caller's view
            self._positions = {k: float(v) for k, v in active_strategies.items()}
            active_peers = [s for s in self._positions if s != strategy]

            self._rebuild_matrix_if_needed()

            strategy_corr = self._strategy_corr_score(strategy, active_peers)
            max_peer = self._max_peer_corr(strategy, active_peers)
            portfolio_corr = self._portfolio_corr_score(active_peers)

            adjusted = proposed_size_usd
            reason_parts: List[str] = []
            allowed = True

            # Gate A: pairwise correlation with any active peer
            if max_peer > self.max_peer_corr:
                allowed = False
                reason_parts.append(
                    f"peer_corr={max_peer:.2f} > limit={self.max_peer_corr:.2f}"
                )

            # Gate B: portfolio-wide average strategy correlation
            if portfolio_corr > self.max_portfolio_corr:
                allowed = False
                reason_parts.append(
                    f"portfolio_corr={portfolio_corr:.2f} > limit={self.max_portfolio_corr:.2f}"
                )

            # Gate C: max concurrent strategies
            if len(active_peers) >= self.max_concurrent:
                allowed = False
                reason_parts.append(
                    f"active_strategies={len(active_peers)+1} > limit={self.max_concurrent}"
                )

            # Proportional size reduction (even when allowed)
            if allowed and max_peer > 0:
                reduction = max_peer * self.size_reduction_slope
                adjusted = proposed_size_usd * (1.0 - min(reduction, 0.75))
                if adjusted < proposed_size_usd:
                    reason_parts.append(
                        f"size reduced by {reduction:.0%} (peer_corr={max_peer:.2f})"
                    )

            reason = (
                " | ".join(reason_parts) if reason_parts else "cross-strategy gate passed"
            )

            decision = CrossStrategyDecision(
                allowed=allowed,
                reason=reason,
                strategy=strategy,
                symbol=symbol,
                proposed_size_usd=proposed_size_usd,
                adjusted_size_usd=round(adjusted, 2),
                strategy_corr_score=round(strategy_corr, 4),
                max_peer_corr=round(max_peer, 4),
                active_peers=active_peers,
            )

            self._log_decision(decision)

            if not allowed:
                logger.warning("CSCR blocked %s/%s: %s", strategy, symbol, reason)
            else:
                logger.debug("CSCR approved %s/%s: %s", strategy, symbol, reason)

            return decision

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def get_status(self) -> CrossStrategyStatus:
        """Return a snapshot of the current cross-strategy correlation state."""
        with self._lock:
            self._rebuild_matrix_if_needed()
            active = list(self._positions.keys())
            portfolio_corr = self._portfolio_corr_score(active)
            top_pairs = self._top_correlated_pairs(n=5)
            return CrossStrategyStatus(
                num_tracked_strategies=len(self._returns),
                num_active_strategies=len(self._positions),
                portfolio_corr_score=round(portfolio_corr, 4),
                top_pairs=top_pairs,
                matrix_age_trades=self._matrix_age_trades,
            )

    def get_pair_correlation(self, strategy_a: str, strategy_b: str) -> Optional[float]:
        """Return the current correlation between two strategies, or *None*."""
        with self._lock:
            self._rebuild_matrix_if_needed()
            return self._lookup_corr(strategy_a, strategy_b)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_matrix_if_needed(self) -> None:
        """Recalculate the full correlation matrix when the cache is stale."""
        if not self._matrix_dirty:
            return

        eligible = {
            strat: list(hist)
            for strat, hist in self._returns.items()
            if len(hist) >= self.min_history
        }

        if len(eligible) < 2:
            self._corr_matrix = None
            self._corr_strategies = []
            self._matrix_dirty = False
            return

        strategies = sorted(eligible.keys())
        min_len = min(len(eligible[s]) for s in strategies)
        ret_array = np.array(
            [eligible[s][-min_len:] for s in strategies], dtype=float
        )  # shape: (n_strategies, min_len)

        if ret_array.shape[1] < 2:
            self._corr_matrix = None
            self._corr_strategies = []
            self._matrix_dirty = False
            return

        std = ret_array.std(axis=1)
        valid_mask = std > 1e-10
        if valid_mask.sum() < 2:
            self._corr_matrix = None
            self._corr_strategies = []
            self._matrix_dirty = False
            return

        valid_strategies = [s for s, v in zip(strategies, valid_mask) if v]
        valid_returns = ret_array[valid_mask]
        corr = np.corrcoef(valid_returns)

        self._corr_matrix = corr
        self._corr_strategies = valid_strategies
        self._matrix_dirty = False
        self._matrix_age_trades = 0
        logger.debug("CSCR matrix rebuilt: %d strategies", len(valid_strategies))

    def _lookup_corr(self, strat_a: str, strat_b: str) -> Optional[float]:
        """Return cached correlation, *None* if unknown, 0.0 for self-comparison.

        Note: self-correlation deliberately returns 0.0 (not the mathematically
        correct 1.0) so that callers such as ``_max_peer_corr`` and
        ``_portfolio_corr_score`` can safely iterate over all strategy names
        without special-casing the diagonal – a self-entry would otherwise
        spuriously inflate the correlation score.
        """
        if strat_a == strat_b:
            return 0.0
        if self._corr_matrix is None:
            return None
        syms = self._corr_strategies
        if strat_a not in syms or strat_b not in syms:
            return None
        i, j = syms.index(strat_a), syms.index(strat_b)
        return float(self._corr_matrix[i, j])

    def _max_peer_corr(self, candidate: str, peers: List[str]) -> float:
        """Return the maximum absolute correlation of *candidate* vs any peer."""
        if self._corr_matrix is None or not peers:
            return 0.0
        max_corr = 0.0
        for peer in peers:
            c = self._lookup_corr(candidate, peer)
            if c is not None:
                max_corr = max(max_corr, abs(c))
        return max_corr

    def _strategy_corr_score(self, candidate: str, peers: List[str]) -> float:
        """Average absolute correlation of *candidate* vs all given peers."""
        if self._corr_matrix is None or not peers:
            return 0.0
        values = []
        for peer in peers:
            c = self._lookup_corr(candidate, peer)
            if c is not None:
                values.append(abs(c))
        return float(np.mean(values)) if values else 0.0

    def _portfolio_corr_score(self, active: List[str]) -> float:
        """Average absolute pairwise correlation across all active strategies."""
        if len(active) < 2 or self._corr_matrix is None:
            return 0.0
        total, count = 0.0, 0
        for i, s1 in enumerate(active):
            for s2 in active[i + 1:]:
                c = self._lookup_corr(s1, s2)
                if c is not None:
                    total += abs(c)
                    count += 1
        return total / count if count > 0 else 0.0

    def _top_correlated_pairs(self, n: int = 5) -> List[Tuple[str, str, float]]:
        """Return the *n* most-correlated strategy pairs (across all tracked)."""
        if self._corr_matrix is None:
            return []
        pairs: List[Tuple[str, str, float]] = []
        syms = self._corr_strategies
        for i, s1 in enumerate(syms):
            for j, s2 in enumerate(syms):
                if i < j:
                    pairs.append((s1, s2, float(self._corr_matrix[i, j])))
        pairs.sort(key=lambda x: abs(x[2]), reverse=True)
        return pairs[:n]

    def _log_decision(self, decision: CrossStrategyDecision) -> None:
        """Append *decision* to the JSON-lines audit log."""
        try:
            record = {
                "timestamp": decision.timestamp,
                "strategy": decision.strategy,
                "symbol": decision.symbol,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "proposed_size_usd": decision.proposed_size_usd,
                "adjusted_size_usd": decision.adjusted_size_usd,
                "strategy_corr_score": decision.strategy_corr_score,
                "max_peer_corr": decision.max_peer_corr,
                "active_peers": decision.active_peers,
            }
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_cscr_instance: Optional[CrossStrategyCorrelationRisk] = None
_cscr_lock = threading.Lock()


def get_cross_strategy_correlation_risk(**kwargs) -> CrossStrategyCorrelationRisk:
    """
    Return the process-wide :class:`CrossStrategyCorrelationRisk` singleton.

    All keyword arguments are forwarded to the constructor on first call and
    ignored on subsequent calls (singleton pattern).
    """
    global _cscr_instance
    with _cscr_lock:
        if _cscr_instance is None:
            _cscr_instance = CrossStrategyCorrelationRisk(**kwargs)
            logger.info("CrossStrategyCorrelationRisk singleton created")
    return _cscr_instance
