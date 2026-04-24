"""
NIJA Symbol Performance Tracker
=================================

Tracks per-symbol trading statistics and provides adaptive position-size
multipliers, blacklisting of persistent losers, and prioritisation of
strong performers.

Tracked metrics (per symbol)
-----------------------------
* **Win rate**        — fraction of profitable trades
* **Avg return**      — mean PnL in USD per trade
* **Volatility**      — standard deviation of PnL
* **Failure rate**    — fraction of trades that hit stop-loss

Behaviour
---------
* **Strong symbols** (high win rate + positive avg return) receive a size
  multiplier > 1.0 to compound the edge.
* **Weak symbols** (low win rate or heavy losses) receive a reduced
  multiplier.
* **Blacklisted symbols** receive a 0.0 multiplier — entries are blocked.
  Symbols are auto-blacklisted when their score drops below
  ``blacklist_score_threshold`` after ``min_trades_to_score`` trades.
  They are auto-released after ``blacklist_cooldown_trades`` bot-wide trades
  have been recorded.

Score formula
-------------
::

    score = win_rate_weight × win_rate
          + return_weight   × norm_avg_return
          + volatility_weight × (1 − norm_volatility)
          + failure_weight  × (1 − failure_rate)

Scores are normalised to [0, 1] and mapped to a size multiplier in
[``min_multiplier``, ``max_multiplier``].

Singleton usage
---------------
::

    from bot.symbol_performance_tracker import get_symbol_performance_tracker

    tracker = get_symbol_performance_tracker()

    # After every closed trade:
    tracker.record_trade(
        symbol="BTC-USD",
        pnl_usd=42.0,
        is_win=True,
        hit_stop_loss=False,
        regime="BULL",
        confidence=0.78,
    )

    # Before sizing a new entry:
    mult = tracker.get_size_multiplier("BTC-USD")   # 0.0 = blacklisted
    if mult == 0.0:
        skip_entry()
    else:
        position_size *= mult

    # Prioritised / deprioritised symbol lists:
    top = tracker.get_top_symbols(n=10)
    bad = tracker.get_worst_symbols(n=10)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("nija.symbol_performance_tracker")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WINDOW: int = 50            # rolling window of trades per symbol
MIN_TRADES_TO_SCORE: int = 5        # need at least this many trades before scoring
BLACKLIST_SCORE_THRESHOLD: float = 0.25   # score below this → blacklist
BLACKLIST_COOLDOWN_TRADES: int = 20       # global trades before re-evaluating blacklisted symbols
MIN_MULTIPLIER: float = 0.40        # floor for weak (but non-blacklisted) symbols
MAX_MULTIPLIER: float = 1.50        # ceiling for strong symbols
NEUTRAL_MULTIPLIER: float = 1.00    # used when < min_trades data is available

# Normalisation reference values used in _compute_score().
# avg_return: mid-point 0, full-range ±$20 per trade.
#   At $0/trade → 0.5; at +$20 → 1.0; at -$20 → 0.0.
#   Adjust _SCORE_RETURN_MIDPOINT / _SCORE_RETURN_RANGE for higher-capital accounts.
_SCORE_RETURN_MIDPOINT: float = 0.0   # $0 avg return maps to 0.5 score
_SCORE_RETURN_RANGE: float = 20.0     # ±$20 covers the full [0, 1] return axis

# pnl_vol: $0 → ideal (1.0); $60 → fully noisy (0.0).
#   _SCORE_VOL_MAX is the PnL standard deviation considered maximally noisy.
_SCORE_VOL_MAX: float = 60.0          # $60 std-dev is treated as worst-case volatility


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """One trade outcome for a symbol."""
    pnl_usd: float
    is_win: bool
    hit_stop_loss: bool
    regime: str
    confidence: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SymbolStats:
    """Aggregated statistics for one symbol."""
    symbol: str
    trade_count: int
    win_rate: float          # 0–1
    avg_return_usd: float    # mean PnL per trade
    pnl_volatility: float    # std-dev of PnL
    failure_rate: float      # fraction that hit stop-loss
    score: float             # composite [0, 1]
    size_multiplier: float   # position-size scaling factor
    is_blacklisted: bool
    best_regime: str         # regime with highest win rate
    last_updated: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "trade_count": self.trade_count,
            "win_rate_pct": round(self.win_rate * 100, 1),
            "avg_return_usd": round(self.avg_return_usd, 2),
            "pnl_volatility": round(self.pnl_volatility, 2),
            "failure_rate_pct": round(self.failure_rate * 100, 1),
            "score": round(self.score, 4),
            "size_multiplier": round(self.size_multiplier, 4),
            "is_blacklisted": self.is_blacklisted,
            "best_regime": self.best_regime,
            "last_updated": self.last_updated.isoformat(),
        }


@dataclass
class TrackerConfig:
    """Tunable parameters for the symbol performance tracker."""
    window: int = DEFAULT_WINDOW
    min_trades_to_score: int = MIN_TRADES_TO_SCORE
    blacklist_score_threshold: float = BLACKLIST_SCORE_THRESHOLD
    blacklist_cooldown_trades: int = BLACKLIST_COOLDOWN_TRADES
    min_multiplier: float = MIN_MULTIPLIER
    max_multiplier: float = MAX_MULTIPLIER

    # Composite score weights (must sum to 1.0)
    win_rate_weight: float = 0.40
    return_weight: float = 0.30
    volatility_weight: float = 0.15
    failure_weight: float = 0.15


# ---------------------------------------------------------------------------
# Core tracker
# ---------------------------------------------------------------------------

class SymbolPerformanceTracker:
    """
    Tracks per-symbol win rate, return, volatility, and failure rate.
    Provides position-size multipliers, a blacklist for chronic losers,
    and ranked lists for symbol prioritisation.

    Thread-safe; use :func:`get_symbol_performance_tracker` for the
    process-wide singleton.
    """

    def __init__(self, config: Optional[TrackerConfig] = None) -> None:
        self._cfg = config or TrackerConfig()
        self._lock = threading.Lock()

        # symbol → deque of TradeRecords
        self._records: Dict[str, Deque[TradeRecord]] = {}

        # Blacklisted symbols + the global trade count when they were listed
        self._blacklist: Dict[str, int] = {}   # symbol → global_trade_count at blacklist time

        # Global trade counter (used for blacklist cooldown)
        self._global_trade_count: int = 0

        logger.info(
            "SymbolPerformanceTracker initialised | window=%d min_trades=%d "
            "blacklist_threshold=%.2f",
            self._cfg.window,
            self._cfg.min_trades_to_score,
            self._cfg.blacklist_score_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        symbol: str,
        pnl_usd: float,
        is_win: bool,
        hit_stop_loss: bool = False,
        regime: str = "UNKNOWN",
        confidence: float = 1.0,
    ) -> None:
        """
        Record the outcome of a closed trade for ``symbol``.

        Parameters
        ----------
        symbol:
            Trading pair, e.g. ``"BTC-USD"``.
        pnl_usd:
            Realised PnL in USD (negative for losses).
        is_win:
            ``True`` if the trade was profitable.
        hit_stop_loss:
            ``True`` if the trade was closed by stop-loss.
        regime:
            Market regime at entry (e.g. ``"BULL"``, ``"CHOP"``).
        confidence:
            Entry confidence score [0, 1].
        """
        with self._lock:
            self._global_trade_count += 1

            if symbol not in self._records:
                self._records[symbol] = deque(maxlen=self._cfg.window)

            self._records[symbol].append(
                TradeRecord(
                    pnl_usd=pnl_usd,
                    is_win=is_win,
                    hit_stop_loss=hit_stop_loss,
                    regime=regime,
                    confidence=confidence,
                )
            )

            # Re-evaluate blacklist status
            self._maybe_release_from_blacklist(symbol)
            self._maybe_blacklist(symbol)

    def get_size_multiplier(self, symbol: str) -> float:
        """
        Return the position-size multiplier for ``symbol``.

        Returns
        -------
        float
            * ``0.0`` — symbol is blacklisted, skip the entry.
            * ``< 1.0`` — below-average performance, reduce size.
            * ``1.0`` — neutral (insufficient data or average performer).
            * ``> 1.0`` — strong performer, increase size.
        """
        with self._lock:
            if symbol in self._blacklist:
                return 0.0
            stats = self._compute_stats(symbol)
            if stats is None:
                return NEUTRAL_MULTIPLIER
            return stats.size_multiplier

    def get_symbol_stats(self, symbol: str) -> Optional[SymbolStats]:
        """Return the full statistics object for ``symbol``, or ``None``."""
        with self._lock:
            return self._compute_stats(symbol)

    def get_top_symbols(self, n: int = 10) -> List[SymbolStats]:
        """Return the top ``n`` symbols sorted by composite score (descending)."""
        with self._lock:
            stats = [
                s for sym in self._records
                if (s := self._compute_stats(sym)) is not None
                and not s.is_blacklisted
            ]
            stats.sort(key=lambda s: s.score, reverse=True)
            return stats[:n]

    def get_worst_symbols(self, n: int = 10) -> List[SymbolStats]:
        """Return the worst ``n`` symbols sorted by composite score (ascending)."""
        with self._lock:
            stats = [
                s for sym in self._records
                if (s := self._compute_stats(sym)) is not None
            ]
            stats.sort(key=lambda s: s.score)
            return stats[:n]

    def get_blacklisted_symbols(self) -> List[str]:
        """Return the list of currently blacklisted symbols."""
        with self._lock:
            return list(self._blacklist.keys())

    def unblacklist(self, symbol: str) -> None:
        """Manually remove ``symbol`` from the blacklist."""
        with self._lock:
            if symbol in self._blacklist:
                del self._blacklist[symbol]
                logger.info("Symbol %s manually removed from blacklist", symbol)

    def get_report(self) -> Dict[str, Any]:
        """Return a serialisable summary of tracked symbols."""
        with self._lock:
            all_stats = [
                s for sym in self._records
                if (s := self._compute_stats(sym)) is not None
            ]
            all_stats.sort(key=lambda s: s.score, reverse=True)
            return {
                "total_symbols_tracked": len(self._records),
                "blacklisted_count": len(self._blacklist),
                "global_trade_count": self._global_trade_count,
                "blacklisted": list(self._blacklist.keys()),
                "top_10": [s.to_dict() for s in all_stats[:10]],
                "bottom_10": [s.to_dict() for s in all_stats[-10:]],
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_stats(self, symbol: str) -> Optional[SymbolStats]:
        """Compute :class:`SymbolStats` for ``symbol`` (caller holds lock)."""
        records = self._records.get(symbol)
        if not records:
            return None

        n = len(records)
        is_blacklisted = symbol in self._blacklist

        pnl_list = [r.pnl_usd for r in records]
        wins = sum(1 for r in records if r.is_win)
        stops = sum(1 for r in records if r.hit_stop_loss)

        win_rate = wins / n
        avg_return = sum(pnl_list) / n
        failure_rate = stops / n

        # PnL standard deviation
        if n > 1:
            mean = avg_return
            variance = sum((p - mean) ** 2 for p in pnl_list) / (n - 1)
            pnl_vol = math.sqrt(variance)
        else:
            pnl_vol = 0.0

        # Best regime (by win rate)
        regime_wins: Dict[str, int] = {}
        regime_counts: Dict[str, int] = {}
        for r in records:
            regime_counts[r.regime] = regime_counts.get(r.regime, 0) + 1
            if r.is_win:
                regime_wins[r.regime] = regime_wins.get(r.regime, 0) + 1
        best_regime = "UNKNOWN"
        if regime_counts:
            best_regime = max(
                regime_counts,
                key=lambda reg: regime_wins.get(reg, 0) / max(regime_counts[reg], 1),
            )

        if n < self._cfg.min_trades_to_score:
            score = 0.5
            size_mult = NEUTRAL_MULTIPLIER
        else:
            score = self._compute_score(win_rate, avg_return, pnl_vol, failure_rate)
            size_mult = self._score_to_multiplier(score) if not is_blacklisted else 0.0

        return SymbolStats(
            symbol=symbol,
            trade_count=n,
            win_rate=win_rate,
            avg_return_usd=avg_return,
            pnl_volatility=pnl_vol,
            failure_rate=failure_rate,
            score=score,
            size_multiplier=size_mult,
            is_blacklisted=is_blacklisted,
            best_regime=best_regime,
            last_updated=list(records)[-1].timestamp,
        )

    def _compute_score(
        self,
        win_rate: float,
        avg_return: float,
        pnl_vol: float,
        failure_rate: float,
    ) -> float:
        """
        Combine the four metrics into a composite score in [0, 1].

        avg_return and pnl_vol are normalised by a fixed reference so the
        score is interpretable even before many symbols have been seen.
        """
        cfg = self._cfg

        # Normalise avg_return using reference midpoint and range
        norm_return = min(
            1.0,
            max(
                0.0,
                (avg_return - _SCORE_RETURN_MIDPOINT + _SCORE_RETURN_RANGE)
                / (2.0 * _SCORE_RETURN_RANGE),
            ),
        )

        # Normalise volatility: $0 → 1.0 (ideal), _SCORE_VOL_MAX → 0.0 (very noisy)
        norm_vol_inv = min(1.0, max(0.0, 1.0 - pnl_vol / _SCORE_VOL_MAX))

        score = (
            cfg.win_rate_weight   * win_rate
            + cfg.return_weight   * norm_return
            + cfg.volatility_weight * norm_vol_inv
            + cfg.failure_weight  * (1.0 - failure_rate)
        )
        return min(1.0, max(0.0, score))

    def _score_to_multiplier(self, score: float) -> float:
        """
        Map composite score [0, 1] → size multiplier [min_mult, max_mult].

        score = 0.5 → 1.0 (neutral)
        score = 1.0 → max_multiplier
        score = 0.0 → min_multiplier
        """
        cfg = self._cfg
        s = max(0.0, min(1.0, score))
        if s >= 0.5:
            return 1.0 + (cfg.max_multiplier - 1.0) * ((s - 0.5) / 0.5)
        return cfg.min_multiplier + (1.0 - cfg.min_multiplier) * (s / 0.5)

    def _maybe_blacklist(self, symbol: str) -> None:
        """Blacklist ``symbol`` if its score is persistently poor."""
        if symbol in self._blacklist:
            return
        records = self._records.get(symbol)
        if not records or len(records) < self._cfg.min_trades_to_score:
            return

        stats = self._compute_stats(symbol)
        if stats and stats.score < self._cfg.blacklist_score_threshold:
            self._blacklist[symbol] = self._global_trade_count
            logger.warning(
                "Symbol %s BLACKLISTED — score=%.3f below threshold=%.3f",
                symbol, stats.score, self._cfg.blacklist_score_threshold,
            )

    def _maybe_release_from_blacklist(self, symbol: str) -> None:
        """Release ``symbol`` if the cooldown period has elapsed."""
        if symbol not in self._blacklist:
            return
        listed_at = self._blacklist[symbol]
        trades_since = self._global_trade_count - listed_at
        if trades_since >= self._cfg.blacklist_cooldown_trades:
            del self._blacklist[symbol]
            logger.info(
                "Symbol %s removed from blacklist after %d global trades cooldown",
                symbol, self._cfg.blacklist_cooldown_trades,
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_TRACKER_INSTANCE: Optional[SymbolPerformanceTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_symbol_performance_tracker(
    config: Optional[TrackerConfig] = None,
) -> SymbolPerformanceTracker:
    """
    Return the process-wide :class:`SymbolPerformanceTracker` singleton.

    ``config`` is only applied on the first call; subsequent calls return the
    existing instance regardless of the arguments passed.
    """
    global _TRACKER_INSTANCE
    with _TRACKER_LOCK:
        if _TRACKER_INSTANCE is None:
            _TRACKER_INSTANCE = SymbolPerformanceTracker(config)
    return _TRACKER_INSTANCE


__all__ = [
    "TrackerConfig",
    "TradeRecord",
    "SymbolStats",
    "SymbolPerformanceTracker",
    "get_symbol_performance_tracker",
]
