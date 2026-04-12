"""
NIJA Per-Broker Risk + Sizing Adapters
========================================

Each adapter wraps the broker's risk evaluation and position-sizing logic.
Adapters are the single point where broker-specific rules are applied
**before** the order reaches the execution layer.

Adapters
--------
CoinbaseRiskSizingAdapter   micro-cap bypass + $1 floor sizing
KrakenRiskSizingAdapter     isolated mode — log risk, no sizing enforcement
DefaultRiskSizingAdapter    full risk evaluation + standard sizing

Factory
-------
    from bot.risk_sizing_adapter import RiskSizingAdapterFactory

    adapter = RiskSizingAdapterFactory.for_broker("coinbase")
    sized_order = adapter.size_order(raw_usd=10.0, balance=50.0, symbol="ADA-USD")
    risk_ok     = adapter.evaluate_risk(context)
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger("nija.risk_sizing_adapter")

# ---------------------------------------------------------------------------
# Shared constants (env-overridable)
# ---------------------------------------------------------------------------

_COINBASE_MIN_ORDER: float = float(
    os.getenv("COINBASE_MIN_ORDER_USD", os.getenv("COINBASE_MIN_ORDER", "1.0"))
)
_COINBASE_MAX_PCT: float = float(os.getenv("COINBASE_MAX_POSITION_PCT", "0.25"))
_KRAKEN_MIN_ORDER: float = float(os.getenv("KRAKEN_MIN_ORDER", "10.0"))
_DEFAULT_MIN_ORDER: float = float(os.getenv("DEFAULT_MIN_ORDER_USD", "5.0"))
_DEFAULT_MAX_PCT: float = 0.20


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SizingResult:
    """Outcome of a position-sizing calculation."""
    approved: bool
    sized_usd: float
    reason: str = ""
    clamped: bool = False           # True if size was clamped to min/max


# ---------------------------------------------------------------------------
# Adapter ABC
# ---------------------------------------------------------------------------

class RiskSizingAdapter(ABC):
    """Abstract per-broker risk + sizing adapter."""

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Lower-case broker name."""

    @abstractmethod
    def size_order(
        self,
        raw_usd: float,
        balance: float,
        symbol: str = "",
    ) -> SizingResult:
        """Apply broker-specific sizing rules to *raw_usd* and return the
        final approved size (or a rejected result)."""

    @abstractmethod
    def evaluate_risk(self, context) -> "RiskResult":
        """Run the broker's risk plugin and return a :class:`RiskResult`."""


# ---------------------------------------------------------------------------
# Coinbase adapter — micro-cap, $1 floor, bypass risk gate
# ---------------------------------------------------------------------------

class CoinbaseRiskSizingAdapter(RiskSizingAdapter):
    """Micro-cap execution: $1 minimum, capped at 25% of balance."""

    @property
    def broker_name(self) -> str:
        return "coinbase"

    def size_order(self, raw_usd: float, balance: float, symbol: str = "") -> SizingResult:
        # Enforce $1 micro-cap floor
        if raw_usd < _COINBASE_MIN_ORDER:
            logger.info(
                "CoinbaseAdapter: size $%.2f below micro-cap floor $%.2f — "
                "clamping up to floor",
                raw_usd, _COINBASE_MIN_ORDER,
            )
            raw_usd = _COINBASE_MIN_ORDER

        # Enforce max position cap
        if balance > 0:
            max_usd = balance * _COINBASE_MAX_PCT
            if raw_usd > max_usd:
                logger.debug(
                    "CoinbaseAdapter: size $%.2f > max $%.2f (%.0f%% of $%.2f) — clamping",
                    raw_usd, max_usd, _COINBASE_MAX_PCT * 100, balance,
                )
                return SizingResult(approved=True, sized_usd=max_usd, clamped=True)

        return SizingResult(approved=True, sized_usd=raw_usd)

    def evaluate_risk(self, context) -> "RiskResult":
        try:
            from bot.risk_plugin_base import BypassRiskPlugin
        except ImportError:
            from risk_plugin_base import BypassRiskPlugin  # type: ignore
        return BypassRiskPlugin().evaluate(context)


# ---------------------------------------------------------------------------
# Kraken adapter — isolated; risk logged only; sizing blocked for entries
# ---------------------------------------------------------------------------

class KrakenRiskSizingAdapter(RiskSizingAdapter):
    """Isolated broker: entries sized at zero (blocked), exits allowed."""

    @property
    def broker_name(self) -> str:
        return "kraken"

    def size_order(self, raw_usd: float, balance: float, symbol: str = "") -> SizingResult:
        # Entries never allocated capital in isolated mode
        logger.warning(
            "KrakenAdapter: isolated mode — sizing blocked (no new entries)"
        )
        return SizingResult(
            approved=False,
            sized_usd=0.0,
            reason="KRAKEN_ISOLATED: no new entries",
        )

    def evaluate_risk(self, context) -> "RiskResult":
        try:
            from bot.risk_plugin_base import IsolatedRiskPlugin
        except ImportError:
            from risk_plugin_base import IsolatedRiskPlugin  # type: ignore
        return IsolatedRiskPlugin().evaluate(context)


# ---------------------------------------------------------------------------
# Alpaca adapter — standard sizing (stock/crypto, $1 floor)
# ---------------------------------------------------------------------------

class AlpacaRiskSizingAdapter(RiskSizingAdapter):

    @property
    def broker_name(self) -> str:
        return "alpaca"

    def size_order(self, raw_usd: float, balance: float, symbol: str = "") -> SizingResult:
        if raw_usd < _COINBASE_MIN_ORDER:
            return SizingResult(
                approved=False, sized_usd=0.0,
                reason=f"ALPACA: size ${raw_usd:.2f} below $1 floor",
            )
        if balance > 0:
            max_usd = balance * _DEFAULT_MAX_PCT
            if raw_usd > max_usd:
                return SizingResult(approved=True, sized_usd=max_usd, clamped=True)
        return SizingResult(approved=True, sized_usd=raw_usd)

    def evaluate_risk(self, context) -> "RiskResult":
        try:
            from bot.risk_plugin_base import ActiveRiskPlugin
        except ImportError:
            from risk_plugin_base import ActiveRiskPlugin  # type: ignore
        return ActiveRiskPlugin().evaluate(context)


# ---------------------------------------------------------------------------
# Default adapter — used for Binance, OKX, and unknown brokers
# ---------------------------------------------------------------------------

class DefaultRiskSizingAdapter(RiskSizingAdapter):
    """Standard full-risk sizing for Binance / OKX / unknown brokers."""

    def __init__(self, name: str = "unknown") -> None:
        self._name = name

    @property
    def broker_name(self) -> str:
        return self._name

    def size_order(self, raw_usd: float, balance: float, symbol: str = "") -> SizingResult:
        if raw_usd < _DEFAULT_MIN_ORDER:
            return SizingResult(
                approved=False, sized_usd=0.0,
                reason=f"{self._name}: size ${raw_usd:.2f} below ${_DEFAULT_MIN_ORDER:.2f} floor",
            )
        if balance > 0:
            max_usd = balance * _DEFAULT_MAX_PCT
            if raw_usd > max_usd:
                return SizingResult(approved=True, sized_usd=max_usd, clamped=True)
        return SizingResult(approved=True, sized_usd=raw_usd)

    def evaluate_risk(self, context) -> "RiskResult":
        try:
            from bot.risk_plugin_base import ActiveRiskPlugin
        except ImportError:
            from risk_plugin_base import ActiveRiskPlugin  # type: ignore
        return ActiveRiskPlugin().evaluate(context)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_ADAPTERS = {
    "coinbase": CoinbaseRiskSizingAdapter(),
    "kraken":   KrakenRiskSizingAdapter(),
    "alpaca":   AlpacaRiskSizingAdapter(),
}


class RiskSizingAdapterFactory:
    """Returns the correct :class:`RiskSizingAdapter` for a broker."""

    @classmethod
    def for_broker(cls, broker_name: str) -> RiskSizingAdapter:
        """Return the adapter for *broker_name*, defaulting to
        :class:`DefaultRiskSizingAdapter` for unknown brokers."""
        return _ADAPTERS.get(broker_name.lower(), DefaultRiskSizingAdapter(broker_name))
