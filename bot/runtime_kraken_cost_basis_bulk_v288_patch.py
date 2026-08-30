"""Bound and coalesce Kraken startup cost-basis recovery (v288).

Production on 2026-08-30 proved authoritative Kraken Balance enumeration could
recover while startup reconciliation still failed each held symbol's cost basis.
The cause was a timeout mismatch: v286 correctly moved the configured Kraken
rate wait outside the global API lock, but startup_position_sync v279 still
started one get_real_entry_price/TradesHistory request per symbol and gave each
caller only a short wait. With MICRO_CAP pacing, those per-symbol calls can time
out before the first permitted history read.

KrakenBroker already provides get_bulk_entry_prices(), which obtains broker
trade-history cost basis for a set of symbols in one read path. v288 makes
startup reconciliation use that existing bulk primitive through one
broker-scoped single-flight. Callers wait only a bounded slice and retry later;
a late genuine result is cached and reused for every authoritative held symbol.
While the bulk read is pending or failed, verified EntryPriceStore or
broker-position evidence may still satisfy the existing hierarchy, but no
current-market fallback or synthetic cost basis is introduced.

This patch does not alter authoritative quantities, v285 freshness, Kraken rate
limits, writer/nonce/capital/risk/kill-switch/order/fill gates, or exit rules.
Missing cost basis remains fail closed and auto-exit remains blocked until
genuine broker history or another already-verified source supplies an entry
price.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_kraken_cost_basis_bulk_v288")
MARKER = "20260830-kraken-cost-basis-bulk-v288"
RELEASE_ID = "20260830-runtime-convergence-v288"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_COST_BASIS_BULK_V288_READY"
_PATCH_ATTR = "_nija_kraken_cost_basis_bulk_v288"
_LOCK = threading.RLock()
_FLIGHT_LOCK = threading.RLock()
_BULK_FLIGHTS: dict[int, dict[str, Any]] = {}
_BULK_CACHE: dict[int, dict[str, Any]] = {}
_LAST_ERROR_AT: dict[int, float] = {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _real_broker(broker: Any) -> Any:
    return getattr(broker, "_broker", broker)


def _is_kraken(broker: Any) -> bool:
    real = _real_broker(broker)
    if real is None:
        return False
    if _label(getattr(real, "broker_type", "")) == "kraken":
        return True
    return type(real).__name__.lower() == "krakenbroker"


def _wait_slice_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_BULK_ENTRY_PRICE_WAIT_SLICE_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(1.0, min(15.0, value))


def _cache_ttl_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_BULK_ENTRY_PRICE_CACHE_TTL_S", "300") or 300.0)
    except (TypeError, ValueError):
        value = 300.0
    return max(30.0, min(1800.0, value))


def _error_backoff_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_BULK_ENTRY_PRICE_ERROR_BACKOFF_S", "15") or 15.0)
    except (TypeError, ValueError):
        value = 15.0
    return max(5.0, min(120.0, value))


def _authoritative_symbols(real: Any, current_symbol: str) -> tuple[str, ...]:
    symbols: set[str] = set()
    rows = tuple(getattr(real, "_nija_authoritative_position_raw_rows_v286", ()) or ())
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol", "") or "").strip().upper()
        quantity = _float(row.get("quantity", row.get("size", 0.0)))
        if symbol and quantity > 0.0:
            symbols.add(symbol)
    current = str(current_symbol or "").strip().upper()
    if current:
        symbols.add(current)
    return tuple(sorted(symbols))


def _finish_bulk_flight(flight: dict[str, Any], method: Any, symbols: tuple[str, ...]) -> None:
    try:
        result = method(list(symbols))
        if not isinstance(result, Mapping):
            raise RuntimeError(f"invalid_bulk_entry_price_payload:{type(result).__name__}")
        flight["result"] = {
            str(key or "").strip().upper(): _float(value)
            for key, value in result.items()
            if str(key or "").strip() and _float(value) > 0.0
        }
    except BaseException as exc:
        flight["error"] = exc
    finally:
        flight["finished_at"] = time.monotonic()
        flight["event"].set()


def _cache_result(key: int, flight: dict[str, Any]) -> None:
    symbols = tuple(str(value).upper() for value in tuple(flight.get("symbols", ()) or ()))
    result = flight.get("result")
    prices = dict(result) if isinstance(result, Mapping) else {}
    _BULK_CACHE[key] = {
        "symbols": frozenset(symbols),
        "prices": prices,
        "stored_at": time.monotonic(),
    }


def _cached_price(key: int, symbol: str) -> tuple[bool, float]:
    row = _BULK_CACHE.get(key)
    if not isinstance(row, dict):
        return False, 0.0
    age = max(0.0, time.monotonic() - _float(row.get("stored_at")))
    if age > _cache_ttl_s():
        _BULK_CACHE.pop(key, None)
        return False, 0.0
    covered = row.get("symbols", frozenset())
    if symbol not in covered:
        return False, 0.0
    prices = row.get("prices", {})
    value = _float(prices.get(symbol, 0.0) if isinstance(prices, Mapping) else 0.0)
    return True, max(0.0, value)


def _bounded_bulk_entry_price(broker: Any, symbol: str) -> tuple[float, str]:
    real = _real_broker(broker)
    method = getattr(real, "get_bulk_entry_prices", None)
    if not callable(method):
        return 0.0, "bulk_api_unavailable"

    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return 0.0, "bulk_api_invalid_symbol"
    key = id(real)

    with _FLIGHT_LOCK:
        covered, cached = _cached_price(key, normalized)
        if covered:
            return (cached, "trade_history") if cached > 0.0 else (0.0, "bulk_api_empty")

        flight = _BULK_FLIGHTS.get(key)
        if flight is not None and bool(flight.get("event") and flight["event"].is_set()):
            if flight.get("error") is None:
                _cache_result(key, flight)
            else:
                _LAST_ERROR_AT[key] = time.monotonic()
            _BULK_FLIGHTS.pop(key, None)
            covered, cached = _cached_price(key, normalized)
            if covered:
                return (cached, "trade_history") if cached > 0.0 else (0.0, "bulk_api_empty")
            flight = None

        last_error = _float(_LAST_ERROR_AT.get(key, 0.0))
        if flight is None and last_error > 0.0 and time.monotonic() - last_error < _error_backoff_s():
            return 0.0, "bulk_api_backoff"

        if flight is None:
            symbols = _authoritative_symbols(real, normalized)
            event = threading.Event()
            flight = {
                "event": event,
                "symbols": symbols,
                "result": None,
                "error": None,
                "started_at": time.monotonic(),
                "finished_at": 0.0,
            }
            _BULK_FLIGHTS[key] = flight
            worker = threading.Thread(
                target=_finish_bulk_flight,
                args=(flight, method, symbols),
                name=f"kraken-bulk-entry-price-v288-{getattr(real, 'account_identifier', key)}",
                daemon=True,
            )
            flight["thread"] = worker
            worker.start()
            started_new = True
        else:
            started_new = False

    wait_s = _wait_slice_s()
    if not flight["event"].wait(wait_s):
        age = max(0.0, time.monotonic() - _float(flight.get("started_at")))
        LOGGER.warning(
            "KRAKEN_COST_BASIS_V288_PENDING marker=%s account=%s symbol=%s symbols=%s "
            "wait_slice_s=%.1f age_s=%.1f single_flight_reused=%s cost_basis_verified=false "
            "synthetic_entry=false current_price_fallback=false auto_exit_authority_unchanged=true",
            MARKER,
            str(getattr(real, "account_identifier", "unknown")),
            normalized,
            ",".join(tuple(flight.get("symbols", ()) or ())),
            wait_s,
            age,
            str(not started_new).lower(),
        )
        return 0.0, "bulk_api_pending"

    error = flight.get("error")
    with _FLIGHT_LOCK:
        if _BULK_FLIGHTS.get(key) is flight:
            _BULK_FLIGHTS.pop(key, None)
        if error is None:
            _cache_result(key, flight)
        else:
            _LAST_ERROR_AT[key] = time.monotonic()

    if error is not None:
        LOGGER.warning(
            "KRAKEN_COST_BASIS_V288_ERROR marker=%s account=%s error=%s:%s "
            "cost_basis_verified=false synthetic_entry=false current_price_fallback=false",
            MARKER,
            str(getattr(real, "account_identifier", "unknown")),
            type(error).__name__,
            error,
        )
        return 0.0, "bulk_api_error"

    with _FLIGHT_LOCK:
        covered, cached = _cached_price(key, normalized)
    if covered and cached > 0.0:
        LOGGER.critical(
            "KRAKEN_COST_BASIS_V288_VERIFIED marker=%s account=%s symbol=%s entry_price=%.8f "
            "source=bulk_trade_history broker_history_required=true synthetic_entry=false "
            "current_price_fallback=false safety_gates_bypassed=false",
            MARKER,
            str(getattr(real, "account_identifier", "unknown")),
            normalized,
            cached,
        )
        return cached, "trade_history"
    return 0.0, "bulk_api_empty"


class _NoPerSymbolEntryPriceProxy:
    __slots__ = ("_target",)

    def __init__(self, target: Any) -> None:
        object.__setattr__(self, "_target", target)

    def __getattr__(self, name: str) -> Any:
        if name == "get_real_entry_price":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_target"), name)


def _patch_startup_entry_price() -> bool:
    try:
        sync = importlib.import_module("bot.startup_position_sync")
    except Exception:
        return False
    current = getattr(sync, "_resolve_entry_price", None)
    payload_reader = getattr(sync, "_position_payload_entry_price", None)
    if not callable(current) or not callable(payload_reader):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def resolve_entry_price_v288(
        broker: Any,
        symbol: str,
        eps: Any,
        broker_quantity: float,
        existing: Any = None,
        position: Any = None,
    ):
        if not _is_kraken(broker):
            return original(broker, symbol, eps, broker_quantity, existing, position=position)

        payload_price, payload_source = payload_reader(position, broker_quantity)
        if _float(payload_price) > 0.0:
            return payload_price, payload_source

        bulk_price, bulk_source = _bounded_bulk_entry_price(broker, symbol)
        if bulk_price > 0.0:
            return bulk_price, "trade_history"

        # Preserve non-API fallbacks in v279 (verified EntryPriceStore and
        # legacy reconstruction) while suppressing the N-per-symbol
        # get_real_entry_price calls that caused the startup stall.
        fallback_broker = _NoPerSymbolEntryPriceProxy(broker)
        fallback_price, fallback_source = original(
            fallback_broker,
            symbol,
            eps,
            broker_quantity,
            existing,
            position=position,
        )
        if _float(fallback_price) > 0.0:
            return fallback_price, fallback_source
        return 0.0, bulk_source

    setattr(resolve_entry_price_v288, _PATCH_ATTR, True)
    setattr(resolve_entry_price_v288, "__wrapped__", original)
    sync._resolve_entry_price = resolve_entry_price_v288
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_cost_basis_bulk_v288"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        patched = _patch_startup_entry_price()
        manifest_ok = _register_manifest()
        ready = bool(patched and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        LOGGER.critical(
            "RUNTIME_KRAKEN_COST_BASIS_BULK_V288_%s marker=%s ready=%s "
            "broker_scoped_single_flight=true bulk_trade_history=true per_symbol_history_suppressed=true "
            "bounded_caller_wait=true late_real_result_reused=true broker_position_and_verified_store_preserved=true "
            "cost_basis_fabricated=false current_price_fallback=false authoritative_quantity_unchanged=true "
            "kraken_rate_limits_unchanged=true forced_trade=false forced_activation=false "
            "writer_nonce_capital_risk_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_bounded_bulk_entry_price", "_patch_startup_entry_price",
]
