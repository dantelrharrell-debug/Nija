"""
NIJA Strategies Package
========================

Pluggable strategy modules for NIJA.  Import individual strategies or use
``StrategyManager`` (``bot/strategy_manager.py``) to auto-select based on
detected market regime.

Available strategies
--------------------
- ``ApexTrendStrategy``       – trend-following; best for TRENDING markets
- ``MomentumBreakoutStrategy``– breakout trading; best for VOLATILE markets
- ``MeanReversionStrategy``   – range mean-reversion; best for RANGING markets
- ``LiquidityReversalStrategy``– stop-hunt fade; useful across regimes

Base class
----------
- ``BaseStrategy`` – abstract interface that all strategies implement
"""

from .base_strategy import BaseStrategy
from .apex_strategy import ApexTrendStrategy
from .momentum_breakout import MomentumBreakoutStrategy
from .mean_reversion import MeanReversionStrategy
from .liquidity_reversal import LiquidityReversalStrategy

__all__ = [
    "BaseStrategy",
    "ApexTrendStrategy",
    "MomentumBreakoutStrategy",
    "MeanReversionStrategy",
    "LiquidityReversalStrategy",
]
