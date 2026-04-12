"""
NIJA Exchange Plug-in Architecture
=====================================

Each exchange is a self-contained, zero-dependency plugin that knows:
- How to normalise symbols between internal (BTC-USD) and native formats
- Order constraints: minimum/maximum size, lot precision, quote currency
- Supported order types and trading hours
- Fee tier (taker/maker) for profitability gating

All plugins implement :class:`ExchangePlugin` and are retrieved through
the module-level :class:`ExchangePluginRegistry` singleton.

Usage
-----
    from bot.exchange_plugin import get_plugin_registry
    reg = get_plugin_registry()
    plugin = reg.get("coinbase")            # → CoinbasePlugin
    native  = plugin.format_symbol("BTC-USD")  # "BTC-USD" (no change)
    ok, reason = plugin.validate_order("BTC-USD", "buy", usd_size=3.0)
"""

from __future__ import annotations

import logging
import math
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.exchange_plugin")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class OrderConstraints:
    """Exchange-level order constraints for a trading pair."""
    min_order_usd: float = 1.0
    max_order_usd: float = 1_000_000.0
    lot_precision: int = 6          # decimal places for base currency quantity
    quote_precision: int = 2        # decimal places for quote (USD) amount
    min_base_qty: float = 0.0       # minimum base currency quantity (0 = no constraint)
    fee_taker: float = 0.006        # taker fee fraction (0.6 % default)
    fee_maker: float = 0.004        # maker fee fraction


@dataclass
class ExchangeMeta:
    """Static metadata for an exchange plugin."""
    name: str                               # lower-case key, matches BrokerType.value
    display_name: str
    quote_currency: str = "USD"             # primary quote currency
    internal_quote: str = "USD"             # what internal symbols use (always USD)
    supports_market_orders: bool = True
    supports_limit_orders: bool = True
    is_24_7: bool = True                    # False for stock exchanges
    default_constraints: OrderConstraints = field(default_factory=OrderConstraints)


# ---------------------------------------------------------------------------
# Plugin ABC
# ---------------------------------------------------------------------------

class ExchangePlugin(ABC):
    """Interface that every exchange plug-in must implement."""

    @property
    @abstractmethod
    def meta(self) -> ExchangeMeta:
        """Return static exchange metadata."""

    @abstractmethod
    def format_symbol(self, internal_symbol: str) -> str:
        """Convert internal ``BASE-USD`` format to exchange-native format."""

    @abstractmethod
    def parse_symbol(self, native_symbol: str) -> str:
        """Convert exchange-native format back to internal ``BASE-USD`` format."""

    @abstractmethod
    def get_constraints(self, symbol: str = "") -> OrderConstraints:
        """Return order constraints for *symbol* (or exchange defaults)."""

    def validate_order(
        self,
        symbol: str,
        side: str,
        usd_size: float,
        base_qty: float = 0.0,
    ) -> Tuple[bool, str]:
        """Return ``(valid, reason)``.  Checks min/max size and format."""
        c = self.get_constraints(symbol)
        if usd_size > 0 and usd_size < c.min_order_usd:
            return False, (
                f"{self.meta.name}: order ${usd_size:.2f} below min ${c.min_order_usd:.2f}"
            )
        if usd_size > c.max_order_usd:
            return False, (
                f"{self.meta.name}: order ${usd_size:.2f} exceeds max ${c.max_order_usd:.2f}"
            )
        if base_qty > 0 and c.min_base_qty > 0 and base_qty < c.min_base_qty:
            return False, (
                f"{self.meta.name}: base qty {base_qty} below min {c.min_base_qty}"
            )
        return True, "ok"

    def round_base_qty(self, qty: float, symbol: str = "") -> float:
        """Round *qty* to the exchange's lot precision."""
        p = self.get_constraints(symbol).lot_precision
        factor = 10 ** p
        return math.floor(qty * factor) / factor

    def round_quote_qty(self, qty: float, symbol: str = "") -> float:
        """Round *qty* to the exchange's quote precision."""
        p = self.get_constraints(symbol).quote_precision
        return round(qty, p)


# ---------------------------------------------------------------------------
# Concrete plug-ins
# ---------------------------------------------------------------------------

class CoinbasePlugin(ExchangePlugin):
    """Coinbase Advanced Trade — internal BTC-USD format is native."""

    _META = ExchangeMeta(
        name="coinbase",
        display_name="Coinbase Advanced Trade",
        quote_currency="USD",
        default_constraints=OrderConstraints(
            min_order_usd=1.0,
            fee_taker=0.006,
            fee_maker=0.004,
        ),
    )

    @property
    def meta(self) -> ExchangeMeta:
        return self._META

    def format_symbol(self, internal_symbol: str) -> str:
        return internal_symbol.upper()

    def parse_symbol(self, native_symbol: str) -> str:
        return native_symbol.upper()

    def get_constraints(self, symbol: str = "") -> OrderConstraints:
        return self._META.default_constraints


class KrakenPlugin(ExchangePlugin):
    """Kraken Pro — BTC-USD → XXBTZUSD (legacy) or XBT/USD (new REST)."""

    # Internal → Kraken legacy symbol map (most common pairs)
    _FMT: Dict[str, str] = {
        "BTC-USD": "XXBTZUSD",
        "ETH-USD": "XETHZUSD",
        "SOL-USD": "SOLUSD",
        "ADA-USD": "ADAUSD",
        "DOT-USD": "DOTUSD",
        "LINK-USD": "LINKUSD",
        "ATOM-USD": "ATOMUSD",
        "LTC-USD": "XLTCZUSD",
        "XLM-USD": "XXLMZUSD",
        "BCH-USD": "BCHUSD",
        "AVAX-USD": "AVAXUSD",
        "MATIC-USD": "MATICUSD",
        "UNI-USD": "UNIUSD",
        "ALGO-USD": "ALGOUSD",
        "DOGE-USD": "XDGEUSD",
    }
    _REV: Dict[str, str] = {v: k for k, v in _FMT.items()}

    _META = ExchangeMeta(
        name="kraken",
        display_name="Kraken Pro",
        quote_currency="USD",
        default_constraints=OrderConstraints(
            min_order_usd=10.50,  # $10 hard floor + fee buffer
            fee_taker=0.0026,
            fee_maker=0.0016,
        ),
    )

    @property
    def meta(self) -> ExchangeMeta:
        return self._META

    def format_symbol(self, internal_symbol: str) -> str:
        return self._FMT.get(internal_symbol.upper(), internal_symbol.upper())

    def parse_symbol(self, native_symbol: str) -> str:
        return self._REV.get(native_symbol.upper(), native_symbol.upper())

    def get_constraints(self, symbol: str = "") -> OrderConstraints:
        return self._META.default_constraints


class AlpacaPlugin(ExchangePlugin):
    """Alpaca Markets — BTC-USD → BTC/USD."""

    _META = ExchangeMeta(
        name="alpaca",
        display_name="Alpaca Markets",
        quote_currency="USD",
        default_constraints=OrderConstraints(
            min_order_usd=1.0,
            fee_taker=0.0,  # Alpaca crypto is fee-free
            fee_maker=0.0,
        ),
    )

    @property
    def meta(self) -> ExchangeMeta:
        return self._META

    def format_symbol(self, internal_symbol: str) -> str:
        # BTC-USD → BTC/USD
        return internal_symbol.replace("-", "/").upper()

    def parse_symbol(self, native_symbol: str) -> str:
        # BTC/USD → BTC-USD
        return native_symbol.replace("/", "-").upper()

    def get_constraints(self, symbol: str = "") -> OrderConstraints:
        return self._META.default_constraints


class BinancePlugin(ExchangePlugin):
    """Binance Spot — BTC-USD → BTCUSDT."""

    _META = ExchangeMeta(
        name="binance",
        display_name="Binance Spot",
        quote_currency="USDT",
        default_constraints=OrderConstraints(
            min_order_usd=5.0,
            fee_taker=0.001,
            fee_maker=0.001,
        ),
    )

    @property
    def meta(self) -> ExchangeMeta:
        return self._META

    def format_symbol(self, internal_symbol: str) -> str:
        # BTC-USD → BTCUSDT
        return internal_symbol.replace("-USD", "USDT").replace("-", "").upper()

    def parse_symbol(self, native_symbol: str) -> str:
        # BTCUSDT → BTC-USD
        if native_symbol.endswith("USDT"):
            return native_symbol[:-4] + "-USD"
        return native_symbol

    def get_constraints(self, symbol: str = "") -> OrderConstraints:
        return self._META.default_constraints


class OKXPlugin(ExchangePlugin):
    """OKX Spot — BTC-USD → BTC-USDT."""

    _META = ExchangeMeta(
        name="okx",
        display_name="OKX Spot",
        quote_currency="USDT",
        default_constraints=OrderConstraints(
            min_order_usd=5.0,
            fee_taker=0.001,
            fee_maker=0.0008,
        ),
    )

    @property
    def meta(self) -> ExchangeMeta:
        return self._META

    def format_symbol(self, internal_symbol: str) -> str:
        # BTC-USD → BTC-USDT
        return internal_symbol.replace("-USD", "-USDT").upper()

    def parse_symbol(self, native_symbol: str) -> str:
        # BTC-USDT → BTC-USD
        return native_symbol.replace("-USDT", "-USD").upper()

    def get_constraints(self, symbol: str = "") -> OrderConstraints:
        return self._META.default_constraints


class PassthroughPlugin(ExchangePlugin):
    """Passthrough plug-in for brokers without active implementation.

    Used for Interactive Brokers, TD Ameritrade, Tradier, etc.
    Symbols pass through unchanged; default constraints apply.
    """

    def __init__(self, name: str, display_name: str = "") -> None:
        self._meta = ExchangeMeta(
            name=name,
            display_name=display_name or name.title(),
            default_constraints=OrderConstraints(min_order_usd=1.0),
        )

    @property
    def meta(self) -> ExchangeMeta:
        return self._meta

    def format_symbol(self, internal_symbol: str) -> str:
        return internal_symbol

    def parse_symbol(self, native_symbol: str) -> str:
        return native_symbol

    def get_constraints(self, symbol: str = "") -> OrderConstraints:
        return self._meta.default_constraints


# ---------------------------------------------------------------------------
# Plugin registry
# ---------------------------------------------------------------------------

class ExchangePluginRegistry:
    """Thread-safe registry of all exchange plug-ins.

    Built-in plug-ins are registered at construction time.  Additional
    plug-ins can be added at runtime with :meth:`register`.
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, ExchangePlugin] = {}
        self._lock = threading.Lock()
        self._register_builtins()

    def _register_builtins(self) -> None:
        for plugin in [
            CoinbasePlugin(),
            KrakenPlugin(),
            AlpacaPlugin(),
            BinancePlugin(),
            OKXPlugin(),
            PassthroughPlugin("interactive_brokers", "Interactive Brokers"),
            PassthroughPlugin("td_ameritrade", "TD Ameritrade"),
            PassthroughPlugin("tradier", "Tradier"),
        ]:
            self._plugins[plugin.meta.name] = plugin

    def register(self, plugin: ExchangePlugin) -> None:
        """Register (or replace) a plug-in."""
        with self._lock:
            self._plugins[plugin.meta.name] = plugin
            logger.info("ExchangePluginRegistry: registered %s", plugin.meta.display_name)

    def get(self, broker_name: str) -> Optional[ExchangePlugin]:
        """Return the plug-in for *broker_name* (case-insensitive), or None."""
        return self._plugins.get(broker_name.lower())

    def get_or_passthrough(self, broker_name: str) -> ExchangePlugin:
        """Return the plug-in, falling back to :class:`PassthroughPlugin`."""
        return self._plugins.get(broker_name.lower()) or PassthroughPlugin(broker_name)

    def all_plugins(self) -> List[ExchangePlugin]:
        return list(self._plugins.values())

    def all_names(self) -> List[str]:
        return list(self._plugins.keys())


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: Optional[ExchangePluginRegistry] = None
_registry_lock = threading.Lock()


def get_plugin_registry() -> ExchangePluginRegistry:
    """Return (or create) the process-wide :class:`ExchangePluginRegistry`."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ExchangePluginRegistry()
    return _registry
