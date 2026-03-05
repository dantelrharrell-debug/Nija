"""
NIJA Strategy Manager
======================

Central orchestrator that maps detected market regimes to the correct
pluggable trading strategy.

Architecture
------------

    Market Scan
        ↓
    Market Structure Filter
        ↓
    Strategy Selector  ←── StrategyManager.select_strategy(market_regime)
        ↓
    Strategy Pool
      ├── ApexTrendStrategy       (TRENDING)
      ├── MeanReversionStrategy   (RANGING)
      ├── MomentumBreakoutStrategy(VOLATILE)
      └── LiquidityReversalStrategy(any regime, secondary)
        ↓
    Risk Engine
        ↓
    Trade Execution

Usage
-----
    from bot.strategy_manager import StrategyManager

    manager = StrategyManager()

    # Select strategy for current regime
    strategy = manager.select_strategy("TRENDING")
    signal   = strategy.generate_signal(df, indicators)

    # Or let the manager handle the full signal generation
    result = manager.get_signal(market_regime="RANGING", df=df, indicators=indicators)

Author: NIJA Trading Systems
"""

import logging
from typing import Dict, Optional, Type

try:
    from strategies.base_strategy import BaseStrategy
    from strategies.apex_strategy import ApexTrendStrategy
    from strategies.momentum_breakout import MomentumBreakoutStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    from strategies.liquidity_reversal import LiquidityReversalStrategy
except ImportError:
    from bot.strategies.base_strategy import BaseStrategy
    from bot.strategies.apex_strategy import ApexTrendStrategy
    from bot.strategies.momentum_breakout import MomentumBreakoutStrategy
    from bot.strategies.mean_reversion import MeanReversionStrategy
    from bot.strategies.liquidity_reversal import LiquidityReversalStrategy

logger = logging.getLogger("nija.strategy_manager")

# Canonical regime name aliases so callers don't have to worry about case
_REGIME_ALIASES: Dict[str, str] = {
    # TRENDING
    "trending": "TRENDING",
    "trend": "TRENDING",
    "strong_trend": "TRENDING",
    "weak_trend": "TRENDING",
    # RANGING
    "ranging": "RANGING",
    "range": "RANGING",
    "consolidation": "RANGING",
    # VOLATILE / BREAKOUT
    "volatile": "VOLATILE",
    "volatility_expansion": "VOLATILE",
    "high_volatility": "VOLATILE",
    "breakout": "VOLATILE",
    "momentum": "VOLATILE",
}


class StrategyManager:
    """
    Selects and runs the optimal trading strategy based on current market regime.

    The manager maintains a **strategy pool** and routes each market scan cycle
    to the most appropriate strategy.  It also supports a secondary
    ``LiquidityReversalStrategy`` as a fall-back / overlay that can be
    consulted for any regime.

    Strategy Routing
    ----------------
    +------------+-------------------------------+
    | Regime     | Primary Strategy              |
    +============+===============================+
    | TRENDING   | ApexTrendStrategy             |
    +------------+-------------------------------+
    | RANGING    | MeanReversionStrategy         |
    +------------+-------------------------------+
    | VOLATILE   | MomentumBreakoutStrategy      |
    +------------+-------------------------------+
    | (other)    | ApexTrendStrategy (default)   |
    +------------+-------------------------------+
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialise the StrategyManager.

        Args:
            config: Optional dict of configuration overrides.  Top-level keys
                    are regime names (``"TRENDING"``, ``"RANGING"``,
                    ``"VOLATILE"``); values are dicts forwarded to the
                    corresponding strategy constructor.

                    Example::

                        config = {
                            "TRENDING": {"min_confirmations": 4},
                            "RANGING":  {"rsi_oversold": 30},
                        }
        """
        self.config = config or {}
        self._current_regime: Optional[str] = None

        # Build the strategy pool
        self._pool: Dict[str, BaseStrategy] = {
            "TRENDING": ApexTrendStrategy(self.config.get("TRENDING")),
            "RANGING":  MeanReversionStrategy(self.config.get("RANGING")),
            "VOLATILE": MomentumBreakoutStrategy(self.config.get("VOLATILE")),
        }

        # Secondary overlay strategy (available for any regime)
        self._liquidity_reversal = LiquidityReversalStrategy(
            self.config.get("LIQUIDITY_REVERSAL")
        )

        logger.info(
            "StrategyManager initialised with pool: %s",
            list(self._pool.keys()),
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def select_strategy(self, market_regime: str) -> BaseStrategy:
        """
        Return the primary strategy for the given market regime.

        Args:
            market_regime: Regime string.  Case-insensitive.  Accepted values
                           include ``"TRENDING"``, ``"RANGING"``, ``"VOLATILE"``
                           and common aliases (e.g. ``"trend"``, ``"ranging"``,
                           ``"breakout"``).

        Returns:
            The ``BaseStrategy`` instance assigned to that regime.

        Notes:
            Unknown regimes fall back to ``ApexTrendStrategy`` and a warning
            is logged.
        """
        normalised = _REGIME_ALIASES.get(market_regime.lower(), market_regime.upper())

        if normalised not in self._pool:
            logger.warning(
                "Unknown market regime '%s' – falling back to ApexTrendStrategy",
                market_regime,
            )
            normalised = "TRENDING"

        # Notify strategy of regime change when it differs from previous
        if normalised != self._current_regime:
            strategy = self._pool[normalised]
            strategy.on_regime_change(normalised)
            self._current_regime = normalised
            logger.info(
                "Market regime → %s | Strategy → %s", normalised, strategy.name
            )

        return self._pool[normalised]

    def get_signal(self, market_regime: str, df, indicators: Dict) -> Dict:
        """
        Convenience wrapper: select strategy and immediately generate a signal.

        Args:
            market_regime: Current market regime string.
            df:            OHLCV DataFrame.
            indicators:    Pre-computed indicator dictionary.

        Returns:
            Signal dictionary from the selected strategy (see
            ``BaseStrategy.generate_signal`` for the schema).  A
            ``"strategy"`` key with the strategy name is appended.
        """
        strategy = self.select_strategy(market_regime)
        signal = strategy.generate_signal(df, indicators)
        signal["strategy"] = strategy.name
        signal["regime"] = market_regime
        return signal

    def get_liquidity_reversal_signal(self, df, indicators: Dict) -> Dict:
        """
        Query the LiquidityReversalStrategy independently of the primary regime.

        Use as a secondary signal overlay when hunting for high-conviction
        stop-hunt entries regardless of regime.

        Args:
            df:         OHLCV DataFrame.
            indicators: Pre-computed indicator dictionary.

        Returns:
            Signal dictionary from LiquidityReversalStrategy.
        """
        signal = self._liquidity_reversal.generate_signal(df, indicators)
        signal["strategy"] = self._liquidity_reversal.name
        return signal

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def list_strategies(self) -> Dict[str, str]:
        """
        Return a mapping of regime → strategy name for logging/dashboards.

        Returns:
            Dict[str, str]
        """
        result = {regime: s.name for regime, s in self._pool.items()}
        result["LIQUIDITY_REVERSAL"] = self._liquidity_reversal.name
        return result

    def get_strategy_parameters(self, market_regime: str) -> Dict:
        """
        Return the tunable parameters of the strategy for a given regime.

        Args:
            market_regime: Regime string.

        Returns:
            Parameter dictionary from the strategy's ``get_parameters()``.
        """
        strategy = self.select_strategy(market_regime)
        return strategy.get_parameters()

    @property
    def current_regime(self) -> Optional[str]:
        """The last regime that was passed to ``select_strategy``."""
        return self._current_regime

    def register_strategy(self, regime: str, strategy: BaseStrategy) -> None:
        """
        Register a custom strategy for a given regime at runtime.

        Allows operators to hot-swap strategies without restarting the bot.

        Args:
            regime:   Regime key, e.g. ``"TRENDING"``.
            strategy: Concrete ``BaseStrategy`` instance.

        Raises:
            TypeError: If ``strategy`` is not a ``BaseStrategy`` subclass.
        """
        if not isinstance(strategy, BaseStrategy):
            raise TypeError(
                f"strategy must be a BaseStrategy instance, got {type(strategy)}"
            )
        normalised = regime.upper()
        self._pool[normalised] = strategy
        logger.info("Registered custom strategy '%s' for regime '%s'", strategy.name, normalised)
