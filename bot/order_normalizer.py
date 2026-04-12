"""
NIJA Automatic Order Normalizer
=================================

Converts an internal :class:`NormalizedOrder` (base currency ``BTC-USD``
format, USD-denominated size) into the exchange-native representation
required by each broker's ``place_market_order`` call.

Each exchange has different conventions:

===================  ================  ==========  =======================
Exchange             Symbol format     Size field  Notes
===================  ================  ==========  =======================
Coinbase             BTC-USD           quote USD   no conversion needed
Kraken               XXBTZUSD          quote USD   symbol map required
Alpaca               BTC/USD           qty shares  USD → base-qty via price
Binance              BTCUSDT           quoteQty    replace -USD with USDT
OKX                  BTC-USDT          sz (base)   replace -USD with -USDT
===================  ================  ==========  =======================

Usage
-----
    from bot.order_normalizer import get_order_normalizer, NormalizedOrder

    normalizer = get_order_normalizer()
    order = NormalizedOrder(
        symbol="BTC-USD", side="buy", usd_size=10.0,
        current_price=65_000.0,
    )
    native = normalizer.normalize("coinbase", order)
    # native.symbol == "BTC-USD", native.size == 10.0, native.size_type == "quote"
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("nija.order_normalizer")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class NormalizedOrder:
    """Internal (exchange-agnostic) order representation."""
    symbol: str                         # BASE-USD format, e.g. "BTC-USD"
    side: str                           # "buy" | "sell"
    usd_size: float                     # USD notional value
    current_price: float = 0.0          # used to derive base qty when needed
    base_qty: float = 0.0               # base currency qty (overrides usd_size if > 0)
    size_type: str = "quote"            # "quote" (USD) | "base" (crypto amount)
    extra: Dict = field(default_factory=dict)


@dataclass
class ExchangeOrder:
    """Exchange-native order ready to pass to place_market_order."""
    symbol: str                         # exchange-native symbol
    side: str                           # "buy" | "sell" (lower-case)
    size: float                         # amount in the exchange's expected denomination
    size_type: str                      # "quote" | "base"
    broker_name: str = ""
    raw: NormalizedOrder = field(default_factory=lambda: NormalizedOrder("", "", 0.0))


# ---------------------------------------------------------------------------
# Per-exchange normalisation strategies
# ---------------------------------------------------------------------------

class _BaseNormalizer:
    """Shared helpers."""

    def _base_qty(self, order: NormalizedOrder) -> float:
        """Derive base currency qty from usd_size and current_price."""
        if order.base_qty > 0:
            return order.base_qty
        if order.current_price > 0:
            return order.usd_size / order.current_price
        return order.usd_size  # fallback

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        raise NotImplementedError


class CoinbaseNormalizer(_BaseNormalizer):
    """Coinbase: symbol unchanged, size in USD (quote)."""

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        return ExchangeOrder(
            symbol=order.symbol.upper(),
            side=order.side.lower(),
            size=order.usd_size,
            size_type="quote",
            broker_name=broker_name,
            raw=order,
        )


class KrakenNormalizer(_BaseNormalizer):
    """Kraken: map symbol to Kraken format; size in USD (quote)."""

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        try:
            from bot.exchange_plugin import get_plugin_registry
        except ImportError:
            from exchange_plugin import get_plugin_registry  # type: ignore
        plugin = get_plugin_registry().get("kraken")
        native_sym = plugin.format_symbol(order.symbol) if plugin else order.symbol
        return ExchangeOrder(
            symbol=native_sym,
            side=order.side.lower(),
            size=order.usd_size,
            size_type="quote",
            broker_name=broker_name,
            raw=order,
        )


class AlpacaNormalizer(_BaseNormalizer):
    """Alpaca: BTC-USD → BTC/USD; size in base currency (shares/coins)."""

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        native_sym = order.symbol.replace("-", "/").upper()
        qty = self._base_qty(order)
        try:
            from bot.exchange_plugin import get_plugin_registry
            plugin = get_plugin_registry().get("alpaca")
            if plugin:
                qty = plugin.round_base_qty(qty, order.symbol)
        except Exception:
            pass
        return ExchangeOrder(
            symbol=native_sym,
            side=order.side.lower(),
            size=qty,
            size_type="base",
            broker_name=broker_name,
            raw=order,
        )


class BinanceNormalizer(_BaseNormalizer):
    """Binance: BTC-USD → BTCUSDT; buys use quoteOrderQty (USD), sells use qty (base)."""

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        native_sym = order.symbol.replace("-USD", "USDT").replace("-", "").upper()
        if order.side.lower() == "buy":
            size = order.usd_size
            size_type = "quote"
        else:
            size = self._base_qty(order)
            size_type = "base"
        return ExchangeOrder(
            symbol=native_sym,
            side=order.side.lower(),
            size=size,
            size_type=size_type,
            broker_name=broker_name,
            raw=order,
        )


class OKXNormalizer(_BaseNormalizer):
    """OKX: BTC-USD → BTC-USDT; size in base currency."""

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        native_sym = order.symbol.replace("-USD", "-USDT").upper()
        size = self._base_qty(order)
        try:
            from bot.exchange_plugin import get_plugin_registry
            plugin = get_plugin_registry().get("okx")
            if plugin:
                size = plugin.round_base_qty(size, order.symbol)
        except Exception:
            pass
        return ExchangeOrder(
            symbol=native_sym,
            side=order.side.lower(),
            size=size,
            size_type="base",
            broker_name=broker_name,
            raw=order,
        )


class PassthroughNormalizer(_BaseNormalizer):
    """Passthrough: symbol and size unchanged."""

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        return ExchangeOrder(
            symbol=order.symbol,
            side=order.side.lower(),
            size=order.usd_size,
            size_type=order.size_type,
            broker_name=broker_name,
            raw=order,
        )


# ---------------------------------------------------------------------------
# OrderNormalizer dispatcher
# ---------------------------------------------------------------------------

_NORMALIZERS: Dict[str, _BaseNormalizer] = {
    "coinbase": CoinbaseNormalizer(),
    "kraken": KrakenNormalizer(),
    "alpaca": AlpacaNormalizer(),
    "binance": BinanceNormalizer(),
    "okx": OKXNormalizer(),
}


class OrderNormalizer:
    """Dispatches normalisation to the correct per-exchange strategy.

    Returns an :class:`ExchangeOrder` ready for the broker adapter.
    """

    def normalize(
        self,
        broker_name: str,
        order: NormalizedOrder,
    ) -> ExchangeOrder:
        normalizer = _NORMALIZERS.get(broker_name.lower(), PassthroughNormalizer())
        result = normalizer.normalize(order, broker_name)
        logger.debug(
            "OrderNormalizer[%s]: %s %s $%.2f → symbol=%s size=%s (%s)",
            broker_name, order.side.upper(), order.symbol, order.usd_size,
            result.symbol, result.size, result.size_type,
        )
        return result

    @staticmethod
    def from_broker_call(
        broker_name: str,
        symbol: str,
        side: str,
        quantity: float,
        size_type: str = "quote",
        current_price: float = 0.0,
    ) -> ExchangeOrder:
        """Convenience: build a :class:`NormalizedOrder` from raw broker-call args
        and normalise it in one step.
        """
        raw = NormalizedOrder(
            symbol=symbol,
            side=side,
            usd_size=quantity if size_type == "quote" else 0.0,
            base_qty=quantity if size_type == "base" else 0.0,
            size_type=size_type,
            current_price=current_price,
        )
        return OrderNormalizer().normalize(broker_name, raw)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[OrderNormalizer] = None
_lock = threading.Lock()


def get_order_normalizer() -> OrderNormalizer:
    """Return (or create) the process-wide :class:`OrderNormalizer`."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = OrderNormalizer()
    return _instance
