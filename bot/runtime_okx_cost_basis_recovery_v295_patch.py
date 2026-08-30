"""Bounded OKX startup cost-basis recovery from genuine fill history (v295).

Production on 2026-08-30 proved that OKX authoritative position enumeration was
healthy while startup reconciliation rejected both tiny BTC/ETH holdings because
historical entry price was unresolved. The broker already exposes
``get_bulk_entry_prices()``, which reads OKX fills and computes BUY VWAP, but the
canonical startup resolver only consulted per-symbol ``get_real_entry_price`` and
therefore never used that existing broker-native evidence path.

v295 adds a broker-scoped, bounded single-flight around the existing OKX bulk-fill
primitive and consults it before falling through to the canonical resolver. A
real positive VWAP is returned with source ``trade_history`` so the existing
PositionTracker verification rules remain authoritative. Pending, empty, failed,
or malformed history remains unverified and fail closed.

No market-price fallback, synthetic entry price, dust exception, position
fabrication, readiness grant, order, fill, risk, kill-switch, writer, nonce, or
capital behavior is introduced or changed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_okx_cost_basis_recovery_v295")
MARKER = "20260830-okx-cost-basis-recovery-v295"
RELEASE_ID = "20260830-runtime-convergence-v295"
_READY_FLAG = "NIJA_RUNTIME_OKX_COST_BASIS_RECOVERY_V295_READY"
_PATCH_ATTR = "_nija_okx_cost_basis_recovery_v295"
_LOCK = threading.RLock()
_FLIGHT_LOCK = threading.RLock()
_FLIGHTS: dict[int, dict[str, Any]] = {}
_CACHE: dict[int, dict[str, Any]] = {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
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


def _is_okx(broker: Any) -> bool:
    real = _real_broker(broker)
    if real is None:
        return False
    if _label(getattr(real, "broker_type", "")) == "okx":
        return True
    return type(real).__name__.lower() == "okxbroker"


def _wait_s() -> float:
    try:
        value = float(os.environ.get("NIJA_OKX_ENTRY_PRICE_WAIT_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(1.0, min(15.0, value))


def _cache_ttl_s() -> float:
    try:
        value = float(os.environ.get("NIJA_OKX_ENTRY_PRICE_CACHE_TTL_S", "600") or 600.0)
    except (TypeError, ValueError):
        value = 600.0
    return max(30.0, min(3600.0, value))


def _finish_flight(flight: dict[str, Any], method: Any, symbol: str) -> None:
    try:
        result = method([symbol])
        if not isinstance(result, Mapping):
            raise RuntimeError(f"invalid_okx_bulk_entry_price_payload:{type(result).__name__}")
        price = _float(result.get(symbol, 0.0))
        flight["price"] = price if price > 0.0 else 0.0
    except BaseException as exc:
        flight["error"] = exc
    finally:
        flight["finished_at"] = time.monotonic()
        flight["event"].set()


def _cached_price(key: int, symbol: str) -> tuple[bool, float]:
    row = _CACHE.get(key)
    if not isinstance(row, dict):
        return False, 0.0
    if max(0.0, time.monotonic() - _float(row.get("stored_at"))) > _cache_ttl_s():
        _CACHE.pop(key, None)
        return False, 0.0
    values = row.get("prices", {})
    if not isinstance(values, Mapping) or symbol not in values:
        return False, 0.0
    return True, max(0.0, _float(values.get(symbol)))


def _store_result(key: int, symbol: str, price: float) -> None:
    row = _CACHE.setdefault(key, {"prices": {}, "stored_at": time.monotonic()})
    values = row.setdefault("prices", {})
    values[symbol] = max(0.0, float(price))
    row["stored_at"] = time.monotonic()


def _bounded_okx_entry_price(broker: Any, symbol: str) -> tuple[float, str]:
    real = _real_broker(broker)
    method = getattr(real, "get_bulk_entry_prices", None)
    normalized = str(symbol or "").strip().upper()
    if not callable(method) or not normalized:
        return 0.0, "okx_bulk_history_unavailable"

    key = id(real)
    with _FLIGHT_LOCK:
        covered, cached = _cached_price(key, normalized)
        if covered:
            return (cached, "trade_history") if cached > 0.0 else (0.0, "okx_bulk_history_empty")

        flight = _FLIGHTS.get(key)
        if flight is not None and flight.get("symbol") != normalized:
            # One broker history worker at a time. A different symbol will be
            # retried on the next reconciliation pass rather than starting a
            # parallel OKX private-history request.
            return 0.0, "okx_bulk_history_other_symbol_pending"

        if flight is not None and bool(flight["event"].is_set()):
            _FLIGHTS.pop(key, None)
            error = flight.get("error")
            price = max(0.0, _float(flight.get("price")))
            if error is None:
                _store_result(key, normalized, price)
                return (price, "trade_history") if price > 0.0 else (0.0, "okx_bulk_history_empty")
            LOGGER.warning(
                "OKX_COST_BASIS_V295_ERROR marker=%s account=%s symbol=%s error=%s:%s cost_basis_verified=false synthetic_entry=false",
                MARKER,
                str(getattr(real, "account_identifier", "unknown")),
                normalized,
                type(error).__name__,
                error,
            )
            return 0.0, "okx_bulk_history_error"

        if flight is None:
            flight = {
                "symbol": normalized,
                "event": threading.Event(),
                "price": 0.0,
                "error": None,
                "started_at": time.monotonic(),
                "finished_at": 0.0,
            }
            _FLIGHTS[key] = flight
            worker = threading.Thread(
                target=_finish_flight,
                args=(flight, method, normalized),
                name=f"okx-entry-price-v295-{getattr(real, 'account_identifier', key)}-{normalized}",
                daemon=True,
            )
            flight["thread"] = worker
            worker.start()
            started_new = True
        else:
            started_new = False

    wait_s = _wait_s()
    if not flight["event"].wait(wait_s):
        age = max(0.0, time.monotonic() - _float(flight.get("started_at")))
        LOGGER.warning(
            "OKX_COST_BASIS_V295_PENDING marker=%s account=%s symbol=%s wait_s=%.1f age_s=%.1f single_flight_reused=%s cost_basis_verified=false synthetic_entry=false current_price_fallback=false",
            MARKER,
            str(getattr(real, "account_identifier", "unknown")),
            normalized,
            wait_s,
            age,
            str(not started_new).lower(),
        )
        return 0.0, "okx_bulk_history_pending"

    with _FLIGHT_LOCK:
        if _FLIGHTS.get(key) is flight:
            _FLIGHTS.pop(key, None)
        error = flight.get("error")
        price = max(0.0, _float(flight.get("price")))
        if error is None:
            _store_result(key, normalized, price)

    if error is not None:
        LOGGER.warning(
            "OKX_COST_BASIS_V295_ERROR marker=%s account=%s symbol=%s error=%s:%s cost_basis_verified=false synthetic_entry=false",
            MARKER,
            str(getattr(real, "account_identifier", "unknown")),
            normalized,
            type(error).__name__,
            error,
        )
        return 0.0, "okx_bulk_history_error"
    if price <= 0.0:
        LOGGER.info(
            "OKX_COST_BASIS_V295_EMPTY marker=%s account=%s symbol=%s genuine_history_checked=true cost_basis_verified=false synthetic_entry=false",
            MARKER,
            str(getattr(real, "account_identifier", "unknown")),
            normalized,
        )
        return 0.0, "okx_bulk_history_empty"

    LOGGER.critical(
        "OKX_COST_BASIS_V295_VERIFIED marker=%s account=%s symbol=%s entry_price=%.8f source=okx_fill_history synthetic_entry=false current_price_fallback=false safety_gates_bypassed=false",
        MARKER,
        str(getattr(real, "account_identifier", "unknown")),
        normalized,
        price,
    )
    return price, "trade_history"


def _patch_startup_resolver() -> bool:
    try:
        sync = importlib.import_module("bot.startup_position_sync")
    except Exception:
        return False
    current = getattr(sync, "_resolve_entry_price", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def resolve_entry_price_v295(
        broker: Any,
        symbol: str,
        eps: Any,
        broker_quantity: float,
        existing: Any = None,
        position: Any = None,
    ):
        if _is_okx(broker):
            price, source = _bounded_okx_entry_price(broker, symbol)
            if price > 0.0:
                return price, source
        return original(
            broker,
            symbol,
            eps,
            broker_quantity,
            existing,
            position=position,
        )

    setattr(resolve_entry_price_v295, _PATCH_ATTR, True)
    setattr(resolve_entry_price_v295, "__wrapped__", original)
    sync._resolve_entry_price = resolve_entry_price_v295
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_okx_cost_basis_recovery_v295"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        patched = _patch_startup_resolver()
        manifest = _register_manifest()
        ready = bool(patched and manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_OKX_COST_BASIS_RECOVERY_V295_%s marker=%s ready=%s broker_native_fill_history=true bounded_single_flight=true trade_history_source_required=true synthetic_entry=false current_price_fallback=false dust_policy_unchanged=true position_success_fabricated=false execution_proof_fabricated=false forced_trade=false forced_activation=false writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_is_okx",
    "_bounded_okx_entry_price",
    "_patch_startup_resolver",
]
