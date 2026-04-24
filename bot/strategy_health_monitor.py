"""
NIJA Strategy Health Monitor
==============================

Tracks the live health of every active strategy by maintaining rolling
performance statistics and emitting health scores that can gate or suspend
underperforming strategies automatically.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────────┐
  │                  StrategyHealthMonitor                            │
  │                                                                   │
  │  Per-strategy rolling window (configurable, default 50 trades):   │
  │                                                                   │
  │  • Win Rate         – fraction of winning trades                  │
  │  • Profit Factor    – gross profit / gross loss                   │
  │  • Sharpe Ratio     – mean return / std return (annualised)       │
  │  • Max Drawdown     – peak-to-trough over rolling window          │
  │  • EMA Score        – exponentially smoothed composite (0–100)    │
  │                                                                   │
  │  Health Levels: HEALTHY → WATCHING → DEGRADED → SUSPENDED        │
  │                                                                   │
  │  Suspension: strategies below SUSPENDED threshold are blocked     │
  │  from new entries until they recover or are manually reset.       │
  │                                                                   │
  │  Audit: every status change logged to                             │
  │  data/strategy_health.jsonl                                       │
  └──────────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.strategy_health_monitor import get_strategy_health_monitor

    monitor = get_strategy_health_monitor()

    # After every trade closes:
    monitor.record_trade(
        strategy="ApexTrend",
        pnl_usd=120.0,
        is_win=True,
        regime="BULL_TRENDING",
    )

    # Before opening a new position:
    status = monitor.get_health(strategy="ApexTrend")
    if not status.is_tradeable:
        logger.warning("Strategy %s suspended: %s", strategy, status.reason)
        return

    # Full dashboard:
    print(monitor.get_dashboard())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.strategy_health_monitor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WINDOW: int = 50               # rolling trade window
DEFAULT_MIN_TRADES: int = 10           # minimum trades before scoring
DEFAULT_EMA_ALPHA: float = 0.10        # EMA smoothing for composite score

# Crypto markets trade 365 days a year; use 365 for annualisation.
# For traditional markets you would typically use 252 (trading days/year).
TRADING_DAYS_PER_YEAR: int = 365

# Health thresholds (composite score 0–100)
THRESHOLD_HEALTHY: float = 65.0
THRESHOLD_WATCHING: float = 50.0
THRESHOLD_DEGRADED: float = 35.0
# Below DEGRADED → SUSPENDED

# Constituent weights for composite score
W_WIN_RATE: float = 0.30
W_PROFIT_FACTOR: float = 0.30
W_SHARPE: float = 0.25
W_DRAWDOWN: float = 0.15

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Enums and data containers
# ---------------------------------------------------------------------------

class HealthLevel(str, Enum):
    HEALTHY = "HEALTHY"
    WATCHING = "WATCHING"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class StrategyHealthStatus:
    """Health snapshot for one strategy."""

    strategy: str
    health_level: HealthLevel
    composite_score: float          # 0–100
    win_rate: float                 # 0–1
    profit_factor: float            # gross profit / gross loss
    sharpe_ratio: float             # annualised (rolling window)
    max_drawdown_pct: float         # peak-to-trough as positive %
    total_trades: int               # all-time trade count
    window_trades: int              # trades in rolling window
    is_tradeable: bool
    reason: str
    regime_breakdown: Dict[str, float] = field(default_factory=dict)  # regime → avg pnl
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class StrategyDashboard:
    """Aggregate report across all tracked strategies."""

    strategies: List[StrategyHealthStatus]
    num_healthy: int
    num_watching: int
    num_degraded: int
    num_suspended: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Internal per-strategy state
# ---------------------------------------------------------------------------

class _StrategyState:
    """Mutable rolling state for one strategy."""

    def __init__(self, window: int, min_trades: int, ema_alpha: float) -> None:
        self.window = window
        self.min_trades = min_trades
        self.ema_alpha = ema_alpha

        self.pnl_window: Deque[float] = deque(maxlen=window)
        self.win_window: Deque[bool] = deque(maxlen=window)
        self.total_trades: int = 0
        self.ema_score: float = 50.0          # start neutral
        self.is_suspended: bool = False
        self.suspension_reason: str = ""
        self.regime_pnl: Dict[str, List[float]] = {}  # regime → pnl list

    def record(self, pnl_usd: float, is_win: bool, regime: Optional[str]) -> None:
        self.pnl_window.append(pnl_usd)
        self.win_window.append(is_win)
        self.total_trades += 1
        if regime:
            self.regime_pnl.setdefault(regime, []).append(pnl_usd)

    def win_rate(self) -> float:
        if not self.win_window:
            return 0.5
        return sum(self.win_window) / len(self.win_window)

    def profit_factor(self) -> float:
        gross_profit = sum(p for p in self.pnl_window if p > 0)
        gross_loss = abs(sum(p for p in self.pnl_window if p < 0))
        if gross_loss < 1e-9:
            return 3.0 if gross_profit > 0 else 1.0
        return gross_profit / gross_loss

    def sharpe_ratio(self) -> float:
        """Approximation: mean/std of pnl, scaled to annualised-like value."""
        if len(self.pnl_window) < 4:
            return 0.0
        arr = list(self.pnl_window)
        mean = sum(arr) / len(arr)
        variance = sum((x - mean) ** 2 for x in arr) / len(arr)
        std = math.sqrt(variance) if variance > 0 else 1e-9
        # Scale by sqrt(TRADING_DAYS_PER_YEAR / window) to approximate annualisation
        scale = math.sqrt(TRADING_DAYS_PER_YEAR / self.window)
        return (mean / std) * scale

    def max_drawdown_pct(self) -> float:
        """Peak-to-trough drawdown over the rolling window (as positive %)."""
        if len(self.pnl_window) < 2:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in self.pnl_window:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        if peak <= 0:
            return 0.0
        return (max_dd / peak) * 100.0

    def composite_score(self) -> float:
        """Combine metrics into a 0–100 score."""
        # Normalize each component to [0, 100]
        wr_score = self.win_rate() * 100.0

        pf = self.profit_factor()
        # profit factor 0→0, 1→50, 2→75, 3+→100
        pf_score = min(pf / 3.0, 1.0) * 100.0

        sharpe = self.sharpe_ratio()
        # sharpe: -2→0, 0→50, 2→100
        sh_score = max(0.0, min(100.0, 50.0 + sharpe * 25.0))

        dd = self.max_drawdown_pct()
        # drawdown: 0%→100, 20%→50, 50%+→0
        dd_score = max(0.0, 100.0 - dd * 2.0)

        raw = (
            W_WIN_RATE * wr_score
            + W_PROFIT_FACTOR * pf_score
            + W_SHARPE * sh_score
            + W_DRAWDOWN * dd_score
        )
        return round(raw, 2)

    def update_ema(self) -> float:
        """Update EMA composite score and return current value."""
        if self.total_trades < self.min_trades:
            return self.ema_score
        current = self.composite_score()
        self.ema_score = (
            self.ema_alpha * current + (1 - self.ema_alpha) * self.ema_score
        )
        return self.ema_score

    def regime_breakdown(self) -> Dict[str, float]:
        return {
            regime: round(sum(pnls) / len(pnls), 4)
            for regime, pnls in self.regime_pnl.items()
            if pnls
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class StrategyHealthMonitor:
    """
    Monitors per-strategy performance and emits health verdicts.

    Parameters
    ----------
    window : int
        Rolling trade window for statistics (default 50).
    min_trades : int
        Minimum trades before health scoring activates (default 10).
    ema_alpha : float
        EMA smoothing factor for composite score (default 0.10).
    """

    def __init__(
        self,
        window: int = DEFAULT_WINDOW,
        min_trades: int = DEFAULT_MIN_TRADES,
        ema_alpha: float = DEFAULT_EMA_ALPHA,
    ) -> None:
        self.window = window
        self.min_trades = min_trades
        self.ema_alpha = ema_alpha

        self._strategies: Dict[str, _StrategyState] = {}
        self._lock = threading.RLock()

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = DATA_DIR / "strategy_health.jsonl"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        strategy: str,
        pnl_usd: float,
        is_win: bool,
        regime: Optional[str] = None,
    ) -> StrategyHealthStatus:
        """
        Record a completed trade result for *strategy*.

        Parameters
        ----------
        strategy : str
            Strategy identifier (e.g. "ApexTrend").
        pnl_usd : float
            Realised P&L in USD (negative for losses).
        is_win : bool
            ``True`` if the trade was profitable.
        regime : str, optional
            Market regime at time of trade.

        Returns
        -------
        StrategyHealthStatus
            Updated health snapshot.
        """
        with self._lock:
            state = self._get_or_create(strategy)
            prev_suspended = state.is_suspended
            state.record(pnl_usd, is_win, regime)
            state.update_ema()

            status = self._build_status(strategy, state)

            # Auto-suspend/resume logic
            if not state.is_suspended and status.health_level == HealthLevel.SUSPENDED:
                state.is_suspended = True
                state.suspension_reason = status.reason
                logger.warning(
                    "Strategy %s SUSPENDED (score=%.1f): %s",
                    strategy,
                    status.composite_score,
                    status.reason,
                )
            elif state.is_suspended and status.health_level in (
                HealthLevel.DEGRADED,
                HealthLevel.WATCHING,
                HealthLevel.HEALTHY,
            ):
                state.is_suspended = False
                state.suspension_reason = ""
                logger.info(
                    "Strategy %s resumed (score=%.1f)",
                    strategy,
                    status.composite_score,
                )

            if state.is_suspended != prev_suspended:
                self._log_status_change(status)

            return status

    def get_health(self, strategy: str) -> StrategyHealthStatus:
        """Return the current health status for *strategy*."""
        with self._lock:
            state = self._get_or_create(strategy)
            return self._build_status(strategy, state)

    def is_tradeable(self, strategy: str) -> bool:
        """Return ``True`` if *strategy* is allowed to open new positions."""
        return self.get_health(strategy).is_tradeable

    def force_suspend(self, strategy: str, reason: str = "manual") -> None:
        """Manually suspend a strategy."""
        with self._lock:
            state = self._get_or_create(strategy)
            state.is_suspended = True
            state.suspension_reason = reason
            logger.warning("Strategy %s manually suspended: %s", strategy, reason)

    def force_resume(self, strategy: str) -> None:
        """Manually resume a previously suspended strategy."""
        with self._lock:
            state = self._get_or_create(strategy)
            state.is_suspended = False
            state.suspension_reason = ""
            logger.info("Strategy %s manually resumed", strategy)

    def get_dashboard(self) -> StrategyDashboard:
        """Return health status for all tracked strategies."""
        with self._lock:
            statuses = [
                self._build_status(name, state)
                for name, state in self._strategies.items()
            ]
        counts = {level: 0 for level in HealthLevel}
        for s in statuses:
            counts[s.health_level] += 1
        return StrategyDashboard(
            strategies=statuses,
            num_healthy=counts[HealthLevel.HEALTHY],
            num_watching=counts[HealthLevel.WATCHING],
            num_degraded=counts[HealthLevel.DEGRADED],
            num_suspended=counts[HealthLevel.SUSPENDED],
        )

    def reset_strategy(self, strategy: str) -> None:
        """Clear all historical data for *strategy* and start fresh."""
        with self._lock:
            if strategy in self._strategies:
                del self._strategies[strategy]
                logger.info("Strategy %s health state reset", strategy)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, strategy: str) -> _StrategyState:
        if strategy not in self._strategies:
            self._strategies[strategy] = _StrategyState(
                self.window, self.min_trades, self.ema_alpha
            )
        return self._strategies[strategy]

    def _build_status(self, strategy: str, state: _StrategyState) -> StrategyHealthStatus:
        """Compute the full StrategyHealthStatus from *state*."""
        if state.total_trades < state.min_trades:
            return StrategyHealthStatus(
                strategy=strategy,
                health_level=HealthLevel.INSUFFICIENT_DATA,
                composite_score=state.ema_score,
                win_rate=state.win_rate(),
                profit_factor=state.profit_factor(),
                sharpe_ratio=state.sharpe_ratio(),
                max_drawdown_pct=state.max_drawdown_pct(),
                total_trades=state.total_trades,
                window_trades=len(state.pnl_window),
                is_tradeable=True,
                reason=f"insufficient data ({state.total_trades}/{state.min_trades} trades)",
                regime_breakdown=state.regime_breakdown(),
            )

        score = state.ema_score

        if state.is_suspended:
            level = HealthLevel.SUSPENDED
            tradeable = False
            reason = state.suspension_reason or f"score={score:.1f} below threshold"
        elif score >= THRESHOLD_HEALTHY:
            level = HealthLevel.HEALTHY
            tradeable = True
            reason = f"score={score:.1f} – healthy"
        elif score >= THRESHOLD_WATCHING:
            level = HealthLevel.WATCHING
            tradeable = True
            reason = f"score={score:.1f} – monitoring closely"
        elif score >= THRESHOLD_DEGRADED:
            level = HealthLevel.DEGRADED
            tradeable = True
            reason = f"score={score:.1f} – degraded, reduce size"
        else:
            level = HealthLevel.SUSPENDED
            tradeable = False
            reason = f"score={score:.1f} – auto-suspended (below {THRESHOLD_DEGRADED:.0f})"

        return StrategyHealthStatus(
            strategy=strategy,
            health_level=level,
            composite_score=score,
            win_rate=state.win_rate(),
            profit_factor=state.profit_factor(),
            sharpe_ratio=state.sharpe_ratio(),
            max_drawdown_pct=state.max_drawdown_pct(),
            total_trades=state.total_trades,
            window_trades=len(state.pnl_window),
            is_tradeable=tradeable,
            reason=reason,
            regime_breakdown=state.regime_breakdown(),
        )

    def _log_status_change(self, status: StrategyHealthStatus) -> None:
        try:
            record = {
                "timestamp": status.timestamp,
                "strategy": status.strategy,
                "health_level": status.health_level.value,
                "composite_score": round(status.composite_score, 2),
                "win_rate": round(status.win_rate, 4),
                "profit_factor": round(status.profit_factor, 4),
                "sharpe_ratio": round(status.sharpe_ratio, 4),
                "max_drawdown_pct": round(status.max_drawdown_pct, 2),
                "is_tradeable": status.is_tradeable,
                "reason": status.reason,
            }
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_shm_instance: Optional[StrategyHealthMonitor] = None
_shm_lock = threading.Lock()


def get_strategy_health_monitor(**kwargs) -> StrategyHealthMonitor:
    """Return the process-wide :class:`StrategyHealthMonitor` singleton."""
    global _shm_instance
    with _shm_lock:
        if _shm_instance is None:
            _shm_instance = StrategyHealthMonitor(**kwargs)
            logger.info("StrategyHealthMonitor singleton created")
    return _shm_instance
