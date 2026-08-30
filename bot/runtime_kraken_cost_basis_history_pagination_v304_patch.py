"""Kraken startup cost-basis history pagination recovery v304.

Production generation 5021 on 2026-08-30 exposed a deadline/rate-profile mismatch
inside KrakenBroker.get_bulk_entry_prices().  The broker starts its default
8-second wall-clock history deadline *before* the first authenticated
TradesHistory request.  MICRO_CAP monitoring legitimately imposes roughly a
60-second pre-request wait, so page 1 may complete successfully but the local
8-second deadline is already expired before page 2 can start.  Older genuine
fills can therefore be reported as missing even though authenticated history is
healthy.

v304 leaves that generic broker method and its deadline unchanged for ordinary
callers.  Only a v288 startup bulk-cost-basis worker whose existing page-1 result
is missing one or more requested symbols may supplement those missing symbols by
reading older Kraken TradesHistory pages (offsets 50..200).  These reads use the
same _kraken_private_call path, the same monitoring category, the same credential
serialization, nonce ordering, configured rate interval, and bounded transport.
Because the reads are part of authoritative position reconciliation, v304 uses
v297's existing authoritative-priority context so repeated Balance refreshes
cannot indefinitely jump ahead of the required history pages; equal-priority
work remains FIFO and the exclusive gate is never bypassed or force-released.

Only genuine BUY fills are accepted and the same pair-matching/VWAP semantics as
the broker's existing bulk implementation are preserved.  Current-market price
fallback, synthetic cost basis, freshness extension, position fabrication,
activation forcing, and all writer/nonce/capital/risk/kill-switch/order/fill
gate changes are explicitly excluded.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Mapping

LOGGER = logging.getLogger("nija.runtime_kraken_cost_basis_history_pagination_v304")
MARKER = "20260830-kraken-cost-basis-history-pagination-v304"
RELEASE_ID = "20260830-runtime-convergence-v304"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_COST_BASIS_HISTORY_PAGINATION_V304_READY"
_PATCH_ATTR = "_nija_kraken_cost_basis_history_pagination_v304"
_PAGE_SIZE = 50


def _broker_module() -> Any:
    return importlib.import_module("bot.broker_manager")


def _v297() -> Any:
    return importlib.import_module("bot.runtime_kraken_monitoring_fairness_v297_patch")


def _max_extra_pages() -> int:
    try:
        value = int(os.environ.get("NIJA_KRAKEN_STARTUP_COST_BASIS_EXTRA_PAGES", "4") or 4)
    except (TypeError, ValueError):
        value = 4
    return max(1, min(4, value))


def _is_v288_worker() -> bool:
    return threading.current_thread().name.startswith("kraken-bulk-entry-price-v288-")


def _positive_price_map(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    parsed: dict[str, float] = {}
    for key, raw in value.items():
        symbol = str(key or "").strip().upper()
        try:
            price = float(raw or 0.0)
        except (TypeError, ValueError):
            price = 0.0
        if symbol and price > 0.0:
            parsed[symbol] = price
    return parsed


def _symbol_match_sets(symbols: tuple[str, ...]) -> dict[str, tuple[str, set[str]]]:
    module = _broker_module()
    converter = getattr(module, "convert_to_kraken", None)
    result: dict[str, tuple[str, set[str]]] = {}
    for symbol in symbols:
        currency = symbol.replace("-USD", "").replace("-USDT", "")
        pairs: set[str] = set()
        if callable(converter):
            try:
                pair = str(converter(symbol) or "").strip()
                if pair:
                    pairs.add(pair.upper())
            except Exception:
                pass
        pairs.update(
            {
                f"X{currency}ZUSD",
                f"{currency}USD",
                f"X{currency}ZUSDT",
                f"{currency}USDT",
                f"{currency}/USD",
                f"{currency}/USDT",
            }
        )
        result[symbol] = (currency.upper(), pairs)
    return result


@contextmanager
def _authoritative_history_priority():
    v297 = _v297()
    setter = getattr(v297, "_set_authoritative_priority", None)
    restorer = getattr(v297, "_restore_authoritative_priority", None)
    if not callable(setter) or not callable(restorer):
        raise RuntimeError("v297_authoritative_priority_helpers_unavailable")
    state = setter(True)
    try:
        yield
    finally:
        restorer(state)


def _history_category() -> Any:
    module = _broker_module()
    enum_cls = getattr(module, "KrakenAPICategory", None)
    return getattr(enum_cls, "MONITORING", None) if enum_cls is not None else None


def _supplement_older_history(broker: Any, missing_symbols: tuple[str, ...]) -> dict[str, float]:
    """Read only pages 2..5 for symbols page 1 did not resolve."""
    private_call = getattr(broker, "_kraken_private_call", None)
    if not callable(private_call) or not missing_symbols:
        return {}

    matches = _symbol_match_sets(missing_symbols)
    buy_rows: dict[str, list[tuple[float, float, float]]] = {}
    offset = _PAGE_SIZE
    total_count: int | None = None
    pages_read = 0
    category = _history_category()

    with _authoritative_history_priority():
        for _ in range(_max_extra_pages()):
            response = private_call(
                "TradesHistory",
                {"ofs": offset},
                category=category,
            )
            pages_read += 1
            if not isinstance(response, Mapping):
                break
            errors = response.get("error")
            if errors:
                LOGGER.warning(
                    "KRAKEN_COST_BASIS_V304_HISTORY_ERROR marker=%s account=%s offset=%d errors=%s "
                    "cost_basis_verified=false synthetic_entry=false current_price_fallback=false",
                    MARKER,
                    str(getattr(broker, "account_identifier", "unknown") or "unknown"),
                    offset,
                    errors,
                )
                break

            payload = response.get("result")
            if not isinstance(payload, Mapping):
                break
            trades = payload.get("trades")
            if not isinstance(trades, Mapping) or not trades:
                break
            if total_count is None:
                try:
                    total_count = int(payload.get("count"))
                except (TypeError, ValueError):
                    total_count = None

            for trade in trades.values():
                if not isinstance(trade, Mapping):
                    continue
                if str(trade.get("type", "") or "").strip().lower() != "buy":
                    continue
                pair = str(trade.get("pair", "") or "").strip().upper()
                if not pair:
                    continue
                for symbol, (currency, pair_set) in matches.items():
                    if symbol in buy_rows:
                        continue
                    if pair not in pair_set and currency not in pair:
                        continue
                    try:
                        price = float(trade.get("price", 0.0) or 0.0)
                        volume = float(trade.get("vol", 0.0) or 0.0)
                        trade_time = float(trade.get("time", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if price > 0.0 and volume > 0.0:
                        buy_rows.setdefault(symbol, []).append((trade_time, price, volume))
                    break

            if len(buy_rows) >= len(missing_symbols):
                break
            offset += len(trades)
            if total_count is not None and offset >= total_count:
                break

    recovered: dict[str, float] = {}
    for symbol, rows in buy_rows.items():
        total_volume = sum(volume for _, _, volume in rows)
        if total_volume <= 0.0:
            continue
        vwap = sum(price * volume for _, price, volume in rows) / total_volume
        if vwap > 0.0:
            recovered[symbol] = vwap

    account = str(getattr(broker, "account_identifier", "unknown") or "unknown")
    if recovered:
        LOGGER.critical(
            "KRAKEN_COST_BASIS_V304_OLDER_HISTORY_RECOVERED marker=%s account=%s requested=%s recovered=%s pages_read=%d "
            "authenticated_history=true page1_result_preserved=true authoritative_priority=true exclusive_gate_preserved=true "
            "rate_interval_unchanged=true transport_timeout_unchanged=true synthetic_entry=false current_price_fallback=false "
            "freshness_extended=false execution_proof_fabricated=false safety_gates_bypassed=false",
            MARKER,
            account,
            ",".join(missing_symbols),
            ",".join(sorted(recovered)),
            pages_read,
        )
    else:
        LOGGER.info(
            "KRAKEN_COST_BASIS_V304_OLDER_HISTORY_EMPTY marker=%s account=%s requested=%s pages_read=%d "
            "authenticated_history=true synthetic_entry=false current_price_fallback=false",
            MARKER,
            account,
            ",".join(missing_symbols),
            pages_read,
        )
    return recovered


def _wrap_bulk_entry_prices(current: Callable[..., Any]) -> Callable[..., Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def bulk_v304(self: Any, symbols: list[str]) -> Any:
        original_result = current(self, symbols)
        if not _is_v288_worker():
            return original_result

        requested = tuple(
            dict.fromkeys(str(symbol or "").strip().upper() for symbol in (symbols or []) if str(symbol or "").strip())
        )
        if not requested:
            return original_result
        base = _positive_price_map(original_result)
        missing = tuple(symbol for symbol in requested if symbol not in base)
        if not missing:
            return original_result

        recovered = _supplement_older_history(self, missing)
        if not recovered:
            return original_result
        merged = dict(original_result) if isinstance(original_result, Mapping) else {}
        merged.update(recovered)
        return merged

    setattr(bulk_v304, _PATCH_ATTR, True)
    setattr(bulk_v304, "__wrapped__", current)
    return bulk_v304


def _patch_kraken_bulk_history() -> bool:
    module = _broker_module()
    cls = getattr(module, "KrakenBroker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "get_bulk_entry_prices", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    cls.get_bulk_entry_prices = _wrap_bulk_entry_prices(current)
    return bool(getattr(getattr(cls, "get_bulk_entry_prices", None), _PATCH_ATTR, False))


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_cost_basis_history_pagination_v304"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    priority_ready = callable(getattr(_v297(), "_set_authoritative_priority", None)) and callable(
        getattr(_v297(), "_restore_authoritative_priority", None)
    )
    patched = _patch_kraken_bulk_history()
    return {
        "ready": bool(priority_ready and patched),
        "authoritative_priority": bool(priority_ready),
        "bulk_history_patch": bool(patched),
    }


def install() -> bool:
    manifest_ok = _register_manifest()
    try:
        state = reconcile_once()
    except Exception as exc:
        state = {"ready": False, "authoritative_priority": False, "bulk_history_patch": False, "error": f"{type(exc).__name__}:{exc}"}
    ready = bool(manifest_ok and state.get("ready"))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_COST_BASIS_HISTORY_PAGINATION_V304_%s marker=%s ready=%s "
        "authoritative_priority=%s bulk_history_patch=%s v288_worker_only=true older_pages_only=true "
        "generic_history_deadline_unchanged=true page_count_bounded=true authenticated_history_only=true "
        "exclusive_gate_preserved=true rate_interval_unchanged=true credential_lock_unchanged=true nonce_ordering_unchanged=true "
        "transport_timeout_unchanged=true synthetic_entry=false current_price_fallback=false freshness_extended=false "
        "forced_trade=false forced_activation=false writer_nonce_capital_risk_killswitch_order_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        str(bool(state.get("authoritative_priority"))).lower(),
        str(bool(state.get("bulk_history_patch"))).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_is_v288_worker",
    "_positive_price_map",
    "_symbol_match_sets",
    "_supplement_older_history",
    "_wrap_bulk_entry_prices",
    "_patch_kraken_bulk_history",
]
