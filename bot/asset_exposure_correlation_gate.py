"""
NIJA Asset Exposure Correlation Gate
=====================================

Second-layer correlation control that prevents crypto-wide exposure spikes
caused by strategies that trade **different symbols but highly correlated
assets**.

Problem
-------
Two strategies can have uncorrelated *return histories* yet still create
concentrated directional risk::

    Strategy A (RSI_9)  → Long BTC-USD   ─┐
                                           ├─ BTC & ETH are ≈0.90 correlated
    Strategy B (RSI_14) → Long ETH-USD   ─┘

The existing ``CrossStrategyCorrelationRisk`` layer (strategy-return based)
might not catch this because RSI_9 and RSI_14 trade at different cadences.
This engine operates at the **symbol level**: it checks whether the proposed
symbol is highly correlated with any symbol already held by any active peer
strategy, regardless of how those strategies' return histories relate.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │               AssetExposureCorrelationGate                    │
  │                                                               │
  │  Layer 1 (existing): CrossStrategyCorrelationRisk             │
  │      – gates based on strategy *return* correlations          │
  │                                                               │
  │  Layer 2 (this module): AssetExposureCorrelationGate          │
  │      – gates based on *symbol price* correlations             │
  │                                                               │
  │  Data Structures                                              │
  │  ├── Price Store   : symbol → deque of close prices           │
  │  ├── Position Map  : strategy → {symbol: size_usd}            │
  │  └── Corr Matrix   : lazily rebuilt from price returns        │
  │                                                               │
  │  Three Gates                                                  │
  │  ├── Gate 1 – Symbol-Pair   : candidate corr vs any peer     │
  │  │            symbol > max_symbol_pair_corr → block           │
  │  ├── Gate 2 – Cluster Wt.  : correlated cluster share of     │
  │  │            portfolio > max_cluster_exposure_pct → block    │
  │  └── Gate 3 – Portfolio     : average cross-strategy symbol  │
  │               corr > max_portfolio_symbol_corr → block        │
  │                                                               │
  │  Proportional Size Reduction                                  │
  │      Even approved entries are scaled down when peer symbol  │
  │      correlation is elevated.                                 │
  │                                                               │
  │  Audit Log                                                    │
  │      Every decision appended as JSON-lines to                │
  │      data/asset_exposure_correlation_decisions.jsonl          │
  └──────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.asset_exposure_correlation_gate import (
        get_asset_exposure_correlation_gate,
    )

    gate = get_asset_exposure_correlation_gate()

    # Feed price data each bar (call for every symbol you track):
    gate.update_price("BTC-USD", close_price=62_000.0)
    gate.update_price("ETH-USD", close_price=3_200.0)

    # When Strategy A opens a BTC position:
    gate.register_position("RSI_9", "BTC-USD", size_usd=1_000.0)

    # Before Strategy B tries to open an ETH position:
    decision = gate.approve_entry(
        strategy="RSI_14",
        symbol="ETH-USD",
        proposed_size_usd=800.0,
        portfolio_value=10_000.0,
    )
    if not decision.allowed:
        logger.warning("Asset exposure gate blocked: %s", decision.reason)
        return

    # When the position closes:
    gate.remove_position("RSI_9", "BTC-USD")

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
from typing import Deque, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger("nija.asset_exposure_correlation_gate")

# ---------------------------------------------------------------------------
# Constants – all overridable via constructor kwargs
# ---------------------------------------------------------------------------

DEFAULT_LOOKBACK: int = 60              # price bars to retain per symbol
DEFAULT_MIN_HISTORY: int = 20           # minimum bars before computing correlation
DEFAULT_MAX_SYMBOL_PAIR_CORR: float = 0.80   # block if candidate corr vs any peer > this
DEFAULT_MAX_PORTFOLIO_SYMBOL_CORR: float = 0.65  # block if avg cross-strategy corr > this
DEFAULT_CLUSTER_THRESHOLD: float = 0.70        # abs(corr) ≥ this → same cluster
DEFAULT_MAX_CLUSTER_EXPOSURE_PCT: float = 0.40  # max portfolio % in one correlated cluster
DEFAULT_SIZE_REDUCTION_SLOPE: float = 0.5      # how aggressively to shrink at max corr

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class AssetExposureDecision:
    """Result returned by :meth:`AssetExposureCorrelationGate.approve_entry`."""

    allowed: bool
    reason: str
    strategy: str
    symbol: str
    proposed_size_usd: float
    adjusted_size_usd: float
    max_peer_symbol_corr: float   # highest corr of proposed symbol vs any peer symbol
    portfolio_symbol_corr: float  # avg abs cross-strategy symbol correlation
    correlated_peers: List[Tuple[str, str, float]] = field(
        default_factory=list
    )  # [(peer_strategy, peer_symbol, corr), ...]
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class AssetExposureStatus:
    """Snapshot returned by :meth:`AssetExposureCorrelationGate.get_status`."""

    num_tracked_symbols: int
    num_active_strategies: int
    active_positions: Dict[str, Dict[str, float]]  # strategy → {symbol: size_usd}
    portfolio_symbol_corr: float
    top_correlated_pairs: List[Tuple[str, str, float]]  # (sym1, sym2, corr)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class AssetExposureCorrelationGate:
    """
    Second-layer correlation gate that checks symbol-level price correlations
    across strategies before approving a new position entry.

    Unlike ``CrossStrategyCorrelationRisk`` (which uses strategy *return*
    histories), this engine uses *symbol price* histories and the mapping of
    which strategy holds which symbol.  This catches the classic case where
    Strategy A trades BTC and Strategy B trades ETH – two uncorrelated
    strategies creating highly correlated directional exposure.

    Parameters
    ----------
    lookback : int
        Number of close-price bars to retain per symbol (default 60).
    min_history : int
        Minimum bars required before correlation can be estimated (default 20).
        Below this threshold the gate passes (fail-open at startup).
    max_symbol_pair_corr : float
        Block if the proposed symbol correlates above this level with any
        symbol held by an active peer strategy (default 0.80).
    max_portfolio_symbol_corr : float
        Block if the portfolio-wide average cross-strategy symbol correlation
        exceeds this level (default 0.65).
    cluster_threshold : float
        abs(corr) ≥ this marks two symbols as the same cluster (default 0.70).
    max_cluster_exposure_pct : float
        Maximum portfolio fraction (0–1) allowed in one correlated cluster
        (default 0.40).
    size_reduction_slope : float
        Fraction of proposed size shed proportionally to peer correlation when
        entry is allowed but correlation is elevated (default 0.5 → up to 50%
        reduction at max_symbol_pair_corr).
    """

    def __init__(
        self,
        lookback: int = DEFAULT_LOOKBACK,
        min_history: int = DEFAULT_MIN_HISTORY,
        max_symbol_pair_corr: float = DEFAULT_MAX_SYMBOL_PAIR_CORR,
        max_portfolio_symbol_corr: float = DEFAULT_MAX_PORTFOLIO_SYMBOL_CORR,
        cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
        max_cluster_exposure_pct: float = DEFAULT_MAX_CLUSTER_EXPOSURE_PCT,
        size_reduction_slope: float = DEFAULT_SIZE_REDUCTION_SLOPE,
    ) -> None:
        self.lookback = lookback
        self.min_history = min_history
        self.max_symbol_pair_corr = max_symbol_pair_corr
        self.max_portfolio_symbol_corr = max_portfolio_symbol_corr
        self.cluster_threshold = cluster_threshold
        self.max_cluster_exposure_pct = max_cluster_exposure_pct
        self.size_reduction_slope = size_reduction_slope

        # price history: symbol → deque of close prices
        self._prices: Dict[str, Deque[float]] = {}
        # position map: strategy → {symbol: size_usd}
        self._positions: Dict[str, Dict[str, float]] = {}
        # cached correlation matrix (lazily rebuilt)
        self._corr_matrix: Optional[np.ndarray] = None
        self._corr_symbols: List[str] = []
        self._matrix_dirty: bool = True

        self._lock = threading.RLock()

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = DATA_DIR / "asset_exposure_correlation_decisions.jsonl"

        logger.info(
            "AssetExposureCorrelationGate initialised "
            "(max_symbol_pair_corr=%.2f, max_portfolio_symbol_corr=%.2f, lookback=%d)",
            max_symbol_pair_corr,
            max_portfolio_symbol_corr,
            lookback,
        )

    # ------------------------------------------------------------------
    # Price ingestion
    # ------------------------------------------------------------------

    def update_price(self, symbol: str, close_price: float) -> None:
        """Record the latest close price for *symbol*.

        Call this every bar for every symbol you want to track.  The rolling
        window is capped at ``lookback`` bars.
        """
        with self._lock:
            if symbol not in self._prices:
                self._prices[symbol] = deque(maxlen=self.lookback)
            self._prices[symbol].append(float(close_price))
            self._matrix_dirty = True

    def update_prices_bulk(self, prices: Dict[str, float]) -> None:
        """Convenience wrapper – update multiple symbols at once."""
        for sym, px in prices.items():
            self.update_price(sym, px)

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def register_position(
        self, strategy: str, symbol: str, size_usd: float
    ) -> None:
        """Record that *strategy* has opened a position in *symbol*.

        Parameters
        ----------
        strategy : str
            Unique strategy identifier (e.g. ``"RSI_9"``).
        symbol : str
            Trading pair (e.g. ``"BTC-USD"``).
        size_usd : float
            Position size in USD.
        """
        with self._lock:
            if strategy not in self._positions:
                self._positions[strategy] = {}
            self._positions[strategy][symbol] = float(size_usd)
            logger.info(
                "AECG: registered %s → %s $%.2f", strategy, symbol, size_usd
            )

    def remove_position(
        self, strategy: str, symbol: Optional[str] = None
    ) -> None:
        """Remove one or all positions for *strategy*.

        Parameters
        ----------
        strategy : str
            The strategy whose position is being closed.
        symbol : str, optional
            If provided, only this symbol is removed.  If omitted, all
            positions for the strategy are removed (full strategy close).
        """
        with self._lock:
            if strategy not in self._positions:
                return
            if symbol is None:
                del self._positions[strategy]
                logger.info("AECG: removed all positions for %s", strategy)
            else:
                self._positions[strategy].pop(symbol, None)
                if not self._positions[strategy]:
                    del self._positions[strategy]
                logger.info("AECG: removed %s → %s", strategy, symbol)

    def update_position_size(
        self, strategy: str, symbol: str, new_size_usd: float
    ) -> None:
        """Update the size of an existing open position."""
        with self._lock:
            if strategy in self._positions and symbol in self._positions[strategy]:
                self._positions[strategy][symbol] = float(new_size_usd)

    # ------------------------------------------------------------------
    # Core gate
    # ------------------------------------------------------------------

    def approve_entry(
        self,
        strategy: str,
        symbol: str,
        proposed_size_usd: float,
        portfolio_value: float,
    ) -> AssetExposureDecision:
        """
        Decide whether a new position from *strategy* in *symbol* is acceptable
        given the **symbol-level** correlation exposure of all active peer
        strategies.

        This is the second-layer check.  It gates on asset price correlation
        rather than strategy return correlation, catching the classic scenario
        where Strategy A is long BTC and Strategy B wants to go long ETH – two
        assets that are historically ~0.90 correlated – even if the strategies
        themselves behave independently.

        Parameters
        ----------
        strategy : str
            The strategy requesting a new entry.
        symbol : str
            The symbol the strategy wants to trade.
        proposed_size_usd : float
            Requested position size in USD.
        portfolio_value : float
            Total portfolio value in USD (used for cluster weight calculation).

        Returns
        -------
        AssetExposureDecision
            Rich result with ``allowed`` flag, ``adjusted_size_usd``, and
            diagnostics including which peer strategies contributed correlation.
        """
        with self._lock:
            self._rebuild_matrix_if_needed()

            # Collect symbols held by OTHER strategies
            peer_symbols: Dict[str, Tuple[str, float]] = {}  # symbol → (strategy, size_usd)
            for peer_strat, positions in self._positions.items():
                if peer_strat == strategy:
                    continue
                for peer_sym, peer_size in positions.items():
                    if peer_sym != symbol:
                        peer_symbols[peer_sym] = (peer_strat, peer_size)

            max_peer_corr, correlated_peers = self._max_peer_symbol_corr(
                symbol, peer_symbols
            )
            portfolio_corr = self._portfolio_symbol_corr_score()
            cluster_weight = self._cluster_exposure(symbol, peer_symbols, portfolio_value)

            adjusted = proposed_size_usd
            reason_parts: List[str] = []
            allowed = True

            # Gate 1: symbol-pair correlation with any active peer symbol
            if max_peer_corr > self.max_symbol_pair_corr:
                allowed = False
                worst = (
                    correlated_peers[0] if correlated_peers else ("?", "?", max_peer_corr)
                )
                reason_parts.append(
                    f"symbol_pair_corr={max_peer_corr:.2f} > limit={self.max_symbol_pair_corr:.2f}"
                    f" (peer: {worst[0]}/{worst[1]})"
                )

            # Gate 2: cluster exposure
            if cluster_weight > self.max_cluster_exposure_pct:
                allowed = False
                reason_parts.append(
                    f"cluster_exposure={cluster_weight:.2%} > limit={self.max_cluster_exposure_pct:.2%}"
                )

            # Gate 3: portfolio-wide average cross-strategy symbol correlation
            if portfolio_corr > self.max_portfolio_symbol_corr:
                allowed = False
                reason_parts.append(
                    f"portfolio_symbol_corr={portfolio_corr:.2f} > limit={self.max_portfolio_symbol_corr:.2f}"
                )

            # Proportional size reduction even when entry is approved
            if allowed and max_peer_corr > 0:
                reduction = max_peer_corr * self.size_reduction_slope
                adjusted = proposed_size_usd * (1.0 - min(reduction, 0.75))
                if adjusted < proposed_size_usd:
                    reason_parts.append(
                        f"size reduced by {reduction:.0%} (symbol_pair_corr={max_peer_corr:.2f})"
                    )

            reason = (
                " | ".join(reason_parts)
                if reason_parts
                else "asset exposure gate passed"
            )

            decision = AssetExposureDecision(
                allowed=allowed,
                reason=reason,
                strategy=strategy,
                symbol=symbol,
                proposed_size_usd=proposed_size_usd,
                adjusted_size_usd=round(adjusted, 2),
                max_peer_symbol_corr=round(max_peer_corr, 4),
                portfolio_symbol_corr=round(portfolio_corr, 4),
                correlated_peers=correlated_peers,
            )

            self._log_decision(decision)

            if not allowed:
                logger.warning(
                    "AECG blocked %s/%s: %s", strategy, symbol, reason
                )
            else:
                logger.debug(
                    "AECG approved %s/%s: %s", strategy, symbol, reason
                )

            return decision

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def get_status(self) -> AssetExposureStatus:
        """Return a diagnostic snapshot of current asset exposure correlation."""
        with self._lock:
            self._rebuild_matrix_if_needed()
            return AssetExposureStatus(
                num_tracked_symbols=len(self._prices),
                num_active_strategies=len(self._positions),
                active_positions={
                    strat: dict(syms)
                    for strat, syms in self._positions.items()
                },
                portfolio_symbol_corr=self._portfolio_symbol_corr_score(),
                top_correlated_pairs=self._top_correlated_pairs(n=5),
            )

    def get_symbol_correlation(self, sym1: str, sym2: str) -> Optional[float]:
        """Return the current price correlation between *sym1* and *sym2*, or None."""
        with self._lock:
            self._rebuild_matrix_if_needed()
            return self._lookup_corr(sym1, sym2)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_matrix_if_needed(self) -> None:
        """Recalculate the full correlation matrix if the price store is dirty."""
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
        price_array = np.array(
            [eligible[s][-min_len:] for s in symbols], dtype=float
        )
        returns = np.diff(price_array, axis=1)

        if returns.shape[1] < 2:
            self._corr_matrix = None
            self._corr_symbols = []
            self._matrix_dirty = False
            return

        std = returns.std(axis=1)
        valid_mask = std > 1e-10
        if valid_mask.sum() < 2:
            self._corr_matrix = None
            self._corr_symbols = []
            self._matrix_dirty = False
            return

        valid_symbols = [s for s, v in zip(symbols, valid_mask) if v]
        valid_returns = returns[valid_mask]
        self._corr_matrix = np.corrcoef(valid_returns)
        self._corr_symbols = valid_symbols
        self._matrix_dirty = False
        logger.debug("AECG matrix rebuilt: %d symbols", len(valid_symbols))

    def _lookup_corr(self, sym1: str, sym2: str) -> Optional[float]:
        """Return correlation between sym1 and sym2 from the cached matrix."""
        if sym1 == sym2:
            return 1.0
        if self._corr_matrix is None:
            return None
        syms = self._corr_symbols
        if sym1 not in syms or sym2 not in syms:
            return None
        i, j = syms.index(sym1), syms.index(sym2)
        return float(self._corr_matrix[i, j])

    def _max_peer_symbol_corr(
        self,
        candidate: str,
        peer_symbols: Dict[str, Tuple[str, float]],
    ) -> Tuple[float, List[Tuple[str, str, float]]]:
        """
        Return the maximum abs correlation of *candidate* vs all peer symbols,
        along with a sorted list of (peer_strategy, peer_symbol, corr) triples.
        """
        if self._corr_matrix is None or not peer_symbols:
            return 0.0, []

        results: List[Tuple[str, str, float]] = []
        for peer_sym, (peer_strat, _size) in peer_symbols.items():
            c = self._lookup_corr(candidate, peer_sym)
            if c is not None:
                results.append((peer_strat, peer_sym, abs(c)))

        if not results:
            return 0.0, []

        results.sort(key=lambda x: x[2], reverse=True)
        max_corr = results[0][2]
        return max_corr, results

    def _portfolio_symbol_corr_score(self) -> float:
        """
        Average absolute correlation between ALL (strategy, symbol) pairs across
        different strategies.

        Returns 0.0 when fewer than two different strategy symbols are active,
        or when the matrix is not yet available.
        """
        if self._corr_matrix is None:
            return 0.0

        # Collect one symbol per strategy (or all – include all positions)
        all_pairs: List[Tuple[str, str]] = []  # pairs of symbols from different strategies
        strats = list(self._positions.keys())
        for i, s1 in enumerate(strats):
            for s2 in strats[i + 1:]:
                for sym1 in self._positions[s1]:
                    for sym2 in self._positions[s2]:
                        all_pairs.append((sym1, sym2))

        if not all_pairs:
            return 0.0

        total, count = 0.0, 0
        for sym1, sym2 in all_pairs:
            c = self._lookup_corr(sym1, sym2)
            if c is not None:
                total += abs(c)
                count += 1

        return total / count if count > 0 else 0.0

    def _cluster_exposure(
        self,
        candidate: str,
        peer_symbols: Dict[str, Tuple[str, float]],
        portfolio_value: float,
    ) -> float:
        """
        Return the portfolio weight that would be held in the correlated
        cluster containing *candidate* if it were added.
        """
        if portfolio_value <= 0:
            return 0.0

        cluster_usd = 0.0
        for peer_sym, (peer_strat, peer_size) in peer_symbols.items():
            c = self._lookup_corr(candidate, peer_sym)
            if c is not None and abs(c) >= self.cluster_threshold:
                cluster_usd += peer_size

        return cluster_usd / portfolio_value

    def _top_correlated_pairs(self, n: int = 5) -> List[Tuple[str, str, float]]:
        """Return the *n* most correlated symbol pairs from the tracked universe."""
        if self._corr_matrix is None:
            return []
        syms = self._corr_symbols
        pairs: List[Tuple[str, str, float]] = []
        for i, s1 in enumerate(syms):
            for j, s2 in enumerate(syms):
                if i < j:
                    pairs.append((s1, s2, float(self._corr_matrix[i, j])))
        pairs.sort(key=lambda x: abs(x[2]), reverse=True)
        return pairs[:n]

    def _log_decision(self, decision: AssetExposureDecision) -> None:
        """Append the decision to the JSON-lines audit log."""
        try:
            record = {
                "timestamp": decision.timestamp,
                "strategy": decision.strategy,
                "symbol": decision.symbol,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "proposed_size_usd": decision.proposed_size_usd,
                "adjusted_size_usd": decision.adjusted_size_usd,
                "max_peer_symbol_corr": decision.max_peer_symbol_corr,
                "portfolio_symbol_corr": decision.portfolio_symbol_corr,
                "correlated_peers": [
                    {"strategy": p[0], "symbol": p[1], "corr": round(p[2], 4)}
                    for p in decision.correlated_peers
                ],
            }
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_aecg_instance: Optional[AssetExposureCorrelationGate] = None
_aecg_lock = threading.Lock()


def get_asset_exposure_correlation_gate(**kwargs) -> AssetExposureCorrelationGate:
    """Return the process-wide :class:`AssetExposureCorrelationGate` singleton."""
    global _aecg_instance
    with _aecg_lock:
        if _aecg_instance is None:
            _aecg_instance = AssetExposureCorrelationGate(**kwargs)
            logger.info("AssetExposureCorrelationGate singleton created")
    return _aecg_instance
