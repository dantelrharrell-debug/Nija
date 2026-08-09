"""Live exchange-constraint authority v72.

NIJA's historical ExchangeOrderCompiler contains static schemas for Kraken,
Coinbase and OKX plus a generic fallback.  Generic precision/minimum assumptions
are not safe for Binance, Alpaca or future exchanges because symbol rules are
instrument-specific and may change.

v72 adds a provider registry for live symbol constraints and makes unknown/live
venues fail closed unless a provider returns verified metadata.  Existing
Kraken/Coinbase/OKX static schemas remain compatibility fallbacks because those
venues also pass through dedicated runtime order guards elsewhere in NIJA.

Supported normalized provider shapes include:
* canonical: min_order_usd/min_notional_usd/fee_rate_one_way/step_size/precision;
* Binance exchangeInfo filters: LOT_SIZE/MARKET_LOT_SIZE, MIN_NOTIONAL/NOTIONAL;
* Alpaca asset fields: min_order_size, min_trade_increment, price_increment;
* OKX-style: minSz, lotSz, tickSz;
* Coinbase-style: base_min_size, base_increment, quote_min_size.

A provider may be registered directly or derived from a broker client exposing a
symbol/market metadata method.  No provider result is accepted unless positive
quantity precision/minimum information can be proven.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import sys
import threading
from decimal import Decimal
from functools import wraps
from types import ModuleType
from typing import Any, Callable, Mapping, Optional

LOGGER = logging.getLogger("nija.live_exchange_constraints_authority_v72")
MARKER = "20260809-live-exchange-constraints-authority-v72"
_PATCH_ATTR = "_nija_live_exchange_constraints_authority_v72"
_LOCK = threading.RLock()
_PROVIDERS: dict[str, Callable[[str], Any]] = {}
_COMPAT_STATIC = {"kraken", "coinbase", "okx"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _live_mode() -> bool:
    truthy = {"1", "true", "yes", "on", "enabled", "y"}
    return (
        str(os.environ.get("LIVE_CAPITAL_VERIFIED", "false")).strip().lower() in truthy
        and str(os.environ.get("DRY_RUN_MODE", "false")).strip().lower() not in truthy
        and str(os.environ.get("PAPER_MODE", "false")).strip().lower() not in truthy
    )


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _precision_from_step(step: float) -> int:
    if step <= 0.0:
        return 0
    text = format(Decimal(str(step)).normalize(), "f")
    if "." not in text:
        return 0
    return min(18, len(text.rstrip("0").split(".", 1)[1]))


def register_live_constraint_provider(
    exchange: str,
    provider: Callable[[str], Any],
    *,
    replace: bool = False,
) -> None:
    name = _norm(exchange)
    if not name:
        raise ValueError("exchange is required")
    if not callable(provider):
        raise TypeError("provider must be callable")
    with _LOCK:
        if name in _PROVIDERS and not replace:
            raise RuntimeError(f"constraint provider already registered: {name}")
        _PROVIDERS[name] = provider
    LOGGER.info(
        "LIVE_CONSTRAINT_PROVIDER_V72_REGISTERED marker=%s exchange=%s replace=%s",
        MARKER,
        name,
        replace,
    )


def unregister_live_constraint_provider(exchange: str) -> None:
    with _LOCK:
        _PROVIDERS.pop(_norm(exchange), None)


def registered_constraint_providers() -> tuple[str, ...]:
    with _LOCK:
        return tuple(sorted(_PROVIDERS))


def _client_metadata_provider(client: Any) -> Callable[[str], Any]:
    methods = (
        "get_symbol_rules",
        "get_order_rules",
        "get_market_rules",
        "get_instrument_info",
        "get_symbol_info",
        "get_market_info",
        "get_product",
        "get_asset",
    )

    def provider(symbol: str) -> Any:
        errors: list[str] = []
        for name in methods:
            method = getattr(client, name, None)
            if not callable(method):
                continue
            for args, kwargs in (((symbol,), {}), ((), {"symbol": symbol})):
                try:
                    value = method(*args, **kwargs)
                except TypeError:
                    continue
                except Exception as exc:
                    errors.append(f"{name}:{type(exc).__name__}")
                    break
                if value is not None:
                    return value
        raise RuntimeError(
            "broker client exposes no usable symbol-constraint metadata method"
            + (f" ({','.join(errors[-3:])})" if errors else "")
        )

    return provider


def register_client_constraint_provider(
    exchange: str,
    client: Any,
    *,
    replace: bool = False,
) -> None:
    register_live_constraint_provider(
        exchange,
        _client_metadata_provider(client),
        replace=replace,
    )


def _filters_map(raw: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    filters = raw.get("filters")
    if not isinstance(filters, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for item in filters:
        if isinstance(item, Mapping):
            key = str(item.get("filterType") or "").strip().upper()
            if key:
                result[key] = item
    return result


def _extract_rules(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("constraint provider returned non-mapping metadata")

    # Many APIs wrap the symbol object under data/result/product/asset.
    value: Mapping[str, Any] = raw
    for key in ("result", "product", "asset", "symbol_info", "instrument"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            value = nested
            break
    data = value.get("data")
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        value = data[0]

    filters = _filters_map(value)
    lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
    notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}

    # Canonical / Binance / OKX / Coinbase / Alpaca aliases.
    step = max(
        _f(value.get("step_size")),
        _f(value.get("base_increment")),
        _f(value.get("lotSz")),
        _f(value.get("min_trade_increment")),
        _f(lot.get("stepSize")),
    )
    min_base = max(
        _f(value.get("min_base_qty")),
        _f(value.get("base_min_size")),
        _f(value.get("minSz")),
        _f(value.get("min_order_size")),
        _f(lot.get("minQty")),
    )
    min_notional = max(
        _f(value.get("min_notional_usd")),
        _f(value.get("min_order_usd")),
        _f(value.get("quote_min_size")),
        _f(value.get("minNotional")),
        _f(notional.get("minNotional")),
        _f(notional.get("notional")),
    )
    fee = max(
        0.0,
        _f(value.get("fee_rate_one_way")),
        _f(value.get("taker_fee")),
        _f(value.get("fee_taker")),
    )
    precision = int(
        _f(value.get("precision_decimals"), -1)
        if value.get("precision_decimals") is not None
        else _f(value.get("lot_precision"), -1)
    )
    if precision < 0 and step > 0.0:
        precision = _precision_from_step(step)

    # Alpaca crypto may give min_order_size/min_trade_increment in base units,
    # not USD.  Keep min_base separately and do not mislabel it as notional.
    if "min_order_size" in value and not any(
        key in value for key in ("min_order_usd", "min_notional_usd", "quote_min_size")
    ):
        min_base = max(min_base, _f(value.get("min_order_size")))
        min_notional = max(
            _f(value.get("min_notional_usd")),
            _f(value.get("quote_min_size")),
        )

    if step <= 0.0:
        # A positive minimum base increment is usable as a conservative step
        # only when the provider explicitly gives no separate increment.
        step = _f(value.get("min_trade_increment"))
    if step <= 0.0 or precision < 0:
        raise ValueError("symbol quantity increment/precision not proven")
    if min_base <= 0.0 and min_notional <= 0.0:
        raise ValueError("symbol minimum quantity/notional not proven")

    return {
        "step_size": step,
        "precision_decimals": precision,
        "min_base_qty": min_base,
        "min_notional_usd": min_notional,
        "min_order_usd": min_notional,
        "fee_rate_one_way": fee,
    }


def _constraints_from_provider(module: ModuleType, exchange: str, symbol: str) -> Any:
    name = _norm(exchange)
    with _LOCK:
        provider = _PROVIDERS.get(name)
    if provider is None:
        return None
    raw = provider(symbol)
    rules = _extract_rules(raw)
    cls = getattr(module, "ExchangeConstraints")
    min_notional = float(rules["min_notional_usd"] or 0.0)
    min_order = float(rules["min_order_usd"] or 0.0)
    # When the venue exposes only a base minimum, the compiler's post-rounding
    # quantity gate still uses the step; a zero quote minimum is allowed here.
    return cls(
        exchange=name,
        min_order_usd=max(0.0, min_order),
        min_notional_usd=max(0.0, min_notional),
        fee_rate_one_way=max(0.0, float(rules["fee_rate_one_way"] or 0.0)),
        step_size=float(rules["step_size"]),
        precision_decimals=int(rules["precision_decimals"]),
    )


def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "ExchangeOrderCompiler", None)
    error_cls = getattr(module, "OrderCompileError", RuntimeError)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "get_constraints", None)
    if not callable(original):
        return False
    if getattr(original, _PATCH_ATTR, False):
        return True

    @wraps(original)
    def get_constraints_live_authority(self: Any, exchange: str, symbol: str):
        name = _norm(exchange)
        try:
            dynamic = _constraints_from_provider(module, name, symbol)
        except Exception as exc:
            if _live_mode():
                raise error_cls(
                    f"Live symbol constraints unavailable/invalid for {name}/{symbol}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            dynamic = None
        if dynamic is not None:
            LOGGER.info(
                "LIVE_EXCHANGE_CONSTRAINTS_V72_PROVEN marker=%s exchange=%s symbol=%s "
                "min_notional=%.8f step=%.12f precision=%d source=registered_provider",
                MARKER,
                name,
                symbol,
                float(dynamic.min_notional_usd),
                float(dynamic.step_size),
                int(dynamic.precision_decimals),
            )
            return dynamic

        if _live_mode() and name not in _COMPAT_STATIC:
            raise error_cls(
                f"Live exchange {name or 'unknown'} requires a registered symbol-constraint provider; "
                "generic min/precision fallback is prohibited"
            )
        constraints = original(self, exchange, symbol)
        if _live_mode() and name in _COMPAT_STATIC:
            LOGGER.debug(
                "LIVE_EXCHANGE_CONSTRAINTS_V72_COMPAT_STATIC marker=%s exchange=%s symbol=%s "
                "dedicated_runtime_guards_required=true",
                MARKER,
                name,
                symbol,
            )
        return constraints

    setattr(get_constraints_live_authority, _PATCH_ATTR, True)
    setattr(get_constraints_live_authority, "__wrapped__", original)
    cls.get_constraints = get_constraints_live_authority
    LOGGER.critical(
        "LIVE_EXCHANGE_CONSTRAINTS_AUTHORITY_V72_PATCHED marker=%s module=%s "
        "unknown_live_generic_fallback=false provider_registry=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.exchange_order_compiler", "exchange_order_compiler"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        flag = "_NIJA_LIVE_EXCHANGE_CONSTRAINTS_AUTHORITY_V72_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            if "exchange_order_compiler" in str(name):
                _patch_loaded()
            return result

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_LIVE_EXCHANGE_CONSTRAINTS_AUTHORITY_V72_INSTALLED"] = "1"
        LOGGER.critical(
            "LIVE_EXCHANGE_CONSTRAINTS_AUTHORITY_V72_INSTALLED marker=%s live_generic_fallback=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "register_live_constraint_provider",
    "unregister_live_constraint_provider",
    "registered_constraint_providers",
    "register_client_constraint_provider",
    "_extract_rules",
]
