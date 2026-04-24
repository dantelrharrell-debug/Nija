"""
NIJA PnL Analytics Layer
==========================
Unified, persistent PnL analytics that surfaces:

  • Overall win rate & average return
  • Per-pair performance (win rate, avg return, trade count, total PnL)
  • Strategy performance breakdown
  • Streak tracking (current win/loss streak + best streak)
  • Profit factor and Sharpe-like ratio

All state is persisted to ``data/pnl_analytics.json`` so metrics survive
process restarts.

Usage
-----
::

    from bot.pnl_analytics_layer import get_pnl_analytics_layer

    analytics = get_pnl_analytics_layer()

    # Record a completed trade:
    analytics.record_trade(
        symbol="BTC-USD",
        pnl_usd=45.20,
        is_win=True,
        strategy="apex_v71",
    )

    # Get a full report:
    report = analytics.get_report()
    analytics.log_report()         # pretty-prints to logger
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.pnl_analytics_layer")

# ---------------------------------------------------------------------------
# Persistence path
# ---------------------------------------------------------------------------

_DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "pnl_analytics.json"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PairStats:
    """Per-symbol performance statistics."""
    symbol: str
    total_trades: int = 0
    wins: int = 0
    total_pnl_usd: float = 0.0
    sum_win_pnl: float = 0.0
    sum_loss_pnl: float = 0.0  # stored as positive magnitude

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_return_usd(self) -> float:
        return self.total_pnl_usd / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.sum_loss_pnl == 0.0:
            return float("inf") if self.sum_win_pnl > 0 else 0.0
        return self.sum_win_pnl / self.sum_loss_pnl


@dataclass
class StrategyStats:
    """Per-strategy performance statistics."""
    strategy: str
    total_trades: int = 0
    wins: int = 0
    total_pnl_usd: float = 0.0
    sum_win_pnl: float = 0.0
    sum_loss_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_return_usd(self) -> float:
        return self.total_pnl_usd / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.sum_loss_pnl == 0.0:
            return float("inf") if self.sum_win_pnl > 0 else 0.0
        return self.sum_win_pnl / self.sum_loss_pnl


# ---------------------------------------------------------------------------
# Main analytics class
# ---------------------------------------------------------------------------

class PnLAnalyticsLayer:
    """
    Thread-safe PnL analytics singleton.

    Tracks overall, per-pair, and per-strategy metrics with JSON persistence.
    """

    def __init__(self, data_path: Optional[str] = None) -> None:
        self._data_path = data_path or _DEFAULT_DATA_PATH
        self._lock = threading.Lock()

        # ── Global counters ────────────────────────────────────────────────
        self._total_trades: int = 0
        self._total_wins: int = 0
        self._total_pnl_usd: float = 0.0
        self._sum_win_pnl: float = 0.0
        self._sum_loss_pnl: float = 0.0  # positive magnitude

        # Running sum/sum-of-squares for Sharpe-like ratio
        self._pnl_sum: float = 0.0
        self._pnl_sumsq: float = 0.0

        # ── Streak tracking ────────────────────────────────────────────────
        self._current_streak: int = 0          # positive=win streak, negative=loss
        self._best_win_streak: int = 0
        self._worst_loss_streak: int = 0       # stored as positive magnitude

        # ── Per-pair / per-strategy maps ───────────────────────────────────
        self._pairs: Dict[str, PairStats] = {}
        self._strategies: Dict[str, StrategyStats] = {}

        # Timestamp of first trade
        self._first_trade_ts: Optional[float] = None
        self._last_trade_ts: Optional[float] = None

        self._load()
        logger.info("📊 PnLAnalyticsLayer initialised — %d trades loaded", self._total_trades)

    # ── Persistence ──────────────────────────────────────────────────────────

    def _ensure_data_dir(self) -> None:
        d = os.path.dirname(self._data_path)
        if d:
            os.makedirs(d, exist_ok=True)

    def _save(self) -> None:
        """Persist state to JSON (called under lock)."""
        try:
            self._ensure_data_dir()
            state = {
                "total_trades": self._total_trades,
                "total_wins": self._total_wins,
                "total_pnl_usd": self._total_pnl_usd,
                "sum_win_pnl": self._sum_win_pnl,
                "sum_loss_pnl": self._sum_loss_pnl,
                "pnl_sum": self._pnl_sum,
                "pnl_sumsq": self._pnl_sumsq,
                "current_streak": self._current_streak,
                "best_win_streak": self._best_win_streak,
                "worst_loss_streak": self._worst_loss_streak,
                "first_trade_ts": self._first_trade_ts,
                "last_trade_ts": self._last_trade_ts,
                "pairs": {k: asdict(v) for k, v in self._pairs.items()},
                "strategies": {k: asdict(v) for k, v in self._strategies.items()},
            }
            with open(self._data_path, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as exc:
            logger.warning("⚠️ PnLAnalyticsLayer save failed: %s", exc)

    def _load(self) -> None:
        """Restore state from JSON if the file exists."""
        if not os.path.exists(self._data_path):
            return
        try:
            with open(self._data_path, "r") as f:
                state = json.load(f)
            self._total_trades = state.get("total_trades", 0)
            self._total_wins = state.get("total_wins", 0)
            self._total_pnl_usd = state.get("total_pnl_usd", 0.0)
            self._sum_win_pnl = state.get("sum_win_pnl", 0.0)
            self._sum_loss_pnl = state.get("sum_loss_pnl", 0.0)
            self._pnl_sum = state.get("pnl_sum", 0.0)
            self._pnl_sumsq = state.get("pnl_sumsq", 0.0)
            self._current_streak = state.get("current_streak", 0)
            self._best_win_streak = state.get("best_win_streak", 0)
            self._worst_loss_streak = state.get("worst_loss_streak", 0)
            self._first_trade_ts = state.get("first_trade_ts")
            self._last_trade_ts = state.get("last_trade_ts")
            for sym, d in state.get("pairs", {}).items():
                try:
                    self._pairs[sym] = PairStats(**{
                        k: v for k, v in d.items() if k in PairStats.__dataclass_fields__
                    })
                except (TypeError, KeyError):
                    pass
            for strat, d in state.get("strategies", {}).items():
                try:
                    self._strategies[strat] = StrategyStats(**{
                        k: v for k, v in d.items() if k in StrategyStats.__dataclass_fields__
                    })
                except (TypeError, KeyError):
                    pass
        except Exception as exc:
            logger.warning("⚠️ PnLAnalyticsLayer load failed: %s", exc)

    # ── Core recording ────────────────────────────────────────────────────────

    def record_trade(
        self,
        symbol: str,
        pnl_usd: float,
        is_win: bool,
        strategy: str = "unknown",
    ) -> None:
        """
        Record a completed trade.

        Args:
            symbol: Trading pair, e.g. "BTC-USD".
            pnl_usd: Net PnL in USD (can be negative).
            is_win: True if the trade was profitable.
            strategy: Strategy name (e.g. "apex_v71").
        """
        now = time.time()
        with self._lock:
            self._total_trades += 1
            if is_win:
                self._total_wins += 1
                self._sum_win_pnl += pnl_usd
            else:
                self._sum_loss_pnl += abs(pnl_usd)
            self._total_pnl_usd += pnl_usd
            self._pnl_sum += pnl_usd
            self._pnl_sumsq += pnl_usd ** 2

            # Streak
            if is_win:
                self._current_streak = max(0, self._current_streak) + 1
                self._best_win_streak = max(self._best_win_streak, self._current_streak)
            else:
                self._current_streak = min(0, self._current_streak) - 1
                self._worst_loss_streak = max(self._worst_loss_streak, abs(self._current_streak))

            # Timestamps
            if self._first_trade_ts is None:
                self._first_trade_ts = now
            self._last_trade_ts = now

            # Per-pair
            if symbol not in self._pairs:
                self._pairs[symbol] = PairStats(symbol=symbol)
            ps = self._pairs[symbol]
            ps.total_trades += 1
            if is_win:
                ps.wins += 1
                ps.sum_win_pnl += pnl_usd
            else:
                ps.sum_loss_pnl += abs(pnl_usd)
            ps.total_pnl_usd += pnl_usd

            # Per-strategy
            if strategy not in self._strategies:
                self._strategies[strategy] = StrategyStats(strategy=strategy)
            ss = self._strategies[strategy]
            ss.total_trades += 1
            if is_win:
                ss.wins += 1
                ss.sum_win_pnl += pnl_usd
            else:
                ss.sum_loss_pnl += abs(pnl_usd)
            ss.total_pnl_usd += pnl_usd

            # Persist every 10 trades to limit I/O
            if self._total_trades % 10 == 0:
                self._save()

    # ── Computed metrics ──────────────────────────────────────────────────────

    @property
    def win_rate(self) -> float:
        """Overall win rate (0–1)."""
        with self._lock:
            return self._total_wins / self._total_trades if self._total_trades > 0 else 0.0

    @property
    def avg_return_usd(self) -> float:
        """Average PnL per trade in USD."""
        with self._lock:
            return self._total_pnl_usd / self._total_trades if self._total_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        with self._lock:
            if self._sum_loss_pnl == 0.0:
                return float("inf") if self._sum_win_pnl > 0 else 0.0
            return self._sum_win_pnl / self._sum_loss_pnl

    def _sharpe(self) -> float:
        """Simple Sharpe-like ratio: mean_pnl / std_pnl (not annualised)."""
        if self._total_trades < 2:
            return 0.0
        mean = self._pnl_sum / self._total_trades
        variance = (self._pnl_sumsq / self._total_trades) - mean ** 2
        if variance <= 0:
            return 0.0
        return mean / math.sqrt(variance)

    # ── Query helpers ─────────────────────────────────────────────────────────

    def get_top_pairs(self, n: int = 5) -> List[PairStats]:
        """Return the top-N pairs by total PnL (best performers)."""
        with self._lock:
            return sorted(self._pairs.values(), key=lambda p: p.total_pnl_usd, reverse=True)[:n]

    def get_bottom_pairs(self, n: int = 5) -> List[PairStats]:
        """Return the bottom-N pairs by total PnL (worst performers)."""
        with self._lock:
            return sorted(self._pairs.values(), key=lambda p: p.total_pnl_usd)[:n]

    def get_pair_stats(self, symbol: str) -> Optional[PairStats]:
        """Return stats for a specific pair, or None if no trades yet."""
        with self._lock:
            return self._pairs.get(symbol)

    def get_strategy_stats(self, strategy: str) -> Optional[StrategyStats]:
        """Return stats for a specific strategy, or None if no trades yet."""
        with self._lock:
            return self._strategies.get(strategy)

    def get_all_strategy_stats(self) -> List[StrategyStats]:
        """Return a list of all tracked strategy stats objects."""
        with self._lock:
            return list(self._strategies.values())

    def get_all_pair_stats(self) -> List[PairStats]:
        """Return a list of all tracked pair stats objects."""
        with self._lock:
            return list(self._pairs.values())

    # ── Full report ───────────────────────────────────────────────────────────

    def get_report(self) -> dict:
        """Return a full JSON-serialisable analytics report."""
        with self._lock:
            sharpe = self._sharpe()
            top_pairs = sorted(self._pairs.values(), key=lambda p: p.total_pnl_usd, reverse=True)[:5]
            bottom_pairs = sorted(self._pairs.values(), key=lambda p: p.total_pnl_usd)[:5]
            strategies = sorted(self._strategies.values(), key=lambda s: s.total_pnl_usd, reverse=True)

            return {
                "overall": {
                    "total_trades": self._total_trades,
                    "win_rate": round(self._total_wins / self._total_trades if self._total_trades else 0.0, 4),
                    "avg_return_usd": round(self._total_pnl_usd / self._total_trades if self._total_trades else 0.0, 4),
                    "total_pnl_usd": round(self._total_pnl_usd, 2),
                    "profit_factor": round(
                        self._sum_win_pnl / self._sum_loss_pnl if self._sum_loss_pnl else 0.0, 3
                    ),
                    "sharpe_ratio": round(sharpe, 3),
                    "current_streak": self._current_streak,
                    "best_win_streak": self._best_win_streak,
                    "worst_loss_streak": self._worst_loss_streak,
                },
                "top_pairs": [
                    {
                        "symbol": p.symbol,
                        "total_pnl_usd": round(p.total_pnl_usd, 2),
                        "win_rate": round(p.win_rate, 3),
                        "avg_return_usd": round(p.avg_return_usd, 4),
                        "total_trades": p.total_trades,
                        "profit_factor": round(p.profit_factor, 3) if p.profit_factor != float("inf") else 99.0,
                    }
                    for p in top_pairs
                ],
                "bottom_pairs": [
                    {
                        "symbol": p.symbol,
                        "total_pnl_usd": round(p.total_pnl_usd, 2),
                        "win_rate": round(p.win_rate, 3),
                        "avg_return_usd": round(p.avg_return_usd, 4),
                        "total_trades": p.total_trades,
                    }
                    for p in bottom_pairs
                ],
                "strategies": [
                    {
                        "strategy": s.strategy,
                        "total_pnl_usd": round(s.total_pnl_usd, 2),
                        "win_rate": round(s.win_rate, 3),
                        "avg_return_usd": round(s.avg_return_usd, 4),
                        "total_trades": s.total_trades,
                        "profit_factor": round(s.profit_factor, 3) if s.profit_factor != float("inf") else 99.0,
                    }
                    for s in strategies
                ],
            }

    def log_report(self) -> None:
        """Pretty-print the full report to the logger at INFO level."""
        r = self.get_report()
        ov = r["overall"]
        logger.info(
            "📈 PnL Analytics — trades=%d | WR=%.1f%% | avg=$%.2f | "
            "total=$%.2f | PF=%.2f | Sharpe=%.2f | streak=%+d",
            ov["total_trades"],
            ov["win_rate"] * 100,
            ov["avg_return_usd"],
            ov["total_pnl_usd"],
            ov["profit_factor"],
            ov["sharpe_ratio"],
            ov["current_streak"],
        )
        if r["top_pairs"]:
            logger.info("   🏆 Top pairs: %s", ", ".join(
                f"{p['symbol']}=${p['total_pnl_usd']:+.0f}(WR={p['win_rate']*100:.0f}%)"
                for p in r["top_pairs"]
            ))
        if r["strategies"]:
            logger.info("   📊 Strategies: %s", ", ".join(
                f"{s['strategy']}=${s['total_pnl_usd']:+.0f}(WR={s['win_rate']*100:.0f}%)"
                for s in r["strategies"]
            ))

    def flush(self) -> None:
        """Force-persist state to disk immediately."""
        with self._lock:
            self._save()

    @property
    def total_trades(self) -> int:
        """Total number of trades recorded."""
        with self._lock:
            return self._total_trades


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_analytics_instance: Optional[PnLAnalyticsLayer] = None
_analytics_lock = threading.Lock()


def get_pnl_analytics_layer(data_path: Optional[str] = None) -> PnLAnalyticsLayer:
    """
    Return the thread-safe singleton PnLAnalyticsLayer.

    ``data_path`` is only used on the first (initialising) call.
    """
    global _analytics_instance
    if _analytics_instance is None:
        with _analytics_lock:
            if _analytics_instance is None:
                _analytics_instance = PnLAnalyticsLayer(data_path=data_path)
    return _analytics_instance
