"""
Portfolio Performance Analytics
================================
Comprehensive, real-time performance measurement for the NIJA trading bot.

Capabilities
------------
  * Rolling & cumulative P&L tracking (per trade, per day, per strategy)
  * Risk-adjusted ratios: Sharpe, Sortino, Calmar
  * Drawdown analysis: current, max, duration, recovery time
  * Win/loss streak tracking with expectancy calculation
  * Benchmark comparison (passive buy-and-hold BTC/USD baseline)
  * Equity curve reconstruction
  * Multi-period reporting: daily, weekly, monthly, all-time
  * Per-strategy, per-symbol performance breakdown

Public API
----------
  analytics = get_portfolio_performance_analytics()
  analytics.record_trade(trade)
  analytics.update_benchmark(price)
  report    = analytics.get_full_report()
  summary   = analytics.get_summary()
  breakdown = analytics.get_strategy_breakdown()
"""

from __future__ import annotations

import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, date, timezone, timedelta
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.portfolio_performance_analytics")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RISK_FREE_RATE_ANNUAL = 0.05          # 5% annual risk-free rate
TRADING_DAYS_PER_YEAR = 252
MAX_TRADES_IN_MEMORY  = 10_000        # rolling cap on trade history


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """A completed trade used as the unit of analytics input."""
    symbol: str
    strategy: str
    side: str                  # "BUY" | "SELL"
    entry_price: float
    exit_price: float
    size: float                # units (not USD)
    pnl: float                 # realised P&L in USD
    regime: str = "unknown"
    venue: str  = "coinbase"
    duration_seconds: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def won(self) -> bool:
        return self.pnl > 0

    @property
    def return_pct(self) -> float:
        cost = self.entry_price * self.size
        return self.pnl / cost if cost > 0 else 0.0


@dataclass
class DrawdownState:
    """Current drawdown snapshot."""
    current_dd_pct: float       # current drawdown from peak (0-1)
    max_dd_pct: float           # maximum drawdown ever seen (0-1)
    peak_equity: float
    trough_equity: float
    dd_start_date: Optional[str]
    dd_duration_days: float
    recovery_days: Optional[float]  # days to recover, if known

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_dd_pct": round(self.current_dd_pct * 100, 4),
            "max_dd_pct": round(self.max_dd_pct * 100, 4),
            "peak_equity": round(self.peak_equity, 2),
            "trough_equity": round(self.trough_equity, 2),
            "dd_start_date": self.dd_start_date,
            "dd_duration_days": round(self.dd_duration_days, 2),
            "recovery_days": (
                round(self.recovery_days, 2) if self.recovery_days is not None else None
            ),
        }


@dataclass
class PerformanceMetrics:
    """Computed performance statistics for a given window."""
    label: str
    trade_count: int
    total_pnl: float
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    sharpe: float
    sortino: float
    calmar: float
    max_dd_pct: float
    current_streak: int         # positive=win streak, negative=loss streak
    max_win_streak: int
    max_loss_streak: int
    avg_duration_sec: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "trade_count": self.trade_count,
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate * 100, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "profit_factor": round(self.profit_factor, 3),
            "expectancy": round(self.expectancy, 2),
            "sharpe": round(self.sharpe, 4),
            "sortino": round(self.sortino, 4),
            "calmar": round(self.calmar, 4),
            "max_dd_pct": round(self.max_dd_pct * 100, 4),
            "current_streak": self.current_streak,
            "max_win_streak": self.max_win_streak,
            "max_loss_streak": self.max_loss_streak,
            "avg_duration_sec": round(self.avg_duration_sec, 1),
        }


@dataclass
class BenchmarkComparison:
    """Passive BTC buy-and-hold comparison."""
    benchmark_return_pct: float
    portfolio_return_pct: float
    alpha_pct: float            # portfolio − benchmark
    beta: float                 # correlation-adjusted systematic risk
    information_ratio: float
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "benchmark_return_pct": round(self.benchmark_return_pct * 100, 4),
            "portfolio_return_pct": round(self.portfolio_return_pct * 100, 4),
            "alpha_pct": round(self.alpha_pct * 100, 4),
            "beta": round(self.beta, 4),
            "information_ratio": round(self.information_ratio, 4),
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _annualised_sharpe(returns: List[float]) -> float:
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=float)
    daily_rf = (1 + RISK_FREE_RATE_ANNUAL) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = arr - daily_rf
    mu  = float(np.mean(excess))
    std = float(np.std(excess, ddof=1))
    if std < 1e-12:
        return 0.0
    return float(mu / std * math.sqrt(TRADING_DAYS_PER_YEAR))


def _annualised_sortino(returns: List[float]) -> float:
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=float)
    daily_rf = (1 + RISK_FREE_RATE_ANNUAL) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = arr - daily_rf
    mu  = float(np.mean(excess))
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf") if mu > 0 else 0.0
    target_std = float(np.std(downside, ddof=1))
    if target_std < 1e-12:
        return 0.0
    return float(mu / target_std * math.sqrt(TRADING_DAYS_PER_YEAR))


def _max_drawdown(equity_curve: List[float]) -> float:
    """Return max drawdown as a positive fraction (0–1)."""
    if len(equity_curve) < 2:
        return 0.0
    arr = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = (peak - arr) / np.where(peak > 0, peak, 1)
    return float(np.max(dd))


def _calmar(total_return: float, max_dd: float) -> float:
    if max_dd < 1e-10:
        return float("inf") if total_return > 0 else 0.0
    return total_return / max_dd


def _streak_stats(trades: List[TradeRecord]) -> Tuple[int, int, int]:
    """Return (current_streak, max_win_streak, max_loss_streak)."""
    if not trades:
        return 0, 0, 0
    current = 0
    max_win = 0
    max_loss = 0
    streak = 0
    for t in trades:
        if t.won:
            streak = max(0, streak) + 1
            max_win = max(max_win, streak)
        else:
            streak = min(0, streak) - 1
            max_loss = max(max_loss, abs(streak))
    current = streak
    return current, max_win, max_loss


def _profit_factor(wins: List[float], losses: List[float]) -> float:
    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss < 1e-10:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def _beta(portfolio_returns: List[float], benchmark_returns: List[float]) -> float:
    if len(portfolio_returns) < 2 or len(benchmark_returns) < 2:
        return 1.0
    n = min(len(portfolio_returns), len(benchmark_returns))
    p = np.array(portfolio_returns[-n:], dtype=float)
    b = np.array(benchmark_returns[-n:], dtype=float)
    var_b = float(np.var(b))
    if var_b < 1e-12:
        return 1.0
    cov = float(np.cov(p, b)[0, 1])
    return cov / var_b


# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------

class PortfolioPerformanceAnalytics:
    """
    Real-time portfolio performance measurement and reporting.
    All public methods are thread-safe.
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        max_trades: int = MAX_TRADES_IN_MEMORY,
    ) -> None:
        self._initial_capital = max(1.0, initial_capital)
        self._max_trades      = max(100, max_trades)
        self._lock            = threading.RLock()

        # Trade history (bounded deque)
        self._trades: Deque[TradeRecord] = deque(maxlen=self._max_trades)

        # Equity curve: (timestamp_iso, equity_usd)
        self._equity_curve: List[Tuple[str, float]] = [
            (datetime.now(timezone.utc).isoformat(), self._initial_capital)
        ]
        self._current_equity  = self._initial_capital
        self._peak_equity     = self._initial_capital
        self._max_dd          = 0.0

        # Drawdown tracking
        self._dd_start: Optional[str] = None
        self._trough_equity   = self._initial_capital

        # Benchmark (BTC price history for buy-and-hold comparison)
        self._benchmark_prices: Deque[float] = deque(maxlen=self._max_trades)
        self._benchmark_start: Optional[float] = None

        # Daily P&L cache
        self._daily_pnl: Dict[str, float] = defaultdict(float)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(self, trade: TradeRecord) -> None:
        """
        Ingest a completed trade into the analytics engine.

        Call this immediately after every trade closes.
        """
        with self._lock:
            self._trades.append(trade)

            # Update equity curve
            self._current_equity += trade.pnl
            ts = datetime.now(timezone.utc).isoformat()
            self._equity_curve.append((ts, self._current_equity))

            # Update peak / drawdown
            if self._current_equity > self._peak_equity:
                self._peak_equity  = self._current_equity
                self._dd_start     = None
                self._trough_equity = self._current_equity
            else:
                dd = (self._peak_equity - self._current_equity) / self._peak_equity
                if dd > self._max_dd:
                    self._max_dd = dd
                if self._current_equity < self._trough_equity:
                    self._trough_equity = self._current_equity
                    if self._dd_start is None:
                        self._dd_start = ts

            # Update daily P&L
            today = datetime.now(timezone.utc).date().isoformat()
            self._daily_pnl[today] += trade.pnl

    def update_benchmark(self, price: float) -> None:
        """
        Record a current benchmark price (e.g., BTC-USD mid).
        Call once per scan cycle to keep the benchmark fresh.
        """
        if price <= 0:
            return
        with self._lock:
            if self._benchmark_start is None:
                self._benchmark_start = price
            self._benchmark_prices.append(price)

    def get_summary(self) -> Dict[str, Any]:
        """High-level performance summary (fast, suitable for dashboards)."""
        with self._lock:
            trades = list(self._trades)
            equity = self._current_equity
            initial = self._initial_capital

        total_return = (equity - initial) / initial if initial > 0 else 0.0
        metrics = self._compute_metrics("all-time", trades)

        return {
            "initial_capital": round(initial, 2),
            "current_equity": round(equity, 2),
            "total_pnl": round(equity - initial, 2),
            "total_return_pct": round(total_return * 100, 4),
            "trade_count": metrics.trade_count,
            "win_rate": round(metrics.win_rate * 100, 2),
            "sharpe": round(metrics.sharpe, 4),
            "sortino": round(metrics.sortino, 4),
            "calmar": round(metrics.calmar, 4),
            "max_dd_pct": round(metrics.max_dd_pct * 100, 4),
            "profit_factor": round(metrics.profit_factor, 3),
            "expectancy": round(metrics.expectancy, 2),
            "current_streak": metrics.current_streak,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_drawdown_state(self) -> DrawdownState:
        """Return the current drawdown state."""
        with self._lock:
            peak  = self._peak_equity
            curr  = self._current_equity
            trough = self._trough_equity

            current_dd = (peak - curr) / peak if peak > 0 else 0.0
            dd_start   = self._dd_start
            duration   = 0.0
            if dd_start:
                start_dt = datetime.fromisoformat(dd_start.replace("Z", "+00:00"))
                duration = (datetime.now(timezone.utc) - start_dt).total_seconds() / 86_400

            # Recovery estimate: linear projection from trough
            recovery = None
            if trough < peak and len(self._trades) >= 10:
                recent_pnl = [t.pnl for t in list(self._trades)[-20:]]
                avg_daily = float(np.mean(recent_pnl)) if recent_pnl else 0.0
                gap = peak - curr
                if avg_daily > 0:
                    recovery = gap / avg_daily  # trades, not days exactly

            return DrawdownState(
                current_dd_pct=current_dd,
                max_dd_pct=self._max_dd,
                peak_equity=peak,
                trough_equity=trough,
                dd_start_date=dd_start,
                dd_duration_days=duration,
                recovery_days=recovery,
            )

    def get_period_metrics(self, period: str = "daily") -> List[PerformanceMetrics]:
        """
        Compute performance metrics grouped by *period*.

        Parameters
        ----------
        period : "daily" | "weekly" | "monthly"
        """
        with self._lock:
            trades = list(self._trades)

        grouped: Dict[str, List[TradeRecord]] = defaultdict(list)
        for t in trades:
            try:
                dt = datetime.fromisoformat(t.timestamp.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                dt = datetime.now(timezone.utc)

            if period == "daily":
                key = dt.date().isoformat()
            elif period == "weekly":
                iso = dt.isocalendar()
                key = f"{iso[0]}-W{iso[1]:02d}"
            else:  # monthly
                key = f"{dt.year}-{dt.month:02d}"

            grouped[key].append(t)

        return [
            self._compute_metrics(label, bucket)
            for label, bucket in sorted(grouped.items())
        ]

    def get_strategy_breakdown(self) -> List[PerformanceMetrics]:
        """Per-strategy performance metrics."""
        with self._lock:
            trades = list(self._trades)

        grouped: Dict[str, List[TradeRecord]] = defaultdict(list)
        for t in trades:
            grouped[t.strategy].append(t)

        return [
            self._compute_metrics(strategy, bucket)
            for strategy, bucket in sorted(grouped.items())
        ]

    def get_symbol_breakdown(self) -> List[PerformanceMetrics]:
        """Per-symbol performance metrics."""
        with self._lock:
            trades = list(self._trades)

        grouped: Dict[str, List[TradeRecord]] = defaultdict(list)
        for t in trades:
            grouped[t.symbol].append(t)

        return [
            self._compute_metrics(symbol, bucket)
            for symbol, bucket in sorted(grouped.items())
        ]

    def get_benchmark_comparison(self) -> BenchmarkComparison:
        """Compare portfolio returns vs. passive BTC buy-and-hold."""
        with self._lock:
            prices = list(self._benchmark_prices)
            start_price = self._benchmark_start
            initial = self._initial_capital
            current = self._current_equity
            trades = list(self._trades)

        if not prices or start_price is None or start_price <= 0:
            return BenchmarkComparison(
                benchmark_return_pct=0.0,
                portfolio_return_pct=0.0,
                alpha_pct=0.0,
                beta=1.0,
                information_ratio=0.0,
            )

        bm_return = (prices[-1] - start_price) / start_price
        port_return = (current - initial) / initial if initial > 0 else 0.0
        alpha = port_return - bm_return

        # Beta via per-trade returns vs. benchmark price changes
        port_returns = [t.return_pct for t in trades]
        bm_changes = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, len(prices))
        ]
        b = _beta(port_returns, bm_changes)

        # Information ratio: alpha / tracking error
        if port_returns and bm_changes:
            n = min(len(port_returns), len(bm_changes))
            diff = np.array(port_returns[-n:]) - np.array(bm_changes[-n:])
            te = float(np.std(diff, ddof=1)) if len(diff) > 1 else 0.0
            ir = float(np.mean(diff)) / te if te > 1e-10 else 0.0
        else:
            ir = 0.0

        return BenchmarkComparison(
            benchmark_return_pct=bm_return,
            portfolio_return_pct=port_return,
            alpha_pct=alpha,
            beta=b,
            information_ratio=ir,
        )

    def get_equity_curve(self, max_points: int = 500) -> List[Dict[str, Any]]:
        """
        Return the equity curve as a list of (timestamp, equity) dicts,
        sampled to at most *max_points* entries.
        """
        with self._lock:
            curve = list(self._equity_curve)

        if len(curve) > max_points:
            # Uniform downsampling
            step = len(curve) / max_points
            indices = [int(i * step) for i in range(max_points)]
            indices[-1] = len(curve) - 1
            curve = [curve[i] for i in indices]

        return [{"timestamp": ts, "equity": round(eq, 2)} for ts, eq in curve]

    def get_daily_pnl(self) -> List[Dict[str, Any]]:
        """Return daily P&L as a list of {date, pnl} dicts sorted by date."""
        with self._lock:
            daily = dict(self._daily_pnl)

        return [
            {"date": d, "pnl": round(p, 2)}
            for d, p in sorted(daily.items())
        ]

    def get_full_report(self) -> Dict[str, Any]:
        """
        Complete analytics report combining all layers.
        Suitable for dashboard consumption.
        """
        summary    = self.get_summary()
        drawdown   = self.get_drawdown_state().to_dict()
        strategy_b = [m.to_dict() for m in self.get_strategy_breakdown()]
        symbol_b   = [m.to_dict() for m in self.get_symbol_breakdown()]
        daily_pm   = [m.to_dict() for m in self.get_period_metrics("daily")]
        monthly_pm = [m.to_dict() for m in self.get_period_metrics("monthly")]
        benchmark  = self.get_benchmark_comparison().to_dict()
        equity_c   = self.get_equity_curve()
        daily_pnl  = self.get_daily_pnl()

        return {
            "summary": summary,
            "drawdown": drawdown,
            "strategy_breakdown": strategy_b,
            "symbol_breakdown": symbol_b,
            "daily_performance": daily_pm,
            "monthly_performance": monthly_pm,
            "benchmark": benchmark,
            "equity_curve": equity_c,
            "daily_pnl": daily_pnl,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_metrics(
        self, label: str, trades: List[TradeRecord]
    ) -> PerformanceMetrics:
        if not trades:
            return PerformanceMetrics(
                label=label,
                trade_count=0,
                total_pnl=0.0,
                win_rate=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                profit_factor=0.0,
                expectancy=0.0,
                sharpe=0.0,
                sortino=0.0,
                calmar=0.0,
                max_dd_pct=0.0,
                current_streak=0,
                max_win_streak=0,
                max_loss_streak=0,
                avg_duration_sec=0.0,
            )

        pnls   = [t.pnl for t in trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate   = len(wins) / len(pnls)
        avg_win    = float(np.mean(wins))  if wins   else 0.0
        avg_loss   = float(np.mean(losses)) if losses else 0.0
        pf         = _profit_factor(wins, losses)
        expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

        # Equity curve from these trades only (O(n) via cumsum)
        cumulative = list(float(self._initial_capital) + np.cumsum(pnls))
        eq_curve = [self._initial_capital] + cumulative
        returns  = [
            (eq_curve[i] - eq_curve[i - 1]) / eq_curve[i - 1]
            for i in range(1, len(eq_curve))
            if eq_curve[i - 1] > 0
        ]
        max_dd  = _max_drawdown(eq_curve)
        total_r = (eq_curve[-1] - self._initial_capital) / self._initial_capital

        sharpe  = _annualised_sharpe(returns)
        sortino = _annualised_sortino(returns)
        calmar  = _calmar(total_r, max_dd)

        current_streak, max_win_streak, max_loss_streak = _streak_stats(trades)

        avg_dur = float(np.mean([t.duration_seconds for t in trades])) if trades else 0.0

        return PerformanceMetrics(
            label=label,
            trade_count=len(trades),
            total_pnl=sum(pnls),
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=pf,
            expectancy=expectancy,
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            max_dd_pct=max_dd,
            current_streak=current_streak,
            max_win_streak=max_win_streak,
            max_loss_streak=max_loss_streak,
            avg_duration_sec=avg_dur,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_analytics_instance: Optional[PortfolioPerformanceAnalytics] = None
_analytics_lock = threading.Lock()


def get_portfolio_performance_analytics(
    initial_capital: float = 10_000.0,
    max_trades: int = MAX_TRADES_IN_MEMORY,
) -> PortfolioPerformanceAnalytics:
    """
    Return the process-wide PortfolioPerformanceAnalytics singleton.

    Constructor arguments are applied only on first creation.
    """
    global _analytics_instance
    with _analytics_lock:
        if _analytics_instance is None:
            _analytics_instance = PortfolioPerformanceAnalytics(
                initial_capital=initial_capital,
                max_trades=max_trades,
            )
            logger.info(
                "✅ PortfolioPerformanceAnalytics initialised "
                "(capital=$%s, max_trades=%d)",
                f"{initial_capital:,.0f}",
                max_trades,
            )
    return _analytics_instance
