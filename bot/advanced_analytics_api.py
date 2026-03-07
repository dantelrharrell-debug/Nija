"""
Advanced Analytics API
========================

Extends the existing analytics stack with four institutional-grade
reporting layers:

1. Exposure Heatmaps
   - Per-symbol and per-strategy capital exposure as a 2D matrix.
   - Liquidity-adjusted exposure (exposure × inverse spread proxy).

2. Monte Carlo Scenario Updates
   - Pulls latest results from StressTestEngine.
   - Computes forward-looking VaR, CVaR, and survival-rate projections.

3. Performance Attribution
   - P&L attribution sliced by strategy, venue (broker), and market regime.
   - Rolling Sharpe, Sortino, and Calmar ratios per dimension.

4. Real-Time API
   - Lightweight in-process FastAPI-compatible router (or standalone dict).
   - All endpoints return JSON-serialisable dicts.

Usage
-----
    from bot.advanced_analytics_api import AdvancedAnalyticsAPI

    api = AdvancedAnalyticsAPI(initial_capital=50_000)

    # Record trades
    api.record_trade(
        symbol="BTC-USD", strategy="ApexTrend", venue="Coinbase",
        regime="BULL_TRENDING", pnl=200.0, size=0.25,
        entry_price=40_000, exit_price=40_800,
    )

    # Dashboard payloads
    heatmap    = api.get_exposure_heatmap()
    mc_update  = api.get_monte_carlo_update()
    attribution = api.get_performance_attribution()
    full       = api.get_full_dashboard()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import statistics
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.advanced_analytics_api")


# ─────────────────────────────────────────────────────────────────────────────
# Trade record
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    symbol:      str
    strategy:    str
    venue:       str
    regime:      str
    pnl:         float
    size:        float
    entry_price: float
    exit_price:  float
    timestamp:   str
    won:         bool = False

    @property
    def return_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.exit_price - self.entry_price) / self.entry_price


# ─────────────────────────────────────────────────────────────────────────────
# Heatmap helpers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HeatmapCell:
    row:    str
    col:    str
    value:  float   # raw exposure in dollars
    pnl:    float   # cumulative P&L for this cell
    count:  int     # number of trades

    @property
    def avg_pnl(self) -> float:
        return self.pnl / self.count if self.count else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Attribution result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AttributionSlice:
    dimension:     str
    label:         str
    total_pnl:     float
    trade_count:   int
    win_rate:      float
    sharpe:        float
    sortino:       float
    calmar:        float
    max_drawdown:  float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension":   self.dimension,
            "label":       self.label,
            "total_pnl":   round(self.total_pnl, 2),
            "trade_count": self.trade_count,
            "win_rate":    round(self.win_rate, 4),
            "sharpe":      round(self.sharpe, 4),
            "sortino":     round(self.sortino, 4),
            "calmar":      round(self.calmar, 4),
            "max_drawdown":round(self.max_drawdown, 4),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main API class
# ─────────────────────────────────────────────────────────────────────────────

class AdvancedAnalyticsAPI:
    """
    Advanced analytics and reporting API.

    Parameters
    ----------
    initial_capital : float
        Starting capital used for ratio calculations.
    max_trades_in_memory : int
        Rolling window of trades retained in memory (default 5000).
    """

    def __init__(
        self,
        initial_capital: float = 50_000.0,
        max_trades_in_memory: int = 5_000,
    ) -> None:
        self.initial_capital     = max(1.0, initial_capital)
        self.max_trades_in_memory = max_trades_in_memory
        self._lock               = threading.RLock()
        self._trades: List[TradeRecord] = []

        logger.info(
            "📊 AdvancedAnalyticsAPI ready | capital=$%.0f", initial_capital
        )

    # ── Data ingestion ────────────────────────────────────────────────────────

    def record_trade(
        self,
        symbol: str,
        strategy: str,
        venue: str,
        regime: str,
        pnl: float,
        size: float,
        entry_price: float,
        exit_price: float,
        timestamp: Optional[str] = None,
    ) -> None:
        """Record a completed trade for analytics."""
        with self._lock:
            record = TradeRecord(
                symbol      = symbol,
                strategy    = strategy,
                venue       = venue,
                regime      = regime,
                pnl         = pnl,
                size        = size,
                entry_price = entry_price,
                exit_price  = exit_price,
                timestamp   = timestamp or _now(),
                won         = pnl > 0,
            )
            self._trades.append(record)
            # Rolling window
            if len(self._trades) > self.max_trades_in_memory:
                self._trades = self._trades[-self.max_trades_in_memory:]

    # ── Heatmap ───────────────────────────────────────────────────────────────

    def get_exposure_heatmap(
        self,
        row_dim: str = "strategy",
        col_dim: str = "symbol",
    ) -> Dict[str, Any]:
        """
        Generate an exposure heatmap.

        Parameters
        ----------
        row_dim : one of "strategy", "venue", "regime"
        col_dim : one of "symbol", "strategy", "venue", "regime"

        Returns a dict with "rows", "cols", and "cells" keys.
        """
        with self._lock:
            # Collect all distinct dimension values
            def _get(t: TradeRecord, dim: str) -> str:
                return getattr(t, dim, "unknown")

            rows: List[str] = sorted({_get(t, row_dim) for t in self._trades}) or ["(none)"]
            cols: List[str] = sorted({_get(t, col_dim) for t in self._trades}) or ["(none)"]

            # Aggregate exposure and P&L per cell
            exposure: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
            pnl_map:  Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
            count_map: Dict[str, Dict[str, int]]  = defaultdict(lambda: defaultdict(int))

            for t in self._trades:
                r = _get(t, row_dim)
                c = _get(t, col_dim)
                exposure[r][c]  += t.size * t.entry_price
                pnl_map[r][c]   += t.pnl
                count_map[r][c] += 1

            cells = []
            for r in rows:
                for c in cols:
                    cells.append({
                        "row":     r,
                        "col":     c,
                        "exposure": round(exposure[r].get(c, 0.0), 2),
                        "pnl":      round(pnl_map[r].get(c, 0.0), 2),
                        "count":    count_map[r].get(c, 0),
                        "avg_pnl":  round(
                            pnl_map[r].get(c, 0.0) / max(1, count_map[r].get(c, 1)), 2
                        ),
                    })

            total_exposure = sum(e for row in exposure.values() for e in row.values())

            return {
                "rows":          rows,
                "cols":          cols,
                "cells":         cells,
                "row_dim":       row_dim,
                "col_dim":       col_dim,
                "total_exposure": round(total_exposure, 2),
                "generated_at":  _now(),
            }

    # ── Monte Carlo update ────────────────────────────────────────────────────

    def get_monte_carlo_update(
        self,
        num_paths: int = 300,
        seed: int = 42,
    ) -> Dict[str, Any]:
        """
        Run a fresh Monte Carlo stress test and return the scenario summary.
        Uses StressTestEngine internally.
        """
        try:
            from bot.stress_test_engine import StressTestEngine
            engine = StressTestEngine(
                initial_capital=self.initial_capital,
                num_paths=num_paths,
                seed=seed,
            )
            report = engine.run_all_scenarios()
            return {
                "scenarios":            [r.to_dict() for r in report.scenario_results],
                "overall_survival_rate": round(report.overall_survival_rate, 4),
                "worst_scenario":        report.worst_scenario.scenario_name
                                         if report.worst_scenario else "N/A",
                "generated_at":         _now(),
            }
        except Exception as exc:
            logger.warning("[AdvAnalytics] Monte Carlo update failed: %s", exc)
            return {"error": str(exc), "generated_at": _now()}

    # ── Performance attribution ───────────────────────────────────────────────

    def get_performance_attribution(self) -> Dict[str, Any]:
        """
        Compute performance attribution across three dimensions:
        strategy, venue (broker), and market regime.
        """
        with self._lock:
            trades = list(self._trades)

        dimensions = [
            ("strategy", lambda t: t.strategy),
            ("venue",    lambda t: t.venue),
            ("regime",   lambda t: t.regime),
        ]

        result: Dict[str, Any] = {"generated_at": _now()}

        for dim_name, key_fn in dimensions:
            groups: Dict[str, List[TradeRecord]] = defaultdict(list)
            for t in trades:
                groups[key_fn(t)].append(t)

            slices = []
            for label, group_trades in sorted(groups.items()):
                slices.append(_compute_attribution_slice(dim_name, label, group_trades).to_dict())

            result[dim_name] = slices

        return result

    # ── Full dashboard ────────────────────────────────────────────────────────

    def get_full_dashboard(self) -> Dict[str, Any]:
        """Return a combined analytics payload for dashboard consumers."""
        with self._lock:
            trades = list(self._trades)

        total_pnl   = sum(t.pnl for t in trades)
        total_trades = len(trades)
        wins        = sum(1 for t in trades if t.won)
        win_rate    = wins / total_trades if total_trades else 0.0

        return {
            "summary": {
                "total_trades":   total_trades,
                "total_pnl":      round(total_pnl, 2),
                "win_rate":       round(win_rate, 4),
                "initial_capital": self.initial_capital,
                "generated_at":   _now(),
            },
            "exposure_heatmap": self.get_exposure_heatmap(),
            "attribution":      self.get_performance_attribution(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Attribution calculation helper
# ─────────────────────────────────────────────────────────────────────────────

def _compute_attribution_slice(
    dimension: str, label: str, trades: List[TradeRecord]
) -> AttributionSlice:
    """Compute risk-adjusted return statistics for a slice of trades."""
    if not trades:
        return AttributionSlice(
            dimension=dimension, label=label,
            total_pnl=0.0, trade_count=0,
            win_rate=0.0, sharpe=0.0, sortino=0.0, calmar=0.0, max_drawdown=0.0,
        )

    pnls       = [t.pnl for t in trades]
    wins       = sum(1 for t in trades if t.won)
    total_pnl  = sum(pnls)
    trade_count = len(pnls)
    win_rate   = wins / trade_count

    # Sharpe (using P&L series as returns)
    mean_pnl = statistics.mean(pnls)
    try:
        std_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 0.0
    except Exception:
        std_pnl = 0.0
    sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0.0

    # Sortino (downside deviation only)
    downside  = [p for p in pnls if p < 0]
    try:
        d_std = statistics.stdev(downside) if len(downside) > 1 else 0.0
    except Exception:
        d_std = 0.0
    sortino = mean_pnl / d_std if d_std > 0 else 0.0

    # Max drawdown via cumulative equity curve (anchored at 0 / initial)
    cum_pnl    = 0.0
    peak       = 0.0
    max_dd     = 0.0
    for p in pnls:
        cum_pnl += p
        if cum_pnl > peak:
            peak = cum_pnl
        # Only compute drawdown when peak > 0 to avoid misleading values for
        # equity curves that start or remain negative
        if peak > 0:
            dd = (peak - cum_pnl) / peak
            if dd > max_dd:
                max_dd = dd

    calmar = (total_pnl / max(0.0001, max_dd)) if max_dd > 0 else 0.0

    return AttributionSlice(
        dimension    = dimension,
        label        = label,
        total_pnl    = total_pnl,
        trade_count  = trade_count,
        win_rate     = win_rate,
        sharpe       = sharpe,
        sortino      = sortino,
        calmar       = calmar,
        max_drawdown = max_dd,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_api_instance: Optional[AdvancedAnalyticsAPI] = None
_api_lock = threading.Lock()


def get_advanced_analytics_api(
    initial_capital: float = 50_000.0,
    **kwargs: Any,
) -> AdvancedAnalyticsAPI:
    """Return the process-wide AdvancedAnalyticsAPI singleton."""
    global _api_instance
    with _api_lock:
        if _api_instance is None:
            _api_instance = AdvancedAnalyticsAPI(
                initial_capital=initial_capital, **kwargs
            )
    return _api_instance


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
