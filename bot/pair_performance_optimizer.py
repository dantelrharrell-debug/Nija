"""
NIJA Pair Performance Optimizer
=================================

Per-symbol win-rate feedback loop that does three things:

  1. **Kill underperformers automatically** — pairs whose rolling win-rate
     falls below ``KILL_WIN_RATE`` (default 35 %) *and* whose profit factor
     is below ``KILL_PROFIT_FACTOR`` (default 0.70) after a minimum sample
     of trades are silently skipped in the scan loop.  The kill is
     temporary: it lifts automatically once the pair accumulates a recovery
     run of ``RECOVERY_TRADES`` consecutive wins.

  2. **Boost top performers** — pairs whose rolling win-rate exceeds
     ``BOOST_WIN_RATE`` (default 62 %) *and* whose profit factor exceeds
     ``BOOST_PROFIT_FACTOR`` (default 1.40) receive a position-size
     multiplier of ``BOOST_MULTIPLIER`` (default 1.25×) so more capital
     flows into proven setups.

  3. **Strategy performance ranking** — tracks gross P&L and win rate
     per strategy name so the operator can see which strategy is
     contributing most and which should be retired.

Data source
-----------
The optimizer does **not** maintain its own trade store.  It reads
per-pair and per-strategy stats directly from the singleton
``PnLAnalyticsLayer`` (``bot/pnl_analytics_layer.py``), which is already
integrated in ``trading_strategy.py``.  This means zero double-counting
and a single source of truth.

Architecture
------------
::

    PairPerformanceOptimizer (singleton via get_pair_performance_optimizer())
    │
    ├── should_skip_pair(symbol)  → bool
    │     True  → entry blocked (underperformer kill active)
    │     False → entry allowed
    │
    ├── get_pair_size_multiplier(symbol) → float
    │     > 1.0  → top-performer boost
    │     1.0    → neutral
    │     (underperformers are always skipped before this is called)
    │
    ├── get_worst_strategies(n=3) → List[str]
    │     Strategy names ranked by total_pnl_usd ascending
    │
    ├── get_best_strategies(n=3) → List[str]
    │     Strategy names ranked by total_pnl_usd descending
    │
    └── get_report() → dict

Usage
-----
::

    from bot.pair_performance_optimizer import get_pair_performance_optimizer

    opt = get_pair_performance_optimizer()

    # In the scan loop, before sniper filter:
    if opt.should_skip_pair(symbol):
        continue

    # In position sizing:
    position_size *= opt.get_pair_size_multiplier(symbol)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.pair_performance_optimizer")

# ---------------------------------------------------------------------------
# Thresholds (module-level constants so they are easy to tune)
# ---------------------------------------------------------------------------

# Minimum trades on a pair before kill / boost decisions are made.
MIN_TRADES_FOR_DECISION: int = 20

# Kill gate — pair is skipped when BOTH conditions hold after MIN_TRADES.
KILL_WIN_RATE: float = 0.35        # 35 % win rate or below
KILL_PROFIT_FACTOR: float = 0.70   # profit factor 0.70 or below

# Boost gate — pair gets bigger size when BOTH conditions hold.
BOOST_WIN_RATE: float = 0.62       # 62 % win rate or above
BOOST_PROFIT_FACTOR: float = 1.40  # profit factor 1.40 or above

# Position-size multiplier applied to boosted pairs.
BOOST_MULTIPLIER: float = 1.25

# Number of consecutive wins on a killed pair to lift the kill flag.
RECOVERY_TRADES: int = 3


# ---------------------------------------------------------------------------
# Internal state per pair
# ---------------------------------------------------------------------------

@dataclass
class _PairState:
    """Runtime state tracked per symbol (kill / boost flags, recovery streak)."""
    symbol: str
    killed: bool = False
    boosted: bool = False
    consecutive_wins_after_kill: int = 0  # for kill recovery

    def reset_recovery(self) -> None:
        self.consecutive_wins_after_kill = 0


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PairPerformanceOptimizer:
    """
    Feedback-loop optimiser that silently kills underperforming pairs and
    boosts top performers based on rolling per-pair PnL analytics.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: Dict[str, _PairState] = {}
        # Lazy reference to PnLAnalyticsLayer singleton (avoids circular import)
        self._analytics = None
        logger.info(
            "✅ PairPerformanceOptimizer ready — "
            "kill(wr<%.0f%% pf<%.2f after %d trades) "
            "boost(wr>%.0f%% pf>%.2f → %.2f×)",
            KILL_WIN_RATE * 100, KILL_PROFIT_FACTOR, MIN_TRADES_FOR_DECISION,
            BOOST_WIN_RATE * 100, BOOST_PROFIT_FACTOR, BOOST_MULTIPLIER,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _get_analytics(self):
        """Lazily fetch the PnLAnalyticsLayer singleton."""
        if self._analytics is None:
            try:
                from pnl_analytics_layer import get_pnl_analytics_layer
                self._analytics = get_pnl_analytics_layer()
            except ImportError:
                try:
                    from bot.pnl_analytics_layer import get_pnl_analytics_layer
                    self._analytics = get_pnl_analytics_layer()
                except ImportError:
                    pass
        return self._analytics

    def _get_state(self, symbol: str) -> _PairState:
        """Return (or create) the mutable state object for *symbol*."""
        if symbol not in self._states:
            self._states[symbol] = _PairState(symbol=symbol)
        return self._states[symbol]

    def _evaluate_pair(self, symbol: str) -> Tuple[bool, bool]:
        """
        Re-evaluate kill / boost flags from current PnL analytics data.

        Returns ``(killed, boosted)`` tuple.
        """
        analytics = self._get_analytics()
        if analytics is None:
            return False, False

        try:
            ps = analytics.get_pair_stats(symbol)
        except Exception:
            return False, False

        if ps is None or ps.total_trades < MIN_TRADES_FOR_DECISION:
            return False, False

        wr = ps.win_rate
        pf = ps.profit_factor

        killed = (wr <= KILL_WIN_RATE) and (pf <= KILL_PROFIT_FACTOR)
        boosted = (not killed) and (wr >= BOOST_WIN_RATE) and (pf >= BOOST_PROFIT_FACTOR)
        return killed, boosted

    # ── Public API ────────────────────────────────────────────────────────────

    def should_skip_pair(self, symbol: str) -> bool:
        """
        Return ``True`` if the pair should be skipped (underperformer kill).

        The kill flag lifts automatically after ``RECOVERY_TRADES`` consecutive
        wins so a pair can re-qualify as market conditions improve.
        """
        with self._lock:
            killed, boosted = self._evaluate_pair(symbol)
            state = self._get_state(symbol)

            if killed:
                if not state.killed:
                    # First time kill fires
                    state.killed = True
                    state.boosted = False
                    state.reset_recovery()
                    analytics = self._get_analytics()
                    ps = analytics.get_pair_stats(symbol) if analytics else None
                    wr_pct = (ps.win_rate * 100) if ps else 0.0
                    pf_val = ps.profit_factor if ps else 0.0
                    logger.warning(
                        "   ☠️  PAIR KILLED: %s | win_rate=%.1f%% profit_factor=%.2f "
                        "— skipping all new entries until %d consecutive wins",
                        symbol, wr_pct, pf_val, RECOVERY_TRADES,
                    )
                return True  # still in kill zone

            # Not killed → check if previously killed (recovery logic handled
            # by notify_trade_outcome, not here — we just lift the flag)
            if state.killed:
                # Stats improved past kill threshold — lift proactively
                state.killed = False
                state.reset_recovery()
                logger.info(
                    "   ♻️  PAIR REVIVED: %s — stats recovered past kill threshold",
                    symbol,
                )

            state.boosted = boosted
            return False

    def notify_trade_outcome(self, symbol: str, is_win: bool) -> None:
        """
        Called after each closed trade so the optimizer can track recovery
        streaks for killed pairs.  This is optional but enables faster revival.
        """
        with self._lock:
            state = self._get_state(symbol)
            if not state.killed:
                return
            if is_win:
                state.consecutive_wins_after_kill += 1
                if state.consecutive_wins_after_kill >= RECOVERY_TRADES:
                    state.killed = False
                    state.reset_recovery()
                    logger.info(
                        "   ♻️  PAIR REVIVED (streak): %s — %d consecutive wins after kill",
                        symbol, RECOVERY_TRADES,
                    )
            else:
                state.reset_recovery()

    def get_pair_size_multiplier(self, symbol: str) -> float:
        """
        Return the position-size multiplier for *symbol*.

        * ``BOOST_MULTIPLIER`` (e.g. 1.25) for top performers.
        * ``1.0`` for normal pairs.
        * (Underperformers should already be filtered by ``should_skip_pair``.)
        """
        with self._lock:
            _, boosted = self._evaluate_pair(symbol)
            if boosted:
                return BOOST_MULTIPLIER
            return 1.0

    def get_worst_strategies(self, n: int = 3) -> List[str]:
        """Return the *n* worst-performing strategy names by total P&L."""
        analytics = self._get_analytics()
        if analytics is None:
            return []
        try:
            all_stats = analytics.get_all_strategy_stats()
            sorted_strats = sorted(all_stats, key=lambda s: s.total_pnl_usd)
            return [s.strategy for s in sorted_strats[:n]]
        except Exception:
            return []

    def get_best_strategies(self, n: int = 3) -> List[str]:
        """Return the *n* best-performing strategy names by total P&L."""
        analytics = self._get_analytics()
        if analytics is None:
            return []
        try:
            all_stats = analytics.get_all_strategy_stats()
            sorted_strats = sorted(all_stats, key=lambda s: s.total_pnl_usd, reverse=True)
            return [s.strategy for s in sorted_strats[:n]]
        except Exception:
            return []

    def get_report(self) -> dict:
        """Return a summary dict suitable for logging / dashboards."""
        with self._lock:
            killed = [s for s, st in self._states.items() if st.killed]
            boosted = [s for s, st in self._states.items() if st.boosted]
        return {
            "killed_pairs": killed,
            "killed_count": len(killed),
            "boosted_pairs": boosted,
            "boosted_count": len(boosted),
            "boost_multiplier": BOOST_MULTIPLIER,
            "kill_win_rate_threshold": KILL_WIN_RATE,
            "boost_win_rate_threshold": BOOST_WIN_RATE,
            "min_trades_for_decision": MIN_TRADES_FOR_DECISION,
            "worst_strategies": self.get_worst_strategies(3),
            "best_strategies": self.get_best_strategies(3),
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[PairPerformanceOptimizer] = None
_instance_lock = threading.Lock()


def get_pair_performance_optimizer() -> PairPerformanceOptimizer:
    """Return the process-wide singleton ``PairPerformanceOptimizer``."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PairPerformanceOptimizer()
    return _instance
