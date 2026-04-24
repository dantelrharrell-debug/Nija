"""
NIJA Multi-Market Intelligence Network (MMIN)
==============================================

GOD-MODE trading intelligence system that enables:
- Cross-market learning (crypto ↔ forex ↔ equities)
- Transfer learning across asset classes
- Macro regime forecasting
- Global capital routing
- Correlation-aware portfolio intelligence

This transforms NIJA into a global autonomous trading intelligence.

Author: NIJA Trading Systems
Version: 1.0.0
"""

from .mmin_engine import MMINEngine
from .data_collector import MultiMarketDataCollector
from .correlation_analyzer import CrossMarketCorrelationAnalyzer
from .macro_regime_forecaster import MacroRegimeForecaster
from .transfer_learning import TransferLearningEngine
from .global_capital_router import GlobalCapitalRouter

__all__ = [
    'MMINEngine',
    'MultiMarketDataCollector',
    'CrossMarketCorrelationAnalyzer',
    'MacroRegimeForecaster',
    'TransferLearningEngine',
    'GlobalCapitalRouter',
]

__version__ = '1.0.0'
