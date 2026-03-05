"""
NIJA Base Strategy Interface
=============================

Abstract base class that all pluggable trading strategies must implement.
This enforces a consistent contract across every strategy so that the
StrategyManager can swap implementations at runtime without changing
the call-sites.

Each concrete strategy must implement:
    - generate_signal(df, indicators) -> dict
    - get_parameters()                -> dict
    - name (property)                 -> str
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
import logging

logger = logging.getLogger("nija.strategy")


class BaseStrategy(ABC):
    """
    Abstract base class for all NIJA trading strategies.

    Concrete strategies must implement:
        - ``name``             (property) – human-readable strategy name
        - ``generate_signal``  – produce a BUY / SELL / NONE signal dict
        - ``get_parameters``   – expose tunable parameters for logging/debug
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize strategy with optional configuration overrides.

        Args:
            config: Dictionary of configuration overrides.  If omitted, each
                    strategy falls back to its built-in defaults.
        """
        self.config = config or {}

    # ------------------------------------------------------------------
    # Abstract interface – every subclass must provide these
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name, e.g. 'ApexTrendStrategy'."""

    @abstractmethod
    def generate_signal(self, df, indicators: Dict) -> Dict:
        """
        Analyse price data and indicators; return a trading signal.

        Args:
            df:         pandas DataFrame with OHLCV columns
                        (open, high, low, close, volume).
            indicators: Pre-computed indicator dictionary.  Keys are indicator
                        names (e.g. 'rsi_9', 'adx', 'atr', 'ema_21') and
                        values are pandas Series or scalar floats.

        Returns:
            A dictionary with **at minimum** these keys::

                {
                    "signal":     "BUY" | "SELL" | "NONE",
                    "confidence": float,   # 0.0 – 1.0
                    "reason":     str,     # human-readable explanation
                }

            Strategies may include additional keys (e.g. ``stop_loss``,
            ``take_profit``, ``position_size_multiplier``) that the
            StrategyManager will forward to the execution layer.
        """

    @abstractmethod
    def get_parameters(self) -> Dict:
        """
        Return the strategy's current tunable parameters.

        Used for logging, auditing, and the operator dashboard.  Should
        include every threshold that influences ``generate_signal``.

        Returns:
            Dictionary of parameter names to current values.
        """

    # ------------------------------------------------------------------
    # Optional helpers with default no-op implementations
    # ------------------------------------------------------------------

    def on_regime_change(self, new_regime: str) -> None:
        """
        Called by StrategyManager when the market regime changes.

        Override to reset internal state, recalibrate thresholds, etc.

        Args:
            new_regime: New regime string, e.g. "TRENDING", "RANGING", "VOLATILE".
        """
        logger.debug(f"[{self.name}] Regime changed to {new_regime}")

    def __repr__(self) -> str:  # pragma: no cover
        return f"{self.__class__.__name__}(name={self.name!r})"
