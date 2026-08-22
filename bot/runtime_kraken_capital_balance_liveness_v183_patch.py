"""Bound Kraken capital-refresh valuation without weakening capital truth.

Production on 2026-08-22 showed PLATFORM Kraken connected and position-synced,
but the canonical capital refresh repeatedly excluded Kraken after the 30 second
batch budget expired.  ``KrakenBroker.get_account_balance`` performs a private
``Balance`` read, then values every non-fiat holding through public ticker / emergency
resolution, and finally performs a private ``TradeBalance`` read.  On a cold price
cache, several serial public lookups can consume the whole capital-refresh budget
before the broker returns even though Kraken's own equivalent-balance (``eb``)
would provide an authoritative full-equity floor.

v183 changes only the capital-balance call context:
* normal market-price calls are unchanged;
* while ``get_account_balance`` is running, asset USD lookup is cache-only;
* stablecoin fallback semantics stay unchanged;
* the existing bounded authenticated ``TradeBalance`` call remains authoritative;
* ``total_funds`` remains the existing max(local valuation, Kraken ``eb``);
* if Balance / TradeBalance cannot provide usable capital, the broker remains
  excluded and the 3/3 publication gate remains fail closed.

No freshness TTL, publication expiry, broker count, writer/nonce/risk state,
kill switch, activation state, execution permission, signal threshold, or trade
routing is modified.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any, Optional

LOGGER = logging.getLogger("nija.runtime_kraken_capital_balance_liveness_v183")
MARKER = "20260822-runtime-kraken-capital-balance-liveness-v183"
RELEASE_ID = "20260822-runtime-convergence-v183"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_CAPITAL_BALANCE_LIVENESS_V183_READY"
_BALANCE_ATTR = "_nija_runtime_kraken_capital_balance_liveness_v183_balance"
_PRICE_ATTR = "_nija_runtime_kraken_capital_balance_liveness_v183_price"
_LOCK = threading.RLock()
_LOCAL = threading.local()


def _positive_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0.0 else None


def _cached_asset_price(instance: Any, symbol: str) -> Optional[float]:
    """Return broker-owned cached USD/USDT price without network I/O."""
    v173 = importlib.import_module("bot.runtime_kraken_capital_tail_liveness_v173_patch")
    cached = getattr(v173, "_cached_pair_price", None)
    if callable(cached):
        try:
            return _positive_float(cached(instance, str(symbol or "").upper()))
        except Exception:
            return None
    return None


def _in_capital_balance_context(instance: Any) -> bool:
    return getattr(_LOCAL, "broker", None) is instance and bool(
        getattr(_LOCAL, "active", False)
    )


def _patch_kraken_balance_context() -> bool:
    broker_module = importlib.import_module("bot.broker_manager")
    broker_cls = getattr(broker_module, "KrakenBroker", None)
    if not isinstance(broker_cls, type):
        return False

    current_balance = getattr(broker_cls, "get_account_balance", None)
    current_price = getattr(broker_cls, "_get_asset_usd_price", None)
    if not callable(current_balance) or not callable(current_price):
        return False

    balance_exact = (
        bool(getattr(current_balance, _BALANCE_ATTR, False))
        and str(getattr(current_balance, "__name__", "")) == "get_account_balance_v183"
        and getattr(current_balance, "__globals__", {}).get("MARKER") == MARKER
    )
    price_exact = (
        bool(getattr(current_price, _PRICE_ATTR, False))
        and str(getattr(current_price, "__name__", "")) == "asset_price_v183"
        and getattr(current_price, "__globals__", {}).get("MARKER") == MARKER
    )

    if not price_exact:
        original_price = current_price

        @wraps(original_price)
        def asset_price_v183(self: Any, symbol: str):
            if _in_capital_balance_context(self):
                price = _cached_asset_price(self, symbol)
                if price is None:
                    LOGGER.debug(
                        "KRAKEN_CAPITAL_V183_CACHE_MISS marker=%s account=%s asset=%s "
                        "network_lookup=false confidence_not_promoted=true",
                        MARKER,
                        getattr(self, "account_identifier", "unknown"),
                        symbol,
                    )
                    return 0.0
                return price
            return original_price(self, symbol)

        asset_price_v183.__name__ = "asset_price_v183"
        setattr(asset_price_v183, _PRICE_ATTR, True)
        setattr(asset_price_v183, "__wrapped__", original_price)
        broker_cls._get_asset_usd_price = asset_price_v183

    if not balance_exact:
        original_balance = current_balance

        @wraps(original_balance)
        def get_account_balance_v183(self: Any, *args: Any, **kwargs: Any):
            previous_active = getattr(_LOCAL, "active", False)
            previous_broker = getattr(_LOCAL, "broker", None)
            _LOCAL.active = True
            _LOCAL.broker = self
            try:
                return original_balance(self, *args, **kwargs)
            finally:
                _LOCAL.active = previous_active
                _LOCAL.broker = previous_broker

        get_account_balance_v183.__name__ = "get_account_balance_v183"
        setattr(get_account_balance_v183, _BALANCE_ATTR, True)
        setattr(get_account_balance_v183, "__wrapped__", original_balance)
        broker_cls.get_account_balance = get_account_balance_v183

    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_capital_balance_liveness_v183"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        balance_ok = _patch_kraken_balance_context()
        manifest_ok = _patch_release_manifest()
        ready = bool(balance_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_KRAKEN_CAPITAL_BALANCE_LIVENESS_V183_FAILED marker=%s "
                "balance_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(balance_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_KRAKEN_CAPITAL_BALANCE_LIVENESS_V183 marker=%s ready=true "
            "capital_asset_pricing_cache_only=true normal_market_pricing_unchanged=true "
            "tradebalance_equity_authority_preserved=true partial_aggregation_gate_unchanged=true "
            "freshness_extended=false publication_expiry_extended=false forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_cached_asset_price",
    "_in_capital_balance_context",
    "_patch_kraken_balance_context",
    "_patch_release_manifest",
]
