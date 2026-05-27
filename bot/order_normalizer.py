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
    asset_class: str = "crypto"
    instrument_type: str = "spot"
    quantity_mode: str = "usd"          # "usd" | "shares" | "contracts"
    shares: float = 0.0
    contracts: float = 0.0
    account_type: str = ""
    leverage: float = 1.0
    reduce_only: bool = False
    position_effect: str = ""
    borrow_intent: str = ""
    margin_mode: str = ""
    time_in_force: str = ""
    extended_hours: Optional[bool] = None
    extra: Dict = field(default_factory=dict)


@dataclass
class ExchangeOrder:
    """Exchange-native order ready to pass to place_market_order."""
    symbol: str                         # exchange-native symbol
    side: str                           # "buy" | "sell" (lower-case)
    size: float                         # amount in the exchange's expected denomination
    size_type: str                      # "quote" | "base"
    broker_name: str = ""
    params: Dict = field(default_factory=dict)
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

    def _compile_margin_params(self, order: NormalizedOrder) -> Dict:
        params: Dict[str, object] = {}
        if order.account_type:
            params["account_type"] = order.account_type
        if order.leverage and order.leverage > 1:
            params["leverage"] = float(order.leverage)
        if order.reduce_only:
            params["reduce_only"] = True
        if order.position_effect:
            params["position_effect"] = order.position_effect
        if order.borrow_intent:
            params["borrow_intent"] = order.borrow_intent
        if order.margin_mode:
            params["margin_mode"] = order.margin_mode
        if order.time_in_force:
            params["time_in_force"] = order.time_in_force
        if order.extended_hours is not None:
            params["extended_hours"] = bool(order.extended_hours)
        return params


class CoinbaseNormalizer(_BaseNormalizer):
    """Coinbase: symbol unchanged, size in USD (quote)."""

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        return ExchangeOrder(
            symbol=order.symbol.upper(),
            side=order.side.lower(),
            size=order.usd_size,
            size_type="quote",
            broker_name=broker_name,
            params=self._compile_margin_params(order),
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
            params=self._compile_margin_params(order),
            raw=order,
        )


class AlpacaNormalizer(_BaseNormalizer):
    """Alpaca: BTC-USD → BTC/USD; size in base currency (shares/coins)."""

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        native_sym = order.symbol.replace("-", "/").upper()
        qty = order.shares if order.quantity_mode == "shares" and order.shares > 0 else self._base_qty(order)
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
            params=self._compile_margin_params(order),
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
            params=self._compile_margin_params(order),
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
            params=self._compile_margin_params(order),
            raw=order,
        )


class EquityNormalizer(_BaseNormalizer):
    """Equity normalizer: symbol passthrough + share/notional aware sizing."""

    def normalize(self, order: NormalizedOrder, broker_name: str) -> ExchangeOrder:
        params = self._compile_margin_params(order)
        tif = order.time_in_force or "day"
        params.setdefault("time_in_force", tif.lower())
        if order.extended_hours is not None:
            params["extended_hours"] = bool(order.extended_hours)

        if order.quantity_mode == "shares" and order.shares > 0:
            return ExchangeOrder(
                symbol=order.symbol.upper(),
                side=order.side.lower(),
                size=float(order.shares),
                size_type="base",
                broker_name=broker_name,
                params=params,
                raw=order,
            )

        # Notional mode for fractional-friendly brokers.
        if broker_name.lower() in {"alpaca", "alpaca_equity", "interactive_brokers_equity"}:
            params["quantity_mode"] = "notional"
            return ExchangeOrder(
                symbol=order.symbol.upper(),
                side=order.side.lower(),
                size=float(order.usd_size),
                size_type="quote",
                broker_name=broker_name,
                params=params,
                raw=order,
            )

        qty = self._base_qty(order)
        params["quantity_mode"] = "shares"
        return ExchangeOrder(
            symbol=order.symbol.upper(),
            side=order.side.lower(),
            size=qty,
            size_type="base",
            broker_name=broker_name,
            params=params,
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
            params=self._compile_margin_params(order),
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
    "alpaca_equity": EquityNormalizer(),
    "interactive_brokers_equity": EquityNormalizer(),
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
        **kwargs,
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
            asset_class=str(kwargs.get("asset_class") or "crypto"),
            instrument_type=str(kwargs.get("instrument_type") or "spot"),
            quantity_mode=str(kwargs.get("quantity_mode") or ("usd" if size_type == "quote" else "base")),
            shares=float(kwargs.get("quantity") or kwargs.get("shares") or 0.0) if str(kwargs.get("quantity_mode")) == "shares" else float(kwargs.get("shares") or 0.0),
            contracts=float(kwargs.get("contracts") or 0.0),
            account_type=str(kwargs.get("account_type") or ""),
            leverage=float(kwargs.get("leverage") or 1.0),
            reduce_only=bool(kwargs.get("reduce_only", False)),
            position_effect=str(kwargs.get("position_effect") or ""),
            borrow_intent=str(kwargs.get("borrow_intent") or ""),
            margin_mode=str(kwargs.get("margin_mode") or ""),
            time_in_force=str(kwargs.get("time_in_force") or ""),
            extended_hours=kwargs.get("extended_hours"),
            extra={
                "quantity_mode": kwargs.get("quantity_mode"),
                "asset_class": kwargs.get("asset_class"),
            },
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
