"""
NIJA Regime-Aware Memory
=========================

Maintains **separate learning memory** for each market regime so that the bot
accumulates regime-specific knowledge without cross-contaminating insights
between bull, bear, and sideways conditions.

For each regime the module tracks a rolling window of trade outcomes and
derives:

  * Win rate
  * Average PnL (USD)
  * Sharpe ratio (rolling, annualised approximation)
  * Profit factor
  * EMA-smoothed composite quality score  (0–100)

A lightweight **recommendation** is also emitted per regime:

  * ``SCALE_UP``   — regime is performing well → increase position size
  * ``SCALE_DOWN`` — regime is under-performing → reduce position size
  * ``NEUTRAL``    — not enough data or results are mixed

Architecture
------------
::

    ┌─────────────────────────────────────────────────────────────┐
    │                  RegimeAwareMemory                          │
    │                                                             │
    │  _memories: {regime: _RegimeMemory}                        │
    │    "BULL"     → win_rate, sharpe, avg_pnl, score, …        │
    │    "BEAR"     → …                                           │
    │    "SIDEWAYS" → …                                           │
    │                                                             │
    │  record_trade(regime, pnl_usd, is_win)                      │
    │    → routes to the correct _RegimeMemory, updates EMA       │
    │                                                             │
    │  get_stats(regime) → RegimeStats snapshot                   │
    │                                                             │
    │  get_recommendation(regime) → "SCALE_UP" | "SCALE_DOWN"    │
    │                               | "NEUTRAL"                   │
    │                                                             │
    │  get_report() → multi-regime dashboard string               │
    └─────────────────────────────────────────────────────────────┘

Public API
----------
::

    from bot.regime_aware_memory import get_regime_aware_memory

    mem = get_regime_aware_memory()

    # After a trade closes, record it with its regime label:
    mem.record_trade(regime="BULL", pnl_usd=85.0, is_win=True)
    mem.record_trade(regime="BEAR", pnl_usd=-30.0, is_win=False)

    # Before sizing the next entry, get regime-specific insight:
    stats = mem.get_stats("BULL")
    print(stats.win_rate, stats.sharpe_ratio, stats.score)

    rec = mem.get_recommendation("BULL")   # → "SCALE_UP"

    # Full dashboard:
    print(mem.get_report())

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
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("nija.regime_aware_memory")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_REGIMES: List[str] = ["BULL", "BEAR", "SIDEWAYS"]

DEFAULT_WINDOW: int = 60          # rolling trade window per regime
DEFAULT_MIN_TRADES: int = 10      # minimum trades before scoring
DEFAULT_EMA_ALPHA: float = 0.12   # smoothing factor for composite score

# Annualisation constant (crypto trades 365 d/yr)
TRADING_DAYS_PER_YEAR: int = 365

# Score thresholds for recommendations
SCALE_UP_THRESHOLD: float = 62.0   # composite score above this → SCALE_UP
SCALE_DOWN_THRESHOLD: float = 40.0 # composite score below this → SCALE_DOWN

# Constituent weights (must sum to 1.0)
W_WIN_RATE: float = 0.35
W_PROFIT_FACTOR: float = 0.30
W_SHARPE: float = 0.25
W_AVG_PNL: float = 0.10

DATA_DIR = Path(__file__).parent.parent / "data"

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Recommendation(str, Enum):
    SCALE_UP = "SCALE_UP"
    NEUTRAL = "NEUTRAL"
    SCALE_DOWN = "SCALE_DOWN"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class RegimeStats:
    """Performance snapshot for a single market regime."""

    regime: str
    total_trades: int
    window_trades: int
    win_rate: float          # 0–1
    avg_pnl_usd: float       # mean PnL across window
    profit_factor: float     # gross profit / gross loss
    sharpe_ratio: float      # annualised approximation
    score: float             # EMA composite score 0–100
    recommendation: str      # SCALE_UP / NEUTRAL / SCALE_DOWN
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Internal per-regime state
# ---------------------------------------------------------------------------


class _RegimeMemory:
    """Mutable rolling memory for a single market regime."""

    def __init__(
        self,
        regime: str,
        window: int,
        min_trades: int,
        ema_alpha: float,
    ) -> None:
        self.regime = regime
        self.window = window
        self.min_trades = min_trades
        self.ema_alpha = ema_alpha

        self.pnl_window: Deque[float] = deque(maxlen=window)
        self.win_window: Deque[bool] = deque(maxlen=window)
        self.total_trades: int = 0
        self.ema_score: float = 50.0   # start neutral

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def record(self, pnl_usd: float, is_win: bool) -> None:
        self.pnl_window.append(pnl_usd)
        self.win_window.append(is_win)
        self.total_trades += 1

        if self.total_trades >= self.min_trades:
            new_score = self._compute_raw_score()
            self.ema_score = (
                self.ema_alpha * new_score
                + (1.0 - self.ema_alpha) * self.ema_score
            )

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    def win_rate(self) -> float:
        if not self.win_window:
            return 0.5
        return sum(self.win_window) / len(self.win_window)

    def avg_pnl_usd(self) -> float:
        if not self.pnl_window:
            return 0.0
        return sum(self.pnl_window) / len(self.pnl_window)

    def profit_factor(self) -> float:
        gross_profit = sum(p for p in self.pnl_window if p > 0)
        gross_loss = abs(sum(p for p in self.pnl_window if p < 0))
        if gross_loss < 1e-9:
            return 3.0 if gross_profit > 0 else 1.0
        return gross_profit / gross_loss

    def sharpe_ratio(self) -> float:
        """Rolling Sharpe (annualised approximation)."""
        if len(self.pnl_window) < 4:
            return 0.0
        arr = list(self.pnl_window)
        mean = sum(arr) / len(arr)
        variance = sum((x - mean) ** 2 for x in arr) / len(arr)
        std = math.sqrt(variance) if variance > 0 else 1e-9
        scale = math.sqrt(TRADING_DAYS_PER_YEAR / self.window)
        return (mean / std) * scale

    # ------------------------------------------------------------------
    # Composite score  (0–100)
    # ------------------------------------------------------------------

    def _compute_raw_score(self) -> float:
        """Combine individual metrics into a 0–100 score."""
        # Win rate component (0–100)
        wr_score = self.win_rate() * 100.0

        # Profit factor component: clamp PF to [0, 3], map to [0, 100]
        pf = min(self.profit_factor(), 3.0)
        pf_score = (pf / 3.0) * 100.0

        # Sharpe component: clamp Sharpe to [-2, 4], map to [0, 100]
        sharpe = max(-2.0, min(self.sharpe_ratio(), 4.0))
        sharpe_score = ((sharpe + 2.0) / 6.0) * 100.0

        # Avg PnL component: map to [0, 100] via soft sigmoid
        avg = self.avg_pnl_usd()
        # Normalise: $0 → 50, >$0 → >50, <$0 → <50 (scale of $200 range)
        avg_score = 50.0 + (avg / 200.0) * 50.0
        avg_score = max(0.0, min(avg_score, 100.0))

        return (
            W_WIN_RATE * wr_score
            + W_PROFIT_FACTOR * pf_score
            + W_SHARPE * sharpe_score
            + W_AVG_PNL * avg_score
        )

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def recommendation(self) -> Recommendation:
        if self.total_trades < self.min_trades:
            return Recommendation.NEUTRAL
        if self.ema_score >= SCALE_UP_THRESHOLD:
            return Recommendation.SCALE_UP
        if self.ema_score <= SCALE_DOWN_THRESHOLD:
            return Recommendation.SCALE_DOWN
        return Recommendation.NEUTRAL

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> RegimeStats:
        return RegimeStats(
            regime=self.regime,
            total_trades=self.total_trades,
            window_trades=len(self.pnl_window),
            win_rate=self.win_rate(),
            avg_pnl_usd=self.avg_pnl_usd(),
            profit_factor=self.profit_factor(),
            sharpe_ratio=self.sharpe_ratio(),
            score=round(self.ema_score, 2),
            recommendation=self.recommendation().value,
        )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class RegimeAwareMemory:
    """
    Maintains independent rolling learning memories for BULL, BEAR, and
    SIDEWAYS market regimes so that strategy insights remain regime-pure.

    Thread-safe singleton via :func:`get_regime_aware_memory`.
    """

    def __init__(
        self,
        window: int = DEFAULT_WINDOW,
        min_trades: int = DEFAULT_MIN_TRADES,
        ema_alpha: float = DEFAULT_EMA_ALPHA,
        extra_regimes: Optional[List[str]] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._window = window
        self._min_trades = min_trades
        self._ema_alpha = ema_alpha

        regimes = list(SUPPORTED_REGIMES)
        if extra_regimes:
            for r in extra_regimes:
                normalized = r.upper()
                if normalized not in regimes:
                    regimes.append(normalized)

        self._memories: Dict[str, _RegimeMemory] = {
            r: _RegimeMemory(r, window, min_trades, ema_alpha)
            for r in regimes
        }

        logger.info(
            "✅ RegimeAwareMemory initialised — regimes: %s",
            list(self._memories.keys()),
        )

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        regime: str,
        pnl_usd: float,
        is_win: bool,
    ) -> None:
        """
        Record a closed trade outcome for the given regime.

        Args:
            regime:   Market regime label (e.g. ``"BULL"``, ``"BEAR"``,
                      ``"SIDEWAYS"``).  Case-insensitive.
            pnl_usd:  Realised PnL in USD (positive = win, negative = loss).
            is_win:   ``True`` if the trade was profitable.
        """
        key = regime.upper()
        with self._lock:
            if key not in self._memories:
                # Auto-register unknown regimes
                self._memories[key] = _RegimeMemory(
                    key, self._window, self._min_trades, self._ema_alpha
                )
                logger.info("RegimeAwareMemory: auto-registered regime %s", key)
            self._memories[key].record(pnl_usd, is_win)

        logger.debug(
            "RegimeAwareMemory: recorded %s | pnl=%.2f | win=%s",
            key,
            pnl_usd,
            is_win,
        )

    def get_stats(self, regime: str) -> RegimeStats:
        """
        Return a :class:`RegimeStats` snapshot for the given regime.

        Args:
            regime: Market regime label (case-insensitive).

        Returns:
            :class:`RegimeStats` snapshot.
        """
        key = regime.upper()
        with self._lock:
            if key not in self._memories:
                self._memories[key] = _RegimeMemory(
                    key, self._window, self._min_trades, self._ema_alpha
                )
            return self._memories[key].snapshot()

    def get_recommendation(self, regime: str) -> str:
        """
        Return the trade-sizing recommendation for the given regime.

        Returns:
            ``"SCALE_UP"``, ``"SCALE_DOWN"``, or ``"NEUTRAL"``
        """
        return self.get_stats(regime).recommendation

    def get_all_stats(self) -> Dict[str, RegimeStats]:
        """Return stats snapshots for every tracked regime."""
        with self._lock:
            return {r: mem.snapshot() for r, mem in self._memories.items()}

    # ------------------------------------------------------------------
    # Quality multiplier (drop-in for position sizing)
    # ------------------------------------------------------------------

    def get_quality_multiplier(self, regime: str) -> float:
        """
        Translate the regime score into a position-size multiplier.

        Mapping
        -------
        * SCALE_UP   → ``1.20`` (add 20 % to base size)
        * SCALE_DOWN → ``0.70`` (reduce base size by 30 %)
        * NEUTRAL    → ``1.00``

        Args:
            regime: Market regime label (case-insensitive).

        Returns:
            float multiplier in ``[0.70, 1.20]``.
        """
        rec = self.get_recommendation(regime)
        if rec == Recommendation.SCALE_UP.value:
            return 1.20
        if rec == Recommendation.SCALE_DOWN.value:
            return 0.70
        return 1.00

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Return a human-readable multi-regime performance dashboard."""
        lines: List[str] = [
            "",
            "=" * 70,
            "REGIME-AWARE MEMORY — Performance Dashboard",
            "=" * 70,
            f"  Generated : {datetime.now(timezone.utc).isoformat()}",
            f"  Window    : {self._window} trades per regime",
            f"  Min trades: {self._min_trades} (before scoring)",
            "",
        ]

        all_stats = self.get_all_stats()
        for regime in sorted(all_stats):
            s = all_stats[regime]
            lines += [
                f"  [{regime}]",
                f"    Trades (total / window) : {s.total_trades} / {s.window_trades}",
                f"    Win Rate                : {s.win_rate * 100:.1f}%",
                f"    Avg PnL                 : ${s.avg_pnl_usd:.2f}",
                f"    Profit Factor           : {s.profit_factor:.2f}",
                f"    Sharpe (rolling)        : {s.sharpe_ratio:.2f}",
                f"    Composite Score         : {s.score:.1f} / 100",
                f"    Recommendation          : {s.recommendation}",
                "",
            ]

        lines.append("=" * 70)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_snapshot(self, path: Optional[Path] = None) -> Path:
        """Persist all regime stats to a JSON file and return the path."""
        if path is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            path = DATA_DIR / "regime_aware_memory.json"

        payload = {
            r: {
                "total_trades": s.total_trades,
                "window_trades": s.window_trades,
                "win_rate": s.win_rate,
                "avg_pnl_usd": s.avg_pnl_usd,
                "profit_factor": s.profit_factor,
                "sharpe_ratio": s.sharpe_ratio,
                "score": s.score,
                "recommendation": s.recommendation,
            }
            for r, s in self.get_all_stats().items()
        }
        payload["_saved_at"] = datetime.now(timezone.utc).isoformat()

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))
        logger.info("RegimeAwareMemory: snapshot saved → %s", path)
        return path


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[RegimeAwareMemory] = None
_INSTANCE_LOCK = threading.Lock()


def get_regime_aware_memory(
    window: int = DEFAULT_WINDOW,
    min_trades: int = DEFAULT_MIN_TRADES,
    ema_alpha: float = DEFAULT_EMA_ALPHA,
    reset: bool = False,
) -> RegimeAwareMemory:
    """
    Return the process-wide :class:`RegimeAwareMemory` singleton.

    Args:
        window:     Rolling window length (trades per regime).
        min_trades: Minimum trades before scoring kicks in.
        ema_alpha:  EMA smoothing factor for composite score.
        reset:      Force re-creation (testing only).
    """
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None or reset:
            _INSTANCE = RegimeAwareMemory(window, min_trades, ema_alpha)
    return _INSTANCE
