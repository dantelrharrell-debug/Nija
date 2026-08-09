"""Preserve live exchange base-quantity constraints through final compilation.

v72 blocks generic live precision/minimum guesses and normalizes dynamic venue
metadata.  Some venues (notably Alpaca crypto) express their minimum order size
in base units.  ExchangeOrderCompiler's historical ExchangeConstraints dataclass
does not carry that field, so v73 caches the provider-proven base minimum at
constraint resolution time and enforces it against the final rounded quantity.

The module also auto-registers metadata providers for non-legacy broker clients
when they become canonical through MultiAccountBrokerManager or the future-user
SecureBrokerAdapter. Kraken/Coinbase/OKX keep their existing dedicated/static
compatibility path unless explicitly registered elsewhere.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

from bot import live_exchange_constraints_authority_v72_patch as v72

LOGGER = logging.getLogger("nija.live_exchange_base_minimum_v73")
MARKER = "20260809-live-exchange-base-minimum-v73"
_PATCH_ATTR = "_nija_live_exchange_base_minimum_v73"
_LOCK = threading.RLock()
_BASE_MINIMUMS: dict[tuple[str, str], float] = {}
_METADATA_METHODS = (
    "get_symbol_rules",
    "get_order_rules",
    "get_market_rules",
    "get_instrument_info",
    "get_symbol_info",
    "get_market_info",
    "get_product",
    "get_asset",
)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _exchange_name(broker: Any, fallback: Any = None) -> str:
    for candidate in (
        getattr(getattr(broker, "broker_type", None), "value", None),
        getattr(broker, "broker_type", None),
        getattr(broker, "broker_name", None),
        getattr(broker, "exchange_name", None),
        getattr(broker, "exchange", None),
        fallback,
    ):
        name = _norm(candidate)
        if name:
            return name
    class_name = type(broker).__name__.lower()
    for suffix in ("brokeradapter", "broker", "client", "adapter"):
        class_name = class_name.replace(suffix, "")
    return _norm(class_name)


def _provider_for(exchange: str):
    with v72._LOCK:
        return v72._PROVIDERS.get(_norm(exchange))


def _cache_key(exchange: str, symbol: str) -> tuple[str, str]:
    return (_norm(exchange), _symbol(symbol))


def _install_constraint_capture() -> None:
    current = getattr(v72, "_constraints_from_provider", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return

    @wraps(current)
    def constraints_with_base_minimum(module: ModuleType, exchange: str, symbol: str):
        name = _norm(exchange)
        provider = _provider_for(name)
        if provider is None:
            _BASE_MINIMUMS.pop(_cache_key(name, symbol), None)
            return None

        raw = provider(symbol)
        rules = v72._extract_rules(raw)
        min_base = max(0.0, float(rules.get("min_base_qty") or 0.0))
        with _LOCK:
            if min_base > 0.0:
                _BASE_MINIMUMS[_cache_key(name, symbol)] = min_base
            else:
                _BASE_MINIMUMS.pop(_cache_key(name, symbol), None)

        cls = getattr(module, "ExchangeConstraints")
        return cls(
            exchange=name,
            min_order_usd=max(0.0, float(rules.get("min_order_usd") or 0.0)),
            min_notional_usd=max(0.0, float(rules.get("min_notional_usd") or 0.0)),
            fee_rate_one_way=max(0.0, float(rules.get("fee_rate_one_way") or 0.0)),
            step_size=float(rules["step_size"]),
            precision_decimals=int(rules["precision_decimals"]),
        )

    setattr(constraints_with_base_minimum, _PATCH_ATTR, True)
    setattr(constraints_with_base_minimum, "__wrapped__", current)
    v72._constraints_from_provider = constraints_with_base_minimum


def _patch_eoc_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExchangeOrderCompiler", None)
    error_cls = getattr(module, "OrderCompileError", RuntimeError)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "simulate_order", None)
    if not callable(original):
        return False
    if getattr(original, _PATCH_ATTR, False):
        return True

    @wraps(original)
    def simulate_order_base_minimum(
        self: Any,
        symbol: str,
        side: str,
        size_usd: float,
        pricing: Any,
        constraints: Any,
        *args: Any,
        **kwargs: Any,
    ):
        result = original(self, symbol, side, size_usd, pricing, constraints, *args, **kwargs)
        try:
            quantity = float(result[0])
        except Exception as exc:
            raise error_cls("compiled quantity missing from order simulation") from exc

        exchange = _norm(getattr(constraints, "exchange", ""))
        with _LOCK:
            min_base = float(_BASE_MINIMUMS.get(_cache_key(exchange, symbol), 0.0) or 0.0)
        if min_base > 0.0 and quantity + 1e-15 < min_base:
            LOGGER.error(
                "LIVE_EXCHANGE_BASE_MINIMUM_V73_BLOCKED marker=%s exchange=%s symbol=%s "
                "quantity=%.16f min_base=%.16f post_rounding=true fail_closed=true",
                MARKER,
                exchange,
                _symbol(symbol),
                quantity,
                min_base,
            )
            raise error_cls(
                f"Post-rounding quantity {quantity:.16g} below provider-proven "
                f"minimum base quantity {min_base:.16g} for {exchange}/{symbol}"
            )
        if min_base > 0.0:
            LOGGER.info(
                "LIVE_EXCHANGE_BASE_MINIMUM_V73_PROVEN marker=%s exchange=%s symbol=%s "
                "quantity=%.16f min_base=%.16f",
                MARKER,
                exchange,
                _symbol(symbol),
                quantity,
                min_base,
            )
        return result

    setattr(simulate_order_base_minimum, _PATCH_ATTR, True)
    setattr(simulate_order_base_minimum, "__wrapped__", original)
    cls.simulate_order = simulate_order_base_minimum
    LOGGER.critical(
        "LIVE_EXCHANGE_BASE_MINIMUM_V73_PATCHED marker=%s module=%s post_rounding_base_min=true",
        MARKER,
        module.__name__,
    )
    return True


def _has_metadata_api(broker: Any) -> bool:
    return any(callable(getattr(broker, name, None)) for name in _METADATA_METHODS)


def _maybe_register_broker(broker: Any, fallback_exchange: Any = None) -> bool:
    if broker is None:
        return False
    name = _exchange_name(broker, fallback_exchange)
    if not name or name in v72._COMPAT_STATIC:
        return False
    if not _has_metadata_api(broker):
        LOGGER.warning(
            "LIVE_CONSTRAINT_PROVIDER_V73_NOT_REGISTERED marker=%s exchange=%s "
            "reason=metadata_api_missing live_compile_will_fail_closed=true",
            MARKER,
            name or "unknown",
        )
        return False
    if name in v72.registered_constraint_providers():
        return True
    try:
        v72.register_client_constraint_provider(name, broker, replace=False)
    except RuntimeError:
        return name in v72.registered_constraint_providers()
    LOGGER.critical(
        "LIVE_CONSTRAINT_PROVIDER_V73_AUTO_REGISTERED marker=%s exchange=%s client=%s",
        MARKER,
        name,
        type(broker).__name__,
    )
    return True


def _patch_mabm(module: ModuleType) -> bool:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False
    changed = False
    for method_name in ("add_platform_broker", "add_user_broker"):
        original = getattr(cls, method_name, None)
        if not callable(original) or getattr(original, _PATCH_ATTR, False):
            continue

        @wraps(original)
        def wrapped(self: Any, *args: Any, __orig=original, __name=method_name, **kwargs: Any):
            broker = __orig(self, *args, **kwargs)
            fallback = kwargs.get("broker_type")
            if fallback is None:
                fallback = args[-1] if args else None
            _maybe_register_broker(broker, fallback)
            return broker

        setattr(wrapped, _PATCH_ATTR, True)
        setattr(wrapped, "__wrapped__", original)
        setattr(cls, method_name, wrapped)
        changed = True
    return changed


def _patch_secure_adapter(module: ModuleType) -> bool:
    cls = getattr(module, "SecureBrokerAdapter", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_load_broker_client", None)
    if not callable(original) or getattr(original, _PATCH_ATTR, False):
        return bool(callable(original))

    @wraps(original)
    def load_with_constraint_registration(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        _maybe_register_broker(
            getattr(self, "broker_client", None),
            getattr(self, "broker_name", None),
        )
        return result

    setattr(load_with_constraint_registration, _PATCH_ATTR, True)
    setattr(load_with_constraint_registration, "__wrapped__", original)
    cls._load_broker_client = load_with_constraint_registration
    return True


def _patch_loaded() -> bool:
    _install_constraint_capture()
    changed = False
    for name in ("bot.exchange_order_compiler", "exchange_order_compiler"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_eoc_module(module) or changed
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_mabm(module) or changed
    for name in ("execution.broker_adapter", "broker_adapter"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_secure_adapter(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        v72.install_import_hook()
        _patch_loaded()
        flag = "_NIJA_LIVE_EXCHANGE_BASE_MINIMUM_V73_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            text = str(name)
            if (
                "exchange_order_compiler" in text
                or "multi_account_broker_manager" in text
                or "broker_adapter" in text
            ):
                _patch_loaded()
            return result

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_LIVE_EXCHANGE_BASE_MINIMUM_V73_INSTALLED"] = "1"
        LOGGER.critical(
            "LIVE_EXCHANGE_BASE_MINIMUM_V73_INSTALLED marker=%s "
            "post_rounding_base_min=true future_provider_autoregistration=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_maybe_register_broker",
    "_patch_eoc_module",
    "_BASE_MINIMUMS",
]
