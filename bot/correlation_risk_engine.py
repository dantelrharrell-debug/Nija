"""
NIJA Correlation Risk Engine
=============================

Tracks rolling pairwise correlations between every active position, identifies
highly-correlated clusters, and gates new trades when portfolio correlation
risk is too high.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │                  CorrelationRiskEngine                        │
  │                                                               │
  │  1. Price-History Store  – rolling OHLCV returns per symbol   │
  │                                                               │
  │  2. Correlation Matrix   – recalculated every N bars or on    │
  │     any add/remove of a position                              │
  │                                                               │
  │  3. Cluster Detection    – groups symbols with abs(corr) >    │
  │     cluster_threshold using union-find                        │
  │                                                               │
  │  4. Trade Gate           – approve_entry() returns            │
  │     CorrelationDecision with allowed flag, adjusted size,     │
  │     current correlation score, and active clusters            │
  │                                                               │
  │  5. Audit Log            – every decision appended as         │
  │     JSON-lines to data/correlation_decisions.jsonl            │
  └──────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.correlation_risk_engine import get_correlation_risk_engine

    cre = get_correlation_risk_engine()

    # Feed price data each bar:
    cre.update_price(symbol="BTC-USD", close_price=62_000.0)
    cre.update_price(symbol="ETH-USD", close_price=3_200.0)

    # Before opening a position:
    decision = cre.approve_entry(
        symbol="SOL-USD",
        proposed_size_usd=500.0,
        active_positions={"BTC-USD": 1000.0, "ETH-USD": 800.0},
        portfolio_value=10_000.0,
    )
    if not decision.allowed:
        logger.warning("Correlation gate blocked: %s", decision.reason)
        return

    # After a position closes:
    cre.remove_position("SOL-USD")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger("nija.correlation_risk_engine")

# ---------------------------------------------------------------------------
# Constants – all overridable via constructor kwargs
# ---------------------------------------------------------------------------

DEFAULT_LOOKBACK: int = 60            # bars of returns to keep per symbol
DEFAULT_MIN_HISTORY: int = 20         # minimum bars before computing correlation
DEFAULT_MAX_PORTFOLIO_CORR: float = 0.65   # block if avg portfolio corr > this
DEFAULT_MAX_PAIR_CORR: float = 0.80        # block if new symbol corr > this with any position
DEFAULT_CLUSTER_THRESHOLD: float = 0.70   # abs(corr) ≥ this → same cluster
DEFAULT_MAX_CLUSTER_WEIGHT: float = 0.40  # max % of portfolio in one cluster
DEFAULT_SIZE_REDUCTION_SLOPE: float = 0.5 # how aggressively to shrink size on high corr

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class CorrelationDecision:
    """Result returned by :meth:`CorrelationRiskEngine.approve_entry`."""

    allowed: bool
    reason: str
    symbol: str
    proposed_size_usd: float
    adjusted_size_usd: float
    portfolio_corr_score: float      # 0.0 – 1.0; higher = more correlated portfolio
    max_pair_corr: float             # highest correlation of new symbol vs any position
    active_clusters: List[List[str]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CorrelationStatus:
    """Snapshot returned by :meth:`CorrelationRiskEngine.get_status`."""

    num_tracked_symbols: int
    num_active_positions: int
    portfolio_corr_score: float
    clusters: List[List[str]]
    matrix_age_bars: int             # bars since last full recalculation
    top_pairs: List[Tuple[str, str, float]]  # most-correlated (sym1, sym2, corr)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CorrelationRiskEngine:
    """
    Rolling-correlation tracker and trade gate for portfolio-wide correlation risk.

    Parameters
    ----------
    lookback : int
        Number of price bars to retain for each symbol (default 60).
    min_history : int
        Minimum bars needed before correlation can be estimated (default 20).
    max_portfolio_corr : float
        Average absolute correlation across all active position pairs that
        triggers a block (default 0.65).
    max_pair_corr : float
        Correlation of the candidate symbol vs any single active position
        that triggers a block (default 0.80).
    cluster_threshold : float
        abs(corr) ≥ this value puts two symbols in the same cluster (default 0.70).
    max_cluster_weight : float
        Maximum portfolio weight (0–1) allowed in one cluster (default 0.40).
    size_reduction_slope : float
        Controls how aggressively position size is reduced when corr is high
        (default 0.5 → up to 50% reduction at max_pair_corr).
    """

    def __init__(
        self,
        lookback: int = DEFAULT_LOOKBACK,
        min_history: int = DEFAULT_MIN_HISTORY,
        max_portfolio_corr: float = DEFAULT_MAX_PORTFOLIO_CORR,
        max_pair_corr: float = DEFAULT_MAX_PAIR_CORR,
        cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
        max_cluster_weight: float = DEFAULT_MAX_CLUSTER_WEIGHT,
        size_reduction_slope: float = DEFAULT_SIZE_REDUCTION_SLOPE,
    ) -> None:
        self.lookback = lookback
        self.min_history = min_history
        self.max_portfolio_corr = max_portfolio_corr
        self.max_pair_corr = max_pair_corr
        self.cluster_threshold = cluster_threshold
        self.max_cluster_weight = max_cluster_weight
        self.size_reduction_slope = size_reduction_slope

        # price history: symbol → deque of close prices
        self._prices: Dict[str, Deque[float]] = {}
        # active positions: symbol → size_usd
        self._positions: Dict[str, float] = {}
        # cached correlation matrix (recalculated lazily)
        self._corr_matrix: Optional[np.ndarray] = None
        self._corr_symbols: List[str] = []
        self._matrix_dirty: bool = True
        self._matrix_age_bars: int = 0

        self._lock = threading.RLock()

        # Ensure data directory exists
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = DATA_DIR / "correlation_decisions.jsonl"

    # ------------------------------------------------------------------
    # Price ingestion
    # ------------------------------------------------------------------

    def update_price(self, symbol: str, close_price: float) -> None:
        """Record the latest close price for *symbol*."""
        with self._lock:
            if symbol not in self._prices:
                self._prices[symbol] = deque(maxlen=self.lookback)
            self._prices[symbol].append(float(close_price))
            self._matrix_dirty = True
            self._matrix_age_bars += 1

    def update_prices_bulk(self, prices: Dict[str, float]) -> None:
        """Convenience wrapper for updating multiple symbols at once."""
        for sym, px in prices.items():
            self.update_price(sym, px)

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def add_position(self, symbol: str, size_usd: float) -> None:
        """Register an open position."""
        with self._lock:
            self._positions[symbol] = float(size_usd)
            self._matrix_dirty = True
            logger.info("CRE: position added %s $%.2f", symbol, size_usd)

    def remove_position(self, symbol: str) -> None:
        """Remove a closed position."""
        with self._lock:
            self._positions.pop(symbol, None)
            self._matrix_dirty = True
            logger.info("CRE: position removed %s", symbol)

    def update_position_size(self, symbol: str, new_size_usd: float) -> None:
        """Update size for an existing position."""
        with self._lock:
            if symbol in self._positions:
                self._positions[symbol] = float(new_size_usd)

    # ------------------------------------------------------------------
    # Core gate
    # ------------------------------------------------------------------

    def approve_entry(
        self,
        symbol: str,
        proposed_size_usd: float,
        active_positions: Dict[str, float],
        portfolio_value: float,
    ) -> CorrelationDecision:
        """
        Decide whether a new position in *symbol* is acceptable given current
        portfolio correlation.

        Parameters
        ----------
        symbol : str
            Candidate symbol.
        proposed_size_usd : float
            Desired position size in USD.
        active_positions : Dict[str, float]
            Current open positions {symbol: size_usd}.
        portfolio_value : float
            Total portfolio value in USD.

        Returns
        -------
        CorrelationDecision
            Rich result with ``allowed`` flag, adjusted size, and diagnostics.
        """
        with self._lock:
            # Sync internal position state with caller's view
            self._positions = {k: float(v) for k, v in active_positions.items()}

            self._rebuild_matrix_if_needed()
            clusters = self._detect_clusters()

            portfolio_corr = self._portfolio_corr_score()
            max_pair = self._max_pair_corr(symbol)
            cluster_weight = self._cluster_weight_for(symbol, portfolio_value)

            adjusted = proposed_size_usd
            reason_parts: List[str] = []
            allowed = True

            # Gate 1: pair correlation
            if max_pair > self.max_pair_corr:
                allowed = False
                reason_parts.append(
                    f"pair_corr={max_pair:.2f} > limit={self.max_pair_corr:.2f}"
                )

            # Gate 2: portfolio-wide average correlation
            if portfolio_corr > self.max_portfolio_corr:
                allowed = False
                reason_parts.append(
                    f"portfolio_corr={portfolio_corr:.2f} > limit={self.max_portfolio_corr:.2f}"
                )

            # Gate 3: cluster weight
            if cluster_weight > self.max_cluster_weight:
                allowed = False
                reason_parts.append(
                    f"cluster_weight={cluster_weight:.2%} > limit={self.max_cluster_weight:.2%}"
                )

            # Size adjustment (even if allowed, reduce proportionally to corr)
            if allowed and max_pair > 0:
                reduction = max_pair * self.size_reduction_slope
                adjusted = proposed_size_usd * (1.0 - min(reduction, 0.75))
                if adjusted < proposed_size_usd:
                    reason_parts.append(
                        f"size reduced by {reduction:.0%} (pair_corr={max_pair:.2f})"
                    )

            reason = (
                " | ".join(reason_parts)
                if reason_parts
                else "correlation gate passed"
            )

            decision = CorrelationDecision(
                allowed=allowed,
                reason=reason,
                symbol=symbol,
                proposed_size_usd=proposed_size_usd,
                adjusted_size_usd=round(adjusted, 2),
                portfolio_corr_score=portfolio_corr,
                max_pair_corr=max_pair,
                active_clusters=clusters,
            )

            self._log_decision(decision)

            if not allowed:
                logger.warning("CRE blocked %s: %s", symbol, reason)
            else:
                logger.debug("CRE approved %s: %s", symbol, reason)

            return decision

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def get_status(self) -> CorrelationStatus:
        """Return a snapshot of current correlation risk."""
        with self._lock:
            self._rebuild_matrix_if_needed()
            clusters = self._detect_clusters()
            top_pairs = self._top_correlated_pairs(n=5)
            return CorrelationStatus(
                num_tracked_symbols=len(self._prices),
                num_active_positions=len(self._positions),
                portfolio_corr_score=self._portfolio_corr_score(),
                clusters=clusters,
                matrix_age_bars=self._matrix_age_bars,
                top_pairs=top_pairs,
            )

    def get_pair_correlation(self, sym1: str, sym2: str) -> Optional[float]:
        """Return the current correlation between two symbols, or None."""
        with self._lock:
            self._rebuild_matrix_if_needed()
            return self._lookup_corr(sym1, sym2)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_matrix_if_needed(self) -> None:
        """Recalculate the full correlation matrix if dirty."""
        if not self._matrix_dirty:
            return

        eligible = {
            sym: list(prices)
            for sym, prices in self._prices.items()
            if len(prices) >= self.min_history
        }

        if len(eligible) < 2:
            self._corr_matrix = None
            self._corr_symbols = []
            self._matrix_dirty = False
            return

        symbols = sorted(eligible.keys())
        min_len = min(len(eligible[s]) for s in symbols)
        # Use returns (percentage changes) for correlation
        # Build the full price array first, then diff in one vectorised operation
        price_array = np.array(
            [eligible[s][-min_len:] for s in symbols], dtype=float
        )  # shape: (n_symbols, min_len)
        returns = np.diff(price_array, axis=1)  # shape: (n_symbols, min_len - 1)

        if returns.shape[1] < 2:
            self._corr_matrix = None
            self._corr_symbols = []
            self._matrix_dirty = False
            return

        # numpy corrcoef; handle near-zero variance columns gracefully
        std = returns.std(axis=1)
        valid = std > 1e-10
        if valid.sum() < 2:
            self._corr_matrix = None
            self._corr_symbols = []
            self._matrix_dirty = False
            return

        valid_symbols = [s for s, v in zip(symbols, valid) if v]
        valid_returns = returns[valid]
        corr = np.corrcoef(valid_returns)
        # Leave diagonal at 1.0 (mathematically correct); self-correlation is
        # excluded in _portfolio_corr_score() and _max_pair_corr() by the
        # i < j / candidate-vs-position iteration patterns.

        self._corr_matrix = corr
        self._corr_symbols = valid_symbols
        self._matrix_dirty = False
        self._matrix_age_bars = 0
        logger.debug("CRE matrix rebuilt: %d symbols", len(valid_symbols))

    def _lookup_corr(self, sym1: str, sym2: str) -> Optional[float]:
        """Look up correlation from cached matrix; returns None for unknown pairs, 0.0 for self."""
        if sym1 == sym2:
            return 0.0
        if self._corr_matrix is None:
            return None
        syms = self._corr_symbols
        if sym1 not in syms or sym2 not in syms:
            return None
        i, j = syms.index(sym1), syms.index(sym2)
        return float(self._corr_matrix[i, j])

    def _portfolio_corr_score(self) -> float:
        """
        Average absolute pairwise correlation among active positions.

        Returns 0.0 if fewer than 2 active positions or no matrix.
        """
        pos_syms = list(self._positions.keys())
        if len(pos_syms) < 2 or self._corr_matrix is None:
            return 0.0

        total, count = 0.0, 0
        for i, s1 in enumerate(pos_syms):
            for s2 in pos_syms[i + 1:]:
                c = self._lookup_corr(s1, s2)
                if c is not None:
                    total += abs(c)
                    count += 1

        return total / count if count > 0 else 0.0

    def _max_pair_corr(self, candidate: str) -> float:
        """Return the max abs correlation of *candidate* vs any active position."""
        if self._corr_matrix is None:
            return 0.0
        max_corr = 0.0
        for pos_sym in self._positions:
            c = self._lookup_corr(candidate, pos_sym)
            if c is not None:
                max_corr = max(max_corr, abs(c))
        return max_corr

    def _detect_clusters(self) -> List[List[str]]:
        """
        Group symbols into clusters where abs(corr) ≥ cluster_threshold.

        Uses union-find over active positions only.
        """
        pos_syms = list(self._positions.keys())
        parent = {s: s for s in pos_syms}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: str, y: str) -> None:
            parent[find(x)] = find(y)

        for i, s1 in enumerate(pos_syms):
            for s2 in pos_syms[i + 1:]:
                c = self._lookup_corr(s1, s2)
                if c is not None and abs(c) >= self.cluster_threshold:
                    union(s1, s2)

        groups: Dict[str, List[str]] = {}
        for s in pos_syms:
            root = find(s)
            groups.setdefault(root, []).append(s)

        return [sorted(g) for g in groups.values() if len(g) >= 2]

    def _cluster_weight_for(self, candidate: str, portfolio_value: float) -> float:
        """
        Return the portfolio weight that would be occupied by the cluster
        containing *candidate* if it were added (using equal-weight proxy when
        no size is provided).
        """
        if portfolio_value <= 0:
            return 0.0
        # Find the cluster (among current positions) most correlated to candidate
        pos_syms = list(self._positions.keys())
        cluster: Set[str] = set()
        for pos_sym in pos_syms:
            c = self._lookup_corr(candidate, pos_sym)
            if c is not None and abs(c) >= self.cluster_threshold:
                cluster.add(pos_sym)

        if not cluster:
            return 0.0

        cluster_exposure = sum(self._positions.get(s, 0.0) for s in cluster)
        return cluster_exposure / portfolio_value

    def _top_correlated_pairs(self, n: int = 5) -> List[Tuple[str, str, float]]:
        """Return the top *n* most-correlated pairs (among tracked symbols)."""
        if self._corr_matrix is None:
            return []
        pairs: List[Tuple[str, str, float]] = []
        syms = self._corr_symbols
        for i, s1 in enumerate(syms):
            for j, s2 in enumerate(syms):
                if i < j:
                    pairs.append((s1, s2, float(self._corr_matrix[i, j])))
        pairs.sort(key=lambda x: abs(x[2]), reverse=True)
        return pairs[:n]

    def _log_decision(self, decision: CorrelationDecision) -> None:
        """Append decision to JSON-lines audit log."""
        try:
            record = {
                "timestamp": decision.timestamp,
                "symbol": decision.symbol,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "proposed_size_usd": decision.proposed_size_usd,
                "adjusted_size_usd": decision.adjusted_size_usd,
                "portfolio_corr_score": round(decision.portfolio_corr_score, 4),
                "max_pair_corr": round(decision.max_pair_corr, 4),
            }
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_cre_instance: Optional[CorrelationRiskEngine] = None
_cre_lock = threading.Lock()


def get_correlation_risk_engine(**kwargs) -> CorrelationRiskEngine:
    """Return the process-wide :class:`CorrelationRiskEngine` singleton."""
    global _cre_instance
    with _cre_lock:
        if _cre_instance is None:
            _cre_instance = CorrelationRiskEngine(**kwargs)
            logger.info("CorrelationRiskEngine singleton created")
    return _cre_instance
