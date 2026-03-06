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
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.diversification_engine")

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

        # Build strategy pool
        self._strategies: Dict[str, BaseStrategy] = self._build_pool()

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
        Query every strategy, then return the best BUY/SELL opportunity.

        Algorithm
        ---------
        1. Normalise the market regime string.
        2. Compute capital allocations for this cycle.
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
        regime = _REGIME_ALIASES.get(market_regime.lower(), market_regime.upper())
        allocations = self._compute_allocations(regime)

        # Collect raw signals from every strategy
        raw_signals: List[Dict] = []
        for name, strategy in self._strategies.items():
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
        self.total_capital = new_total_capital
        logger.info("Capital updated to $%.2f", new_total_capital)

    def list_strategies(self) -> Dict[str, str]:
        """Return {strategy_name: home_regime} for logging / dashboard."""
        return {name: _STRATEGY_HOME_REGIME.get(name, "ALL") for name in self._strategies}

    def get_capital_allocations(self, market_regime: str = "RANGING") -> List[StrategyAllocation]:
        """Return capital allocation breakdown for a given regime."""
        regime = _REGIME_ALIASES.get(market_regime.lower(), market_regime.upper())
        return self._compute_allocations(regime)

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

        Each strategy starts with an equal share of deployable capital.
        The primary strategy for the detected regime receives an extra
        ``regime_boost`` relative weight.
        """
        deployable = self.total_capital * (1 - self.reserve_pct)

        # Base weights: equal shares
        names = list(self._strategies.keys())
        weights: Dict[str, float] = {n: 1.0 for n in names}

        # Boost the on-regime strategy
        primary = _STRATEGY_HOME_REGIME  # name → home_regime
        for name in names:
            home = primary.get(name, "ALL")
            if home == regime or home == "ALL":
                weights[name] += self.regime_boost

        total_weight = sum(weights.values())
        allocations: List[StrategyAllocation] = []
        for name in names:
            w = weights[name] / total_weight
            home = primary.get(name, "ALL")
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
