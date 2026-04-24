"""
NIJA Symbol Intelligence Memory
=================================

Per-symbol self-learning memory engine.  For every trading pair the bot has
ever touched, the engine maintains a rich performance profile and uses it to:

1. **Score symbols** before entry — historical win-rate and profit-factor
   surface the best setups automatically.
2. **Rank symbols by regime** — each market regime has a different leader-board
   (e.g., BTC-USD may dominate trending markets while DOGE-USD excels in
   volatile regimes).
3. **Detect underperforming symbols** — automatically flag pairs that
   consistently lose money so they can be deprioritised.
4. **Provide per-symbol intelligence reports** — concise, human-readable
   summaries of a symbol's trading history.

Key Features
------------
* Per-symbol aggregated stats: total trades, win rate, average PnL, profit
  factor, average holding hours, fees paid.
* Per-symbol × per-regime breakdown (trending / ranging / volatile …).
* Per-symbol × per-strategy breakdown.
* EMA-smoothed composite score (0–100) used for symbol prioritisation.
* Automatic blacklist recommendation when a symbol's composite score drops
  below a configurable floor.
* Thread-safe with ``threading.RLock``.
* JSON-persistent state survives bot restarts.

Usage
-----
::

    from bot.symbol_intelligence_memory import get_symbol_intelligence_memory

    sim = get_symbol_intelligence_memory()

    # Record a completed trade
    sim.record_trade(
        trade_id="abc123",
        symbol="BTC-USD",
        strategy="ApexTrend",
        side="long",
        entry_price=42_000.0,
        exit_price=43_500.0,
        position_size_usd=500.0,
        pnl=18.50,
        fees=1.05,
        market_regime="BULL_TRENDING",
        holding_hours=4.5,
    )

    # Score a symbol before entry
    result = sim.score_symbol("BTC-USD", regime="BULL_TRENDING", strategy="ApexTrend")
    if result["recommendation"] == "AVOID":
        skip_trade()

    # Retrieve top-performing symbols for current regime
    top = sim.get_top_symbols(n=10, regime="BULL_TRENDING")

    # Full memory report
    report = sim.get_full_report()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.symbol_intelligence_memory")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMA_DECAY = 0.88             # EMA smoothing factor (higher = more weight on historical EMA, i.e. slower adaptation)
MIN_TRADES_FOR_SCORE = 3     # minimum trades before a meaningful score is emitted
LOW_SCORE_THRESHOLD = 25.0   # composite score below this → AVOID recommendation
HIGH_SCORE_THRESHOLD = 65.0  # composite score above this → PREFERRED recommendation
MAX_SYMBOLS = 2_000          # cap the number of symbols tracked in memory

DATA_DIR = Path(__file__).parent.parent / "data"
STATE_FILE = DATA_DIR / "symbol_intelligence_memory.json"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SymbolRegimeStats:
    """Aggregated statistics for one (symbol, regime) bucket."""
    regime: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    total_holding_hours: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total_trades if self.total_trades else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gross_profit / self.gross_loss if self.gross_loss > 0 else float("inf")

    @property
    def avg_holding_hours(self) -> float:
        return self.total_holding_hours / self.total_trades if self.total_trades else 0.0

    def update(
        self,
        pnl: float,
        fees: float,
        holding_hours: float,
    ) -> None:
        self.total_trades += 1
        if pnl > 0:
            self.wins += 1
            self.gross_profit += pnl
        else:
            self.losses += 1
            self.gross_loss += abs(pnl)
        self.total_pnl += pnl
        self.total_fees += fees
        self.total_holding_hours += holding_hours

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": round(self.total_pnl, 4),
            "total_fees": round(self.total_fees, 4),
            "win_rate": round(self.win_rate, 4),
            "avg_pnl": round(self.avg_pnl, 4),
            "profit_factor": round(self.profit_factor, 4) if math.isfinite(self.profit_factor) else None,
            "avg_holding_hours": round(self.avg_holding_hours, 2),
        }


@dataclass
class SymbolStrategyStats:
    """Aggregated statistics for one (symbol, strategy) bucket."""
    strategy: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total_trades if self.total_trades else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gross_profit / self.gross_loss if self.gross_loss > 0 else float("inf")

    def update(self, pnl: float) -> None:
        self.total_trades += 1
        if pnl > 0:
            self.wins += 1
            self.gross_profit += pnl
        else:
            self.losses += 1
            self.gross_loss += abs(pnl)
        self.total_pnl += pnl

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": round(self.total_pnl, 4),
            "win_rate": round(self.win_rate, 4),
            "avg_pnl": round(self.avg_pnl, 4),
            "profit_factor": round(self.profit_factor, 4) if math.isfinite(self.profit_factor) else None,
        }


@dataclass
class SymbolStats:
    """
    Complete performance profile for a single trading symbol.

    The ``ema_score`` (0–100) is a composite EMA-smoothed metric blending
    win-rate, profit-factor, and average PnL.  It is updated on every
    ``record_trade`` call and used for symbol ranking and recommendations.
    """

    symbol: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    total_holding_hours: float = 0.0
    ema_score: float = 50.0          # starts neutral
    last_trade_ts: str = ""
    first_trade_ts: str = ""

    # Nested breakdowns (serialised separately)
    regime_stats: Dict[str, SymbolRegimeStats] = field(default_factory=dict)
    strategy_stats: Dict[str, SymbolStrategyStats] = field(default_factory=dict)

    # ── Derived properties ──────────────────────────────────────────────

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total_trades if self.total_trades else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gross_profit / self.gross_loss if self.gross_loss > 0 else float("inf")

    @property
    def avg_holding_hours(self) -> float:
        return self.total_holding_hours / self.total_trades if self.total_trades else 0.0

    @property
    def avg_fee_per_trade(self) -> float:
        return self.total_fees / self.total_trades if self.total_trades else 0.0

    # ── Mutators ─────────────────────────────────────────────────────────

    def update(
        self,
        pnl: float,
        fees: float,
        holding_hours: float,
        regime: str,
        strategy: str,
        trade_ts: str,
    ) -> None:
        """Ingest one completed trade and update all aggregates."""
        self.total_trades += 1
        if pnl > 0:
            self.wins += 1
            self.gross_profit += pnl
        else:
            self.losses += 1
            self.gross_loss += abs(pnl)
        self.total_pnl += pnl
        self.total_fees += fees
        self.total_holding_hours += holding_hours

        if not self.first_trade_ts:
            self.first_trade_ts = trade_ts
        self.last_trade_ts = trade_ts

        # Regime breakdown
        if regime not in self.regime_stats:
            self.regime_stats[regime] = SymbolRegimeStats(regime=regime)
        self.regime_stats[regime].update(pnl=pnl, fees=fees, holding_hours=holding_hours)

        # Strategy breakdown
        if strategy not in self.strategy_stats:
            self.strategy_stats[strategy] = SymbolStrategyStats(strategy=strategy)
        self.strategy_stats[strategy].update(pnl=pnl)

        # Update EMA score
        self._refresh_ema_score()

    def _refresh_ema_score(self) -> None:
        """Recompute the EMA composite score (0–100)."""
        if self.total_trades < 1:
            return

        # Win-rate component (0–1 → 0–40 pts)
        wr_part = self.win_rate * 40.0

        # Profit-factor component (capped and scaled to 0–35 pts)
        pf = min(self.profit_factor, 5.0) if math.isfinite(self.profit_factor) else 5.0
        pf_part = ((pf - 1.0) / 4.0) * 35.0  # 0 when PF=1, 35 when PF=5
        pf_part = max(0.0, pf_part)

        # Average PnL component — maps ±$50 range to 0–25 pts
        avg = max(-50.0, min(50.0, self.avg_pnl))
        pnl_part = ((avg + 50.0) / 100.0) * 25.0

        raw_score = wr_part + pf_part + pnl_part  # 0–100

        # EMA smoothing: blend previous ema_score with the new raw_score
        alpha = 1.0 - EMA_DECAY
        self.ema_score = EMA_DECAY * self.ema_score + alpha * raw_score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": round(self.total_pnl, 4),
            "total_fees": round(self.total_fees, 4),
            "win_rate": round(self.win_rate, 4),
            "avg_pnl": round(self.avg_pnl, 4),
            "profit_factor": round(self.profit_factor, 4) if math.isfinite(self.profit_factor) else None,
            "avg_holding_hours": round(self.avg_holding_hours, 2),
            "avg_fee_per_trade": round(self.avg_fee_per_trade, 4),
            "ema_score": round(self.ema_score, 2),
            "first_trade_ts": self.first_trade_ts,
            "last_trade_ts": self.last_trade_ts,
            "regime_stats": {k: v.to_dict() for k, v in self.regime_stats.items()},
            "strategy_stats": {k: v.to_dict() for k, v in self.strategy_stats.items()},
        }


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class SymbolIntelligenceMemory:
    """
    Per-symbol self-learning memory engine.

    Maintains a persistent performance profile for every symbol traded by
    the bot.  Thread-safe via ``threading.RLock``.  State is persisted to
    JSON after every ``record_trade`` call.

    Parameters
    ----------
    state_path : str
        Path to the JSON state file.
    low_score_threshold : float
        Symbols with ``ema_score`` below this value get an AVOID recommendation.
    high_score_threshold : float
        Symbols with ``ema_score`` above this value get a PREFERRED recommendation.
    """

    def __init__(
        self,
        state_path: str = str(STATE_FILE),
        low_score_threshold: float = LOW_SCORE_THRESHOLD,
        high_score_threshold: float = HIGH_SCORE_THRESHOLD,
    ) -> None:
        self._state_path = Path(state_path)
        self._low_threshold = low_score_threshold
        self._high_threshold = high_score_threshold
        self._lock = threading.RLock()
        self._symbols: Dict[str, SymbolStats] = {}

        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info(
            "🧠 Symbol Intelligence Memory initialized | %d symbols tracked",
            len(self._symbols),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def record_trade(
        self,
        trade_id: str,
        symbol: str,
        strategy: str,
        side: str,
        entry_price: float,
        exit_price: float,
        position_size_usd: float,
        pnl: float,
        fees: float,
        market_regime: str,
        holding_hours: float = 0.0,
        trade_ts: Optional[str] = None,
    ) -> None:
        """
        Ingest a completed trade and update the symbol's intelligence profile.

        Args:
            trade_id: Unique trade identifier (for logging; not stored).
            symbol: Trading pair, e.g. ``"BTC-USD"``.
            strategy: Strategy name, e.g. ``"ApexTrend"``.
            side: ``"long"`` or ``"short"``.
            entry_price: Entry price.
            exit_price: Exit price.
            position_size_usd: Notional position size in USD.
            pnl: Net profit/loss in USD (after fees).
            fees: Total fees paid in USD.
            market_regime: Market regime label, e.g. ``"BULL_TRENDING"``.
            holding_hours: How long the trade was held (hours).
            trade_ts: ISO-format timestamp; defaults to ``datetime.utcnow()``.
        """
        ts = trade_ts or datetime.utcnow().isoformat()

        with self._lock:
            if symbol not in self._symbols:
                if len(self._symbols) >= MAX_SYMBOLS:
                    logger.warning(
                        "Symbol cap (%d) reached — skipping new symbol %s", MAX_SYMBOLS, symbol
                    )
                    return
                self._symbols[symbol] = SymbolStats(symbol=symbol)

            self._symbols[symbol].update(
                pnl=pnl,
                fees=fees,
                holding_hours=holding_hours,
                regime=market_regime,
                strategy=strategy,
                trade_ts=ts,
            )
            self._save_state()

        logger.debug(
            "📥 [SIM] %s | %s | regime=%s | pnl=%.2f | ema_score=%.1f",
            symbol,
            trade_id,
            market_regime,
            pnl,
            self._symbols[symbol].ema_score,
        )

    def score_symbol(
        self,
        symbol: str,
        regime: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Score a symbol before taking a new trade.

        The returned dictionary contains:
        * ``ema_score`` — composite 0–100 score (higher is better).
        * ``recommendation`` — ``"PREFERRED"``, ``"NEUTRAL"``, or ``"AVOID"``.
        * ``confidence`` — ``"low"``, ``"medium"``, or ``"high"`` based on sample size.
        * ``regime_win_rate`` — win rate in the requested regime (if available).
        * ``strategy_win_rate`` — win rate with the requested strategy (if available).
        * ``total_trades`` — how many times this symbol has been traded.

        Args:
            symbol: Trading pair symbol.
            regime: Optional market regime for a regime-specific win-rate lookup.
            strategy: Optional strategy name for a strategy-specific win-rate lookup.

        Returns:
            Scoring dictionary.
        """
        with self._lock:
            stats = self._symbols.get(symbol)

            if stats is None or stats.total_trades < MIN_TRADES_FOR_SCORE:
                confidence = "none" if stats is None else "low"
                return {
                    "symbol": symbol,
                    "ema_score": 50.0,
                    "recommendation": "NEUTRAL",
                    "confidence": confidence,
                    "total_trades": stats.total_trades if stats else 0,
                    "regime_win_rate": None,
                    "strategy_win_rate": None,
                    "note": "Insufficient trade history — using neutral defaults.",
                }

            score = stats.ema_score
            total = stats.total_trades
            confidence = "low" if total < 10 else ("medium" if total < 50 else "high")

            if score >= self._high_threshold:
                recommendation = "PREFERRED"
            elif score <= self._low_threshold:
                recommendation = "AVOID"
            else:
                recommendation = "NEUTRAL"

            # Optional regime-specific win rate
            regime_wr: Optional[float] = None
            if regime and regime in stats.regime_stats:
                regime_wr = round(stats.regime_stats[regime].win_rate, 4)

            # Optional strategy-specific win rate
            strat_wr: Optional[float] = None
            if strategy and strategy in stats.strategy_stats:
                strat_wr = round(stats.strategy_stats[strategy].win_rate, 4)

            return {
                "symbol": symbol,
                "ema_score": round(score, 2),
                "recommendation": recommendation,
                "confidence": confidence,
                "total_trades": total,
                "overall_win_rate": round(stats.win_rate, 4),
                "overall_avg_pnl": round(stats.avg_pnl, 4),
                "regime_win_rate": regime_wr,
                "strategy_win_rate": strat_wr,
            }

    def get_symbol_stats(self, symbol: str) -> Optional[SymbolStats]:
        """Return the raw ``SymbolStats`` for a symbol, or ``None`` if unseen."""
        with self._lock:
            return self._symbols.get(symbol)

    def get_top_symbols(
        self,
        n: int = 10,
        regime: Optional[str] = None,
        min_trades: int = MIN_TRADES_FOR_SCORE,
    ) -> List[Dict[str, Any]]:
        """
        Return the top-N symbols ranked by EMA composite score.

        When *regime* is provided, symbols are ranked by their win-rate within
        that regime (falling back to overall EMA score when a symbol has no
        regime-specific history).

        Args:
            n: Number of symbols to return.
            regime: Optional regime filter.
            min_trades: Minimum total trades required to be eligible.

        Returns:
            List of dicts (symbol, ema_score, win_rate, avg_pnl, total_trades).
        """
        with self._lock:
            candidates = [
                s for s in self._symbols.values() if s.total_trades >= min_trades
            ]

            def _regime_sort_key(s: SymbolStats) -> float:
                if regime and regime in s.regime_stats:
                    rs = s.regime_stats[regime]
                    if rs.total_trades >= MIN_TRADES_FOR_SCORE:
                        return rs.win_rate * 0.6 + (s.ema_score / 100.0) * 0.4
                return s.ema_score / 100.0

            def _overall_sort_key(s: SymbolStats) -> float:
                return s.ema_score

            _sort_key = _regime_sort_key if regime else _overall_sort_key

            ranked = sorted(candidates, key=_sort_key, reverse=True)[:n]
            return [
                {
                    "symbol": s.symbol,
                    "ema_score": round(s.ema_score, 2),
                    "win_rate": round(s.win_rate, 4),
                    "avg_pnl": round(s.avg_pnl, 4),
                    "total_trades": s.total_trades,
                    "regime_win_rate": (
                        round(s.regime_stats[regime].win_rate, 4)
                        if regime and regime in s.regime_stats
                        else None
                    ),
                }
                for s in ranked
            ]

    def get_avoid_symbols(self, min_trades: int = MIN_TRADES_FOR_SCORE) -> List[str]:
        """
        Return symbols with EMA score below the low-score threshold.

        These symbols have consistently underperformed and should be
        deprioritised or excluded from the scan universe.

        Args:
            min_trades: Minimum trades before a symbol can be flagged.

        Returns:
            Sorted list of symbol strings.
        """
        with self._lock:
            return sorted(
                s.symbol
                for s in self._symbols.values()
                if s.total_trades >= min_trades and s.ema_score < self._low_threshold
            )

    def get_symbol_report(self, symbol: str) -> Dict[str, Any]:
        """
        Generate a per-symbol intelligence report.

        Returns a dict with top-level stats and breakdowns by regime and
        strategy.  Returns a minimal "not tracked" dict when the symbol is
        unknown.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Structured report dictionary.
        """
        with self._lock:
            stats = self._symbols.get(symbol)
            if stats is None:
                return {
                    "symbol": symbol,
                    "status": "not_tracked",
                    "message": "No trade history found for this symbol.",
                }

            best_regime = self._best_regime_for_symbol(stats)
            worst_regime = self._worst_regime_for_symbol(stats)
            best_strategy = self._best_strategy_for_symbol(stats)

            return {
                "symbol": symbol,
                "status": "tracked",
                "ema_score": round(stats.ema_score, 2),
                "recommendation": (
                    "PREFERRED" if stats.ema_score >= self._high_threshold
                    else ("AVOID" if stats.ema_score < self._low_threshold else "NEUTRAL")
                ),
                "total_trades": stats.total_trades,
                "wins": stats.wins,
                "losses": stats.losses,
                "win_rate": round(stats.win_rate, 4),
                "total_pnl": round(stats.total_pnl, 4),
                "avg_pnl": round(stats.avg_pnl, 4),
                "profit_factor": (
                    round(stats.profit_factor, 4) if math.isfinite(stats.profit_factor) else None
                ),
                "avg_holding_hours": round(stats.avg_holding_hours, 2),
                "avg_fee_per_trade": round(stats.avg_fee_per_trade, 4),
                "first_trade_ts": stats.first_trade_ts,
                "last_trade_ts": stats.last_trade_ts,
                "best_regime": best_regime,
                "worst_regime": worst_regime,
                "best_strategy": best_strategy,
                "regime_breakdown": {k: v.to_dict() for k, v in stats.regime_stats.items()},
                "strategy_breakdown": {k: v.to_dict() for k, v in stats.strategy_stats.items()},
            }

    def get_full_report(self) -> Dict[str, Any]:
        """
        Generate a full memory report covering all tracked symbols.

        Returns
        -------
        Dict with:
        * ``total_symbols_tracked``
        * ``total_trades``
        * ``preferred_symbols`` — list of PREFERRED symbols (ema_score ≥ high threshold)
        * ``avoid_symbols`` — list of AVOID symbols (ema_score < low threshold)
        * ``top_10_overall`` — top-10 ranked symbols
        * ``symbol_summary`` — per-symbol summary rows (sorted by ema_score desc)
        * ``generated_at``
        """
        with self._lock:
            total_trades = sum(s.total_trades for s in self._symbols.values())
            preferred = [
                s.symbol
                for s in self._symbols.values()
                if s.ema_score >= self._high_threshold and s.total_trades >= MIN_TRADES_FOR_SCORE
            ]
            avoid = self.get_avoid_symbols()
            top10 = self.get_top_symbols(n=10)

            summary = sorted(
                [
                    {
                        "symbol": s.symbol,
                        "ema_score": round(s.ema_score, 2),
                        "total_trades": s.total_trades,
                        "win_rate": round(s.win_rate, 4),
                        "avg_pnl": round(s.avg_pnl, 4),
                        "total_pnl": round(s.total_pnl, 4),
                    }
                    for s in self._symbols.values()
                ],
                key=lambda x: x["ema_score"],
                reverse=True,
            )

            return {
                "generated_at": datetime.utcnow().isoformat(),
                "total_symbols_tracked": len(self._symbols),
                "total_trades": total_trades,
                "preferred_symbols": sorted(preferred),
                "avoid_symbols": avoid,
                "top_10_overall": top10,
                "symbol_summary": summary,
            }

    def print_report(self, regime: Optional[str] = None) -> None:
        """Log a human-readable summary report."""
        top = self.get_top_symbols(n=10, regime=regime)
        avoid = self.get_avoid_symbols()
        with self._lock:
            total = len(self._symbols)
            trades = sum(s.total_trades for s in self._symbols.values())

        lines = [
            "",
            "=" * 80,
            "🧠  NIJA SYMBOL INTELLIGENCE MEMORY REPORT",
            "=" * 80,
            f"  Symbols Tracked:  {total}",
            f"  Total Trades:     {trades}",
            f"  Regime Filter:    {regime or 'None (overall)'}",
            "",
            "  TOP 10 SYMBOLS",
        ]
        for rank, row in enumerate(top, 1):
            lines.append(
                f"    {rank:>2}. {row['symbol']:<14} score={row['ema_score']:.1f}"
                f"  wr={row['win_rate']*100:.1f}%"
                f"  avg_pnl=${row['avg_pnl']:.2f}"
                f"  trades={row['total_trades']}"
            )
        if avoid:
            lines.append("")
            lines.append(f"  AVOID LIST ({len(avoid)} symbols): {', '.join(avoid[:20])}")
        lines.append("=" * 80)
        logger.info("\n".join(lines))

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _best_regime_for_symbol(stats: SymbolStats) -> Optional[str]:
        """Return the regime with the highest win rate (min 3 trades)."""
        qualified = {
            k: v for k, v in stats.regime_stats.items() if v.total_trades >= MIN_TRADES_FOR_SCORE
        }
        if not qualified:
            return None
        return max(qualified.values(), key=lambda r: r.win_rate).regime

    @staticmethod
    def _worst_regime_for_symbol(stats: SymbolStats) -> Optional[str]:
        """Return the regime with the lowest win rate (min 3 trades)."""
        qualified = {
            k: v for k, v in stats.regime_stats.items() if v.total_trades >= MIN_TRADES_FOR_SCORE
        }
        if not qualified:
            return None
        return min(qualified.values(), key=lambda r: r.win_rate).regime

    @staticmethod
    def _best_strategy_for_symbol(stats: SymbolStats) -> Optional[str]:
        """Return the strategy with the highest win rate (min 3 trades)."""
        qualified = {
            k: v for k, v in stats.strategy_stats.items() if v.total_trades >= MIN_TRADES_FOR_SCORE
        }
        if not qualified:
            return None
        return max(qualified.values(), key=lambda s: s.win_rate).strategy

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_state(self) -> None:
        """Atomically write current state to JSON."""
        try:
            data: Dict[str, Any] = {
                "version": "1.0",
                "saved_at": datetime.utcnow().isoformat(),
                "symbols": {},
            }
            for symbol, stats in self._symbols.items():
                data["symbols"][symbol] = {
                    "symbol": stats.symbol,
                    "total_trades": stats.total_trades,
                    "wins": stats.wins,
                    "losses": stats.losses,
                    "gross_profit": stats.gross_profit,
                    "gross_loss": stats.gross_loss,
                    "total_pnl": stats.total_pnl,
                    "total_fees": stats.total_fees,
                    "total_holding_hours": stats.total_holding_hours,
                    "ema_score": stats.ema_score,
                    "first_trade_ts": stats.first_trade_ts,
                    "last_trade_ts": stats.last_trade_ts,
                    "regime_stats": {
                        k: {
                            "regime": v.regime,
                            "total_trades": v.total_trades,
                            "wins": v.wins,
                            "losses": v.losses,
                            "gross_profit": v.gross_profit,
                            "gross_loss": v.gross_loss,
                            "total_pnl": v.total_pnl,
                            "total_fees": v.total_fees,
                            "total_holding_hours": v.total_holding_hours,
                        }
                        for k, v in stats.regime_stats.items()
                    },
                    "strategy_stats": {
                        k: {
                            "strategy": v.strategy,
                            "total_trades": v.total_trades,
                            "wins": v.wins,
                            "losses": v.losses,
                            "gross_profit": v.gross_profit,
                            "gross_loss": v.gross_loss,
                            "total_pnl": v.total_pnl,
                        }
                        for k, v in stats.strategy_stats.items()
                    },
                }

            tmp = self._state_path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            tmp.replace(self._state_path)

        except Exception as exc:
            logger.error("Failed to save Symbol Intelligence Memory state: %s", exc)

    def _load_state(self) -> None:
        """Load persisted state from JSON."""
        if not self._state_path.exists():
            return
        try:
            with open(self._state_path, "r") as f:
                data = json.load(f)

            for symbol, raw in data.get("symbols", {}).items():
                stats = SymbolStats(
                    symbol=raw["symbol"],
                    total_trades=raw.get("total_trades", 0),
                    wins=raw.get("wins", 0),
                    losses=raw.get("losses", 0),
                    gross_profit=raw.get("gross_profit", 0.0),
                    gross_loss=raw.get("gross_loss", 0.0),
                    total_pnl=raw.get("total_pnl", 0.0),
                    total_fees=raw.get("total_fees", 0.0),
                    total_holding_hours=raw.get("total_holding_hours", 0.0),
                    ema_score=raw.get("ema_score", 50.0),
                    first_trade_ts=raw.get("first_trade_ts", ""),
                    last_trade_ts=raw.get("last_trade_ts", ""),
                )

                for regime_key, rdata in raw.get("regime_stats", {}).items():
                    rs = SymbolRegimeStats(
                        regime=rdata["regime"],
                        total_trades=rdata.get("total_trades", 0),
                        wins=rdata.get("wins", 0),
                        losses=rdata.get("losses", 0),
                        gross_profit=rdata.get("gross_profit", 0.0),
                        gross_loss=rdata.get("gross_loss", 0.0),
                        total_pnl=rdata.get("total_pnl", 0.0),
                        total_fees=rdata.get("total_fees", 0.0),
                        total_holding_hours=rdata.get("total_holding_hours", 0.0),
                    )
                    stats.regime_stats[regime_key] = rs

                for strat_key, sdata in raw.get("strategy_stats", {}).items():
                    ss = SymbolStrategyStats(
                        strategy=sdata["strategy"],
                        total_trades=sdata.get("total_trades", 0),
                        wins=sdata.get("wins", 0),
                        losses=sdata.get("losses", 0),
                        gross_profit=sdata.get("gross_profit", 0.0),
                        gross_loss=sdata.get("gross_loss", 0.0),
                        total_pnl=sdata.get("total_pnl", 0.0),
                    )
                    stats.strategy_stats[strat_key] = ss

                self._symbols[symbol] = stats

            logger.info(
                "✅ Loaded Symbol Intelligence Memory: %d symbols", len(self._symbols)
            )
        except Exception as exc:
            logger.warning("Could not load Symbol Intelligence Memory state: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_sim_instance: Optional[SymbolIntelligenceMemory] = None
_sim_lock = threading.Lock()


def get_symbol_intelligence_memory(
    state_path: str = str(STATE_FILE),
    low_score_threshold: float = LOW_SCORE_THRESHOLD,
    high_score_threshold: float = HIGH_SCORE_THRESHOLD,
) -> SymbolIntelligenceMemory:
    """
    Return the process-wide ``SymbolIntelligenceMemory`` singleton.

    Parameters are only applied on the *first* call; subsequent calls return
    the cached instance regardless of the arguments supplied.

    Args:
        state_path: Path to the JSON state file.
        low_score_threshold: Symbols below this score are flagged AVOID.
        high_score_threshold: Symbols above this score are flagged PREFERRED.

    Returns:
        SymbolIntelligenceMemory singleton.
    """
    global _sim_instance

    with _sim_lock:
        if _sim_instance is None:
            _sim_instance = SymbolIntelligenceMemory(
                state_path=state_path,
                low_score_threshold=low_score_threshold,
                high_score_threshold=high_score_threshold,
            )
    return _sim_instance
