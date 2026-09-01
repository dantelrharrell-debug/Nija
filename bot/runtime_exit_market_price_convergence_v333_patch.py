"""Universal exit canonical market-price convergence v333.

Production exit tracing on 2026-08-31 proved that v285 could hold a fresh,
verified and strongly profitable Coinbase/Kraken ETH position while v67 emitted
no trigger.  The final silent pre-trigger gate was ``auto_exit._price``: it tried
quote/ticker helper names but NIJA's canonical Coinbase, Kraken and OKX broker
classes expose their live public price through ``get_current_price(symbol)``.
A valid position could therefore be skipped with market=0 before any exit rule
was evaluated.

v333 extends only price acquisition:
* keep every existing _price source first;
* if those return no positive price, call canonical read-only public price
  methods (get_current_price, get_price, get_last_price);
* accept only finite positive values or explicit quote fields;
* cache a genuine result for a very short TTL to prevent the 3-second universal
  exit scan from multiplying public market-data traffic across wrappers;
* never substitute position entry price, cost basis, requested price, or a stale
  arbitrary constant for a market observation.

No private broker read, position quantity, order, fill, profit, readiness, risk,
writer, nonce, kill-switch, minimum-order, or reconciliation contract is
changed.  v67 still requires a confirmed fill before local close.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import threading
import time
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_exit_market_price_convergence_v333")
MARKER = "20260831-exit-market-price-convergence-v333"
RELEASE_ID = "20260831-runtime-convergence-v333"
_READY_FLAG = "NIJA_RUNTIME_EXIT_MARKET_PRICE_CONVERGENCE_V333_READY"
_PATCH_ATTR = "_nija_exit_market_price_convergence_v333"
_INSTALL_FLAG = "_NIJA_RUNTIME_EXIT_MARKET_PRICE_CONVERGENCE_V333"
_LOCK = threading.RLock()
_CACHE_LOCK = threading.RLock()
_PRICE_CACHE: dict[tuple[int, str], tuple[float, float, str]] = {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _extract_price(payload: Any) -> float:
    if isinstance(payload, Mapping):
        for key in (
            "price", "last", "last_price", "lastPrice", "mark_price", "markPrice",
            "close", "current_price", "currentPrice",
        ):
            value = _f(payload.get(key))
            if value > 0.0:
                return value
        bid = 0.0
        ask = 0.0
        for key in ("bid", "best_bid", "bestBid", "bid_price", "bidPrice"):
            bid = _f(payload.get(key))
            if bid > 0.0:
                break
        for key in ("ask", "best_ask", "bestAsk", "ask_price", "askPrice"):
            ask = _f(payload.get(key))
            if ask > 0.0:
                break
        if bid > 0.0 and ask > 0.0:
            return (bid + ask) / 2.0
        result = payload.get("result")
        if isinstance(result, Mapping):
            nested = _extract_price(result)
            if nested > 0.0:
                return nested
        data = payload.get("data")
        if isinstance(data, list) and data:
            nested = _extract_price(data[0])
            if nested > 0.0:
                return nested
        return 0.0
    value = _f(payload)
    return value if value > 0.0 else 0.0


def _cache_ttl_s() -> float:
    return max(0.5, min(10.0, _f(os.environ.get("NIJA_EXIT_MARKET_PRICE_CACHE_TTL_S"), 2.5)))


def _cached(broker: Any, symbol: str) -> tuple[float, str]:
    key = (id(broker), _symbol(symbol))
    with _CACHE_LOCK:
        item = _PRICE_CACHE.get(key)
    if item is None:
        return 0.0, ""
    observed_at, price, source = item
    if time.monotonic() - observed_at <= _cache_ttl_s() and price > 0.0:
        return price, source
    return 0.0, ""


def _store(broker: Any, symbol: str, price: float, source: str) -> None:
    if price <= 0.0:
        return
    key = (id(broker), _symbol(symbol))
    with _CACHE_LOCK:
        _PRICE_CACHE[key] = (time.monotonic(), price, source)
        if len(_PRICE_CACHE) > 512:
            cutoff = time.monotonic() - max(10.0, _cache_ttl_s() * 4.0)
            for old_key, item in tuple(_PRICE_CACHE.items()):
                if item[0] < cutoff:
                    _PRICE_CACHE.pop(old_key, None)


def _patch_price() -> bool:
    auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    current = getattr(auto_exit, "_price", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def canonical_exit_price(broker: Any, symbol: str) -> float:
        # Existing paths remain authoritative when available.
        try:
            existing = _f(current(broker, symbol))
        except Exception:
            existing = 0.0
        if existing > 0.0:
            _store(broker, symbol, existing, "legacy_exit_quote_path")
            return existing

        cached, cached_source = _cached(broker, symbol)
        if cached > 0.0:
            return cached

        for method_name in ("get_current_price", "get_price", "get_last_price"):
            method = getattr(broker, method_name, None)
            if not callable(method):
                continue
            try:
                payload = method(symbol)
            except TypeError:
                try:
                    payload = method(symbol=symbol)
                except Exception:
                    continue
            except Exception:
                continue
            price = _extract_price(payload)
            if price <= 0.0:
                continue
            _store(broker, symbol, price, method_name)
            LOGGER.info(
                "EXIT_MARKET_PRICE_V333_OBSERVED marker=%s venue=%s symbol=%s price=%.8f "
                "source=%s public_market_read=true synthetic_price=false entry_price_reuse=false "
                "order_submitted=false safety_gates_bypassed=false",
                MARKER,
                getattr(getattr(broker, "broker_type", None), "value", getattr(broker, "broker_type", type(broker).__name__)),
                _symbol(symbol),
                price,
                method_name,
            )
            return price

        # Log the formerly silent skip, rate-limited naturally by scan/cache flow.
        LOGGER.warning(
            "EXIT_MARKET_PRICE_V333_UNAVAILABLE marker=%s venue=%s symbol=%s "
            "sources=legacy,get_current_price,get_price,get_last_price exit_not_submitted=true "
            "synthetic_price=false fail_closed=true safety_gates_bypassed=false",
            MARKER,
            getattr(getattr(broker, "broker_type", None), "value", getattr(broker, "broker_type", type(broker).__name__)),
            _symbol(symbol),
        )
        return 0.0

    setattr(canonical_exit_price, _PATCH_ATTR, True)
    setattr(canonical_exit_price, "__wrapped__", current)
    auto_exit._price = canonical_exit_price
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_exit_market_price_convergence_v333"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_EXIT_JIT_CONFLICT_RECOVERY_V332_READY") != "1":
                raise RuntimeError("v332_not_ready")
            patched = _patch_price()
            manifest = _register_manifest()
            ready = bool(patched and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "EXIT_MARKET_PRICE_V333_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true forced_exit=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_EXIT_MARKET_PRICE_CONVERGENCE_V333_%s marker=%s ready=%s "
            "canonical_get_current_price=true short_price_cache=true synthetic_price=false "
            "entry_price_reuse=false public_market_data_only=true v332_required=true "
            "v67_fill_confirmation_preserved=true writer_nonce_risk_killswitch_minimum_order_unchanged=true "
            "forced_loss_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_extract_price"]
