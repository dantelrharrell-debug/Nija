"""
NIJA Strategy Diversification Engine
=====================================

Runs multiple trading strategies simultaneously and allocates capital
dynamically based on the detected market regime and each strategy's
real-time performance—the same approach used by hedge funds to beat markets.

Strategy Roster
---------------
+---------------------+------------------------+---------------------+
| Strategy            | Best Regime            | Class               |
+=====================+========================+=====================+
| ApexTrendStrategy   | Bull / Trending        | TRENDING            |
+---------------------+------------------------+---------------------+
| MeanReversionStrategy| Sideways / Ranging    | RANGING             |
+---------------------+------------------------+---------------------+
| MomentumBreakoutStrategy| Volatility spikes  | VOLATILE            |
+---------------------+------------------------+---------------------+
| LiquidityReversalStrategy| Any (overlay)     | ALL                 |
+---------------------+------------------------+---------------------+

Capital Allocation Logic
------------------------
The engine auto-weights capital across active strategies:
  - Each strategy receives a base share of deployable capital.
  - The primary strategy for the detected regime gets a *boost* (configurable,
    default +50 % relative weight).
  - Strategies can be individually paused without restarting the engine.

Integration Example
-------------------
    from bot.strategy_diversification_engine import StrategyDiversificationEngine

    engine = StrategyDiversificationEngine(total_capital=10_000)

    # Every scan cycle:
    result = engine.get_best_signal(
        df=df,
        indicators=indicators,
        market_regime="TRENDING",  # from your regime detector
    )

    if result["signal"] in ("BUY", "SELL"):
        size = result["capital_allocation"]
        strategy_name = result["strategy"]
        ...

Author: NIJA Trading Systems
Version: 1.0
"""

import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.diversification_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum closed trades before performance scores influence weight
_MIN_TRADES_BEFORE_LEARNING: int = 10

# EMA decay for per-trade return smoothing (higher = slower adaptation)
_EMA_DECAY: float = 0.85

# Blend factor: how much performance score influences allocation when
# MIN_TRADES_BEFORE_LEARNING is reached (0.0 = pure regime, 1.0 = pure perf)
_PERF_BLEND: float = 0.50

# Rolling window for Sharpe estimation
_SHARPE_WINDOW: int = 30

# Sentinel profit factor used when a strategy has profit but zero losses.
# Kept finite (rather than float('inf')) so it can be used safely in arithmetic
# and persisted to JSON without special handling.
_MAX_PROFIT_FACTOR: float = 999.99

# Cap applied to the raw profit factor before feeding into composite_score().
# Limits the outsized influence of extreme PF values on the blended weight.
_MAX_PF_FOR_SCORE: float = 10.0

# Sharpe ratio is compressed via tanh(sharpe / _SHARPE_SCALE) to map the
# practically meaningful range (roughly −3 to +3) into [−1, +1].
_SHARPE_SCALE: float = 3.0

# Annualisation factor for Sharpe estimation.  Assumes each element of
# _recent_returns represents one closed trade and that ~365 trades are
# executed per year on average.  For lower-frequency strategies this factor
# can be overestimated; treat the resulting value as a relative ranking
# signal rather than an absolute Sharpe ratio.
_SHARPE_ANNUALISE: float = 365.0

# ---------------------------------------------------------------------------
# Strategy imports (support both bot.* and direct paths)
# ---------------------------------------------------------------------------
try:
    from strategies.apex_strategy import ApexTrendStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    from strategies.momentum_breakout import MomentumBreakoutStrategy
    from strategies.liquidity_reversal import LiquidityReversalStrategy
    from strategies.base_strategy import BaseStrategy
except ImportError:
    from bot.strategies.apex_strategy import ApexTrendStrategy
    from bot.strategies.mean_reversion import MeanReversionStrategy
    from bot.strategies.momentum_breakout import MomentumBreakoutStrategy
    from bot.strategies.liquidity_reversal import LiquidityReversalStrategy
    from bot.strategies.base_strategy import BaseStrategy


# ---------------------------------------------------------------------------
# Regime aliases (normalise incoming regime strings)
# ---------------------------------------------------------------------------
_REGIME_ALIASES: Dict[str, str] = {
    "trending": "TRENDING",
    "trend": "TRENDING",
    "strong_trend": "TRENDING",
    "weak_trend": "TRENDING",
    "bull": "TRENDING",
    "bullish": "TRENDING",
    "ranging": "RANGING",
    "range": "RANGING",
    "consolidation": "RANGING",
    "sideways": "RANGING",
    "neutral": "RANGING",
    "volatile": "VOLATILE",
    "volatility_expansion": "VOLATILE",
    "high_volatility": "VOLATILE",
    "breakout": "VOLATILE",
    "momentum": "VOLATILE",
}

# Which regime each strategy "owns" (its best fit)
_STRATEGY_HOME_REGIME: Dict[str, str] = {
    "ApexTrendStrategy": "TRENDING",
    "MeanReversionStrategy": "RANGING",
    "MomentumBreakoutStrategy": "VOLATILE",
    "LiquidityReversalStrategy": "ALL",
}


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class StrategyPerformanceRecord:
    """Rolling performance statistics for one strategy."""
    name: str
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl_usd: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    ema_return: float = 0.0        # EMA of normalised per-trade return [-1, 1]
    paused: bool = False
    _recent_returns: List[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return (self.winning_trades / self.total_trades) if self.total_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss > 0:
            return round(self.gross_profit / self.gross_loss, 4)
        return _MAX_PROFIT_FACTOR if self.gross_profit > 0 else 0.0

    @property
    def sharpe_estimate(self) -> float:
        if len(self._recent_returns) < 2:
            return 0.0
        n = len(self._recent_returns)
        mean = sum(self._recent_returns) / n
        variance = sum((r - mean) ** 2 for r in self._recent_returns) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0.0:
            return 0.0
        return (mean / std) * math.sqrt(_SHARPE_ANNUALISE)

    def composite_score(self) -> float:
        """Return a composite performance score in [-1, 1]."""
        if self.total_trades < _MIN_TRADES_BEFORE_LEARNING:
            return 0.0
        ema_score = self.ema_return
        wr_score = self.win_rate - 0.5
        pf = min(self.profit_factor, _MAX_PF_FOR_SCORE)
        pf_score = (pf - 1.0) / 5.0
        sharpe_score = math.tanh(self.sharpe_estimate / _SHARPE_SCALE)
        return (ema_score + wr_score + pf_score + sharpe_score) / 4.0


@dataclass
class StrategyAllocation:
    """Capital allocation for one strategy in the current cycle."""
    strategy_name: str
    home_regime: str
    allocated_capital: float
    weight: float           # 0.0 – 1.0, relative weight in this cycle
    is_primary: bool        # True when home_regime matches detected regime


@dataclass
class DiversifiedSignal:
    """
    Aggregated output from the Strategy Diversification Engine.

    Fields
    ------
    signal : str
        ``"BUY"``, ``"SELL"``, or ``"NONE"``.
    confidence : float
        0.0 – 1.0 composite confidence across contributing strategies.
    strategy : str
        Name of the highest-confidence strategy that produced this signal.
    regime : str
        Detected market regime at the time of evaluation.
    capital_allocation : float
        Capital (USD) recommended for deployment in this trade.
    contributing_strategies : list[str]
        Strategies that agreed on this signal direction.
    individual_signals : list[dict]
        Raw signal dicts from every strategy, for auditing.
    reason : str
        Human-readable explanation of the final decision.
    allocations : list[StrategyAllocation]
        Capital allocation breakdown per strategy for this cycle.
    """
    signal: str = "NONE"
    confidence: float = 0.0
    strategy: str = ""
    regime: str = "unknown"
    capital_allocation: float = 0.0
    contributing_strategies: List[str] = field(default_factory=list)
    individual_signals: List[Dict] = field(default_factory=list)
    reason: str = ""
    allocations: List[StrategyAllocation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class StrategyDiversificationEngine:
    """
    Runs all four NIJA strategies in parallel and allocates capital
    dynamically based on the current market regime and per-strategy weights.

    Parameters
    ----------
    total_capital : float
        Total deployable capital (USD).
    reserve_pct : float
        Fraction of capital to keep in reserve (default 0.20 = 20 %).
    regime_boost : float
        Additional relative weight granted to the on-regime (primary) strategy
        (default 0.50 = 50 % extra weight).
    min_confidence : float
        Minimum signal confidence to report a BUY/SELL (default 0.50).
    config : dict, optional
        Per-strategy config overrides keyed by strategy class name, e.g.::

            {
                "ApexTrendStrategy":     {"min_confirmations": 4},
                "MeanReversionStrategy": {"rsi_oversold": 30},
            }
    """

    def __init__(
        self,
        total_capital: float = 10_000.0,
        reserve_pct: float = 0.20,
        regime_boost: float = 0.50,
        min_confidence: float = 0.50,
        config: Optional[Dict] = None,
    ):
        self.total_capital = total_capital
        self.reserve_pct = reserve_pct
        self.regime_boost = regime_boost
        self.min_confidence = min_confidence
        self._config = config or {}
        self._lock = threading.RLock()

        # Build strategy pool
        self._strategies: Dict[str, BaseStrategy] = self._build_pool()

        # Per-strategy performance records (include paused state)
        self._perf: Dict[str, StrategyPerformanceRecord] = {
            name: StrategyPerformanceRecord(name=name)
            for name in self._strategies
        }

        logger.info(
            "StrategyDiversificationEngine initialised | capital=$%.2f | "
            "reserve=%.0f%% | regime_boost=%.0f%% | strategies=%s",
            total_capital,
            reserve_pct * 100,
            regime_boost * 100,
            list(self._strategies.keys()),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_best_signal(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        market_regime: str = "RANGING",
    ) -> DiversifiedSignal:
        """
        Query every active (non-paused) strategy, then return the best
        BUY/SELL opportunity.

        Algorithm
        ---------
        1. Normalise the market regime string.
        2. Compute capital allocations for this cycle (regime + performance blend).
        3. Run every active strategy's ``generate_signal()``.
        4. Collect strategies that agree on the same direction.
        5. Compute a composite confidence score (weighted by strategy capital
           allocation).
        6. Return the highest-confidence direction as the final signal.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV price DataFrame.
        indicators : dict
            Pre-computed technical indicators.
        market_regime : str
            Current market regime from the regime detector.

        Returns
        -------
        DiversifiedSignal
        """
        with self._lock:
            regime = _REGIME_ALIASES.get(market_regime.lower(), market_regime.upper())
            allocations = self._compute_allocations(regime)

            # Only query non-paused strategies
            active_names = {
                name for name, rec in self._perf.items() if not rec.paused
            }

            # Collect raw signals from every active strategy
            raw_signals: List[Dict] = []
            for name, strategy in self._strategies.items():
                if name not in active_names:
                    continue
                try:
                    sig = strategy.generate_signal(df, indicators)
                    alloc = next((a for a in allocations if a.strategy_name == name), None)
                    sig["strategy"] = name
                    sig["home_regime"] = _STRATEGY_HOME_REGIME.get(name, "ALL")
                    sig["capital_allocation"] = alloc.allocated_capital if alloc else 0.0
                    sig["weight"] = alloc.weight if alloc else 0.0
                    raw_signals.append(sig)
                except Exception as exc:
                    logger.warning("Strategy %s raised an error: %s", name, exc)

            # Find consensus direction (BUY or SELL)
            result = self._build_consensus(raw_signals, allocations, regime)
            return result

    def update_capital(self, new_total_capital: float) -> None:
        """Update total capital (e.g. after compounding profits)."""
        with self._lock:
            self.total_capital = new_total_capital
        logger.info("Capital updated to $%.2f", new_total_capital)

    def list_strategies(self) -> Dict[str, str]:
        """Return {strategy_name: home_regime} for logging / dashboard."""
        return {name: _STRATEGY_HOME_REGIME.get(name, "ALL") for name in self._strategies}

    def get_capital_allocations(self, market_regime: str = "RANGING") -> List[StrategyAllocation]:
        """Return capital allocation breakdown for a given regime."""
        regime = _REGIME_ALIASES.get(market_regime.lower(), market_regime.upper())
        return self._compute_allocations(regime)

    def record_trade(
        self,
        strategy: str,
        pnl_usd: float,
        is_win: bool,
        position_size_usd: float = 100.0,
    ) -> None:
        """
        Record a closed trade for a strategy and update its performance score.

        This allows the engine to blend regime-based weights with empirical
        performance scores when ``_MIN_TRADES_BEFORE_LEARNING`` is reached.

        Args:
            strategy:           Strategy name (must match a registered strategy).
            pnl_usd:            Net P&L in USD (positive = profit).
            is_win:             True if the trade was profitable.
            position_size_usd:  Trade size in USD (used to normalise returns).
        """
        with self._lock:
            if strategy not in self._perf:
                self._perf[strategy] = StrategyPerformanceRecord(name=strategy)
            rec = self._perf[strategy]
            rec.total_trades += 1
            rec.total_pnl_usd += pnl_usd
            if is_win:
                rec.winning_trades += 1
            if pnl_usd > 0:
                rec.gross_profit += pnl_usd
            elif pnl_usd < 0:
                rec.gross_loss += abs(pnl_usd)

            trade_return = (
                (pnl_usd / position_size_usd) if position_size_usd > 0 else 0.0
            )
            # Clamp to [-1, 1]: a single trade should not move a non-leveraged
            # position by more than ±100 %.  This keeps the EMA and Sharpe
            # estimates stable in the face of outlier P&L values (e.g. a large
            # winning trade that temporarily exceeds the stated position size).
            trade_return = max(-1.0, min(1.0, trade_return))

            rec.ema_return = (
                _EMA_DECAY * rec.ema_return + (1.0 - _EMA_DECAY) * trade_return
            )
            rec._recent_returns.append(trade_return)
            if len(rec._recent_returns) > _SHARPE_WINDOW:
                rec._recent_returns = rec._recent_returns[-_SHARPE_WINDOW:]

        logger.info(
            "[%s] trade recorded | pnl=$%+.2f | is_win=%s | ema=%.4f",
            strategy, pnl_usd, is_win, rec.ema_return,
        )

    def pause_strategy(self, strategy_name: str) -> None:
        """
        Pause a strategy so it is excluded from signal generation and
        capital allocation until ``resume_strategy()`` is called.

        Args:
            strategy_name: Name of the strategy to pause.
        """
        with self._lock:
            if strategy_name in self._perf:
                self._perf[strategy_name].paused = True
                logger.info("Strategy paused: %s", strategy_name)
            else:
                logger.warning("pause_strategy: unknown strategy '%s'", strategy_name)

    def resume_strategy(self, strategy_name: str) -> None:
        """
        Resume a previously paused strategy.

        Args:
            strategy_name: Name of the strategy to resume.
        """
        with self._lock:
            if strategy_name in self._perf:
                self._perf[strategy_name].paused = False
                logger.info("Strategy resumed: %s", strategy_name)
            else:
                logger.warning("resume_strategy: unknown strategy '%s'", strategy_name)

    def is_strategy_paused(self, strategy_name: str) -> bool:
        """Return True if the strategy is currently paused."""
        with self._lock:
            rec = self._perf.get(strategy_name)
            return rec.paused if rec is not None else False

    def get_performance_summary(self) -> Dict[str, Dict]:
        """
        Return a per-strategy performance summary for dashboards and logging.

        Returns:
            Dictionary mapping strategy name to a stats dict containing:
            total_trades, winning_trades, win_rate, total_pnl_usd,
            profit_factor, sharpe_estimate, ema_return, composite_score,
            paused.
        """
        with self._lock:
            summary = {}
            for name, rec in self._perf.items():
                summary[name] = {
                    "total_trades": rec.total_trades,
                    "winning_trades": rec.winning_trades,
                    "win_rate": round(rec.win_rate, 4),
                    "total_pnl_usd": round(rec.total_pnl_usd, 4),
                    "profit_factor": round(rec.profit_factor, 4),
                    "sharpe_estimate": round(rec.sharpe_estimate, 4),
                    "ema_return": round(rec.ema_return, 6),
                    "composite_score": round(rec.composite_score(), 6),
                    "paused": rec.paused,
                }
            return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_pool(self) -> Dict[str, BaseStrategy]:
        """Instantiate all four strategies."""
        return {
            "ApexTrendStrategy": ApexTrendStrategy(
                self._config.get("ApexTrendStrategy")
            ),
            "MeanReversionStrategy": MeanReversionStrategy(
                self._config.get("MeanReversionStrategy")
            ),
            "MomentumBreakoutStrategy": MomentumBreakoutStrategy(
                self._config.get("MomentumBreakoutStrategy")
            ),
            "LiquidityReversalStrategy": LiquidityReversalStrategy(
                self._config.get("LiquidityReversalStrategy")
            ),
        }

    def _compute_allocations(self, regime: str) -> List[StrategyAllocation]:
        """
        Compute per-strategy capital allocations for the current regime.

        Allocation weights are determined in two phases:

        **Phase 1 – Regime weights (always applied)**
          Each active strategy starts with an equal base weight.  The strategy
          whose ``home_regime`` matches the detected regime receives an extra
          ``regime_boost`` (default +50 % relative weight).

        **Phase 2 – Performance blend (once ≥ MIN_TRADES_BEFORE_LEARNING)**
          When a strategy has accumulated enough trades, its composite
          performance score is blended (``_PERF_BLEND``) with its regime
          weight so that outperforming strategies receive more capital.

        Paused strategies are excluded from allocations entirely.
        """
        deployable = self.total_capital * (1 - self.reserve_pct)

        # Active (non-paused) strategy names
        names = [
            n for n in self._strategies
            if not self._perf.get(n, StrategyPerformanceRecord(name=n)).paused
        ]

        if not names:
            return []

        # ── Phase 1: regime weights ────────────────────────────────────
        regime_weights: Dict[str, float] = {n: 1.0 for n in names}
        for name in names:
            home = _STRATEGY_HOME_REGIME.get(name, "ALL")
            if home == regime or home == "ALL":
                regime_weights[name] += self.regime_boost

        total_regime_w = sum(regime_weights.values())
        regime_fracs: Dict[str, float] = {
            n: regime_weights[n] / total_regime_w for n in names
        }

        # ── Phase 2: performance blend ─────────────────────────────────
        scores: Dict[str, float] = {
            n: self._perf[n].composite_score()
            if n in self._perf and self._perf[n].total_trades >= _MIN_TRADES_BEFORE_LEARNING
            else None
            for n in names
        }

        have_perf = [n for n in names if scores[n] is not None]
        if have_perf:
            # Shift raw scores to be non-negative
            raw_scores = {n: scores[n] for n in have_perf}
            min_score = min(raw_scores.values())
            shifted = {n: raw_scores[n] - min_score for n in have_perf}
            total_shifted = sum(shifted.values())
            if total_shifted > 0:
                perf_fracs: Dict[str, float] = {
                    n: shifted[n] / total_shifted for n in have_perf
                }
            else:
                perf_fracs = {n: 1.0 / len(have_perf) for n in have_perf}

            # Strategies without enough data keep their regime fraction
            final_fracs: Dict[str, float] = {}
            for n in names:
                if n in perf_fracs:
                    final_fracs[n] = (
                        (1.0 - _PERF_BLEND) * regime_fracs[n]
                        + _PERF_BLEND * perf_fracs[n]
                    )
                else:
                    final_fracs[n] = regime_fracs[n]

            # Re-normalise so weights sum to 1
            total_final = sum(final_fracs.values())
            final_fracs = {n: final_fracs[n] / total_final for n in names}
        else:
            final_fracs = regime_fracs

        # ── Build StrategyAllocation list ──────────────────────────────
        allocations: List[StrategyAllocation] = []
        for name in names:
            w = final_fracs[name]
            home = _STRATEGY_HOME_REGIME.get(name, "ALL")
            allocations.append(
                StrategyAllocation(
                    strategy_name=name,
                    home_regime=home,
                    allocated_capital=deployable * w,
                    weight=w,
                    is_primary=(home == regime),
                )
            )

        return allocations

    def _build_consensus(
        self,
        raw_signals: List[Dict],
        allocations: List[StrategyAllocation],
        regime: str,
    ) -> DiversifiedSignal:
        """
        Determine the consensus signal from all strategy outputs.

        Confidence is weighted by each strategy's capital allocation weight so
        that the on-regime (primary) strategy has more influence.
        """
        buy_signals = [s for s in raw_signals if s.get("signal") == "BUY"]
        sell_signals = [s for s in raw_signals if s.get("signal") == "SELL"]

        for direction, group in [("BUY", buy_signals), ("SELL", sell_signals)]:
            if not group:
                continue

            # Weighted confidence
            total_w = sum(s.get("weight", 0.0) for s in group)
            if total_w == 0:
                avg_conf = sum(s.get("confidence", 0.0) for s in group) / len(group)
            else:
                avg_conf = sum(
                    s.get("confidence", 0.0) * s.get("weight", 0.0) for s in group
                ) / total_w

            if avg_conf < self.min_confidence:
                continue

            # Pick the best single strategy (highest confidence in this direction)
            best = max(group, key=lambda s: s.get("confidence", 0.0))
            best_name = best.get("strategy", "")

            # Use the capital allocation for the best strategy
            best_alloc = next(
                (a for a in allocations if a.strategy_name == best_name),
                None,
            )
            capital = best_alloc.allocated_capital if best_alloc else 0.0

            contributors = [s["strategy"] for s in group]
            reasons = "; ".join(
                f"{s['strategy']}: {s.get('reason', '')}" for s in group
            )

            logger.info(
                "DiversificationEngine → %s | regime=%s | confidence=%.2f | "
                "strategies=%s | capital=$%.2f",
                direction,
                regime,
                avg_conf,
                contributors,
                capital,
            )

            return DiversifiedSignal(
                signal=direction,
                confidence=avg_conf,
                strategy=best_name,
                regime=regime,
                capital_allocation=capital,
                contributing_strategies=contributors,
                individual_signals=raw_signals,
                reason=f"{direction} consensus from {len(group)} strategy(ies) | {reasons}",
                allocations=allocations,
            )

        # No qualifying consensus
        return DiversifiedSignal(
            signal="NONE",
            confidence=0.0,
            strategy="",
            regime=regime,
            capital_allocation=0.0,
            contributing_strategies=[],
            individual_signals=raw_signals,
            reason="No qualifying consensus signal",
            allocations=allocations,
        )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_engine_instance: Optional[StrategyDiversificationEngine] = None
_engine_lock = threading.Lock()


def get_strategy_diversification_engine(
    total_capital: float = 10_000.0,
    reserve_pct: float = 0.20,
    regime_boost: float = 0.50,
    min_confidence: float = 0.50,
    config: Optional[Dict] = None,
) -> StrategyDiversificationEngine:
    """
    Return (or create) the global :class:`StrategyDiversificationEngine`
    singleton.

    On the first call the engine is constructed with the supplied parameters.
    Subsequent calls ignore those parameters and return the already-created
    instance — so callers that only need a reference can simply call
    ``get_strategy_diversification_engine()`` with no arguments.

    Args:
        total_capital:  Total deployable capital in USD.
        reserve_pct:    Fraction of capital to keep in reserve (default 0.20).
        regime_boost:   Extra relative weight for the on-regime strategy
                        (default 0.50 = +50 %).
        min_confidence: Minimum signal confidence to emit a BUY/SELL
                        (default 0.50).
        config:         Per-strategy configuration overrides.

    Returns:
        The global :class:`StrategyDiversificationEngine` instance.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = StrategyDiversificationEngine(
                    total_capital=total_capital,
                    reserve_pct=reserve_pct,
                    regime_boost=regime_boost,
                    min_confidence=min_confidence,
                    config=config,
                )
    return _engine_instance
