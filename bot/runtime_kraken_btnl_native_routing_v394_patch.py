"""Kraken BTNL native protective-order routing repair v394.

Kraken US retail margin positions are executed on the Bitnomial (``:BTNL``)
venue.  v381 intentionally strips NIJA's terminal suffix for public market-data
resolution, but v380 previously reused that public pair for private AddOrder
calls.  That can park a NIJA-tagged stop on the standard venue while the real
margin exposure remains on ``:BTNL``.

This repair is deliberately narrow and fail-closed:
* public/reference-market lookup remains on the existing v381 resolver;
* private v380 SL/TP AddOrder uses the authenticated OpenPositions ``:BTNL``
  identity unchanged;
* OpenOrders ``:BTNL`` formatting differences (ETH/USD:BTNL vs ETHUSD:BTNL)
  are normalized only within the same BTNL venue;
* old NIJA-tagged v380 orders tied to an active BTNL position but parked on a
  non-BTNL venue are cancelled before re-arming;
* SELL, reduce_only, leverage, authenticated OpenPositions/OpenOrders proof,
  client-id collision recovery and software four-way protection are unchanged.

No new exposure is created and an AddOrder acknowledgement is never promoted to
protection proof.
"""
from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_btnl_native_routing_v394")
MARKER = "20260907-kraken-btnl-native-routing-v394"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_BTNL_NATIVE_ROUTING_V394_READY"
_PAIR_PATCH_ATTR = "_nija_v394_btnl_private_order_pair"
_NORMALISE_PATCH_ATTR = "_nija_v394_btnl_openorders_identity"
_CLEANUP_PATCH_ATTR = "_nija_v394_btnl_wrong_venue_cleanup"
_PREFIXES = ("njsl", "njtp")


def _compact_head(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    head = raw.split(":", 1)[0]
    return head.replace("/", "").replace("-", "").replace("_", "")


def _btnl_identity(value: Any) -> str:
    """Canonicalize separators while preserving the BTNL execution venue."""
    raw = str(value or "").strip().upper()
    if not raw or ":" not in raw:
        return raw
    head, suffix = raw.split(":", 1)
    if suffix != "BTNL":
        return raw
    compact = head.replace("/", "").replace("-", "").replace("_", "")
    return f"{compact}:BTNL" if compact else ""


def _patch_v367_openorders_normalizer() -> bool:
    v367 = importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")
    current = getattr(v367, "_normalise_open_orders", None)
    if not callable(current):
        return False
    if bool(getattr(current, _NORMALISE_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def normalise_open_orders_v394(payload: Any):
        ok, rows, reason = current(payload)
        if not ok:
            return ok, rows, reason
        merged: dict[str, dict[str, Any]] = {}
        for raw_symbol, raw_row in dict(rows or {}).items():
            symbol = str(raw_symbol or "")
            identity = _btnl_identity(symbol) if ":BTNL" in symbol.upper() else symbol
            row = dict(raw_row or {})
            target = merged.setdefault(
                identity,
                {
                    "stop_qty": 0.0,
                    "take_profit_qty": 0.0,
                    "stop_order_ids": [],
                    "take_profit_order_ids": [],
                },
            )
            try:
                target["stop_qty"] += max(0.0, float(row.get("stop_qty") or 0.0))
            except Exception:
                pass
            try:
                target["take_profit_qty"] += max(0.0, float(row.get("take_profit_qty") or 0.0))
            except Exception:
                pass
            target["stop_order_ids"].extend(str(x) for x in tuple(row.get("stop_order_ids", ()) or ()) if str(x))
            target["take_profit_order_ids"].extend(
                str(x) for x in tuple(row.get("take_profit_order_ids", ()) or ()) if str(x)
            )
        for row in merged.values():
            row["stop_order_ids"] = tuple(sorted(set(row["stop_order_ids"])))
            row["take_profit_order_ids"] = tuple(sorted(set(row["take_profit_order_ids"])))
        return True, merged, reason

    setattr(normalise_open_orders_v394, _NORMALISE_PATCH_ATTR, True)
    setattr(normalise_open_orders_v394, "__wrapped__", current)
    v367._normalise_open_orders = normalise_open_orders_v394
    cache = getattr(v367, "_NATIVE_CACHE", None)
    if isinstance(cache, dict):
        cache.clear()
    return True


def _patch_v380_private_pair() -> bool:
    v380 = importlib.import_module("bot.runtime_kraken_native_margin_backup_v380_patch")
    current = getattr(v380, "_pair_and_price", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PAIR_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def pair_and_price_v394(broker: Any, symbol: str):
        market_pair, current_price = current(broker, symbol)
        raw = str(symbol or "").strip()
        venue_identity = _btnl_identity(raw)
        if not venue_identity:
            return market_pair, current_price
        if not venue_identity.endswith(":BTNL"):
            return market_pair, current_price
        if not market_pair or float(current_price or 0.0) <= 0.0:
            return "", 0.0
        # Prove the public resolver did not drift to a different base/quote pair.
        if _compact_head(market_pair) != _compact_head(venue_identity):
            LOGGER.error(
                "KRAKEN_BTNL_NATIVE_PAIR_V394_MISMATCH marker=%s symbol=%s market_pair=%s "
                "private_order_deferred=true new_exposure=false safety_gates_bypassed=false",
                MARKER, raw, market_pair,
            )
            return "", 0.0
        LOGGER.info(
            "KRAKEN_BTNL_NATIVE_PAIR_V394_ROUTED marker=%s position_symbol=%s market_pair=%s "
            "private_order_pair=%s venue_preserved=true public_market_lookup_unchanged=true "
            "reduce_only_unchanged=true safety_gates_bypassed=false",
            MARKER, raw, market_pair, venue_identity,
        )
        return venue_identity, float(current_price)

    setattr(pair_and_price_v394, _PAIR_PATCH_ATTR, True)
    setattr(pair_and_price_v394, "__wrapped__", current)
    v380._pair_and_price = pair_and_price_v394
    return True


def _client_matches_active_btnl(v380: Any, account: str, client_id: str, active_symbol: str) -> bool:
    wanted = str(client_id or "").strip()
    if not wanted or not active_symbol.upper().endswith(":BTNL"):
        return False
    scope_fn = getattr(v380, "_client_id_scope_v392", None)
    for leg in ("stop-loss", "take-profit"):
        try:
            if wanted == str(v380._client_id(account, active_symbol, leg)):
                return True
        except Exception:
            pass
        if callable(scope_fn):
            try:
                scope = str(scope_fn(account, active_symbol, leg) or "")
            except Exception:
                scope = ""
            if scope and wanted.startswith(scope):
                return True
    return False


def _patch_v380_wrong_venue_cleanup() -> bool:
    v380 = importlib.import_module("bot.runtime_kraken_native_margin_backup_v380_patch")
    current = getattr(v380, "_cleanup_orphans", None)
    if not callable(current):
        return False
    if bool(getattr(current, _CLEANUP_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def cleanup_orphans_v394(account: str, broker: Any, active_symbols: set[str]):
        cancelled = list(current(account, broker, active_symbols) or ())
        active_btnl = {
            _btnl_identity(symbol)
            for symbol in set(active_symbols or set())
            if _btnl_identity(symbol).endswith(":BTNL")
        }
        active_btnl.discard("")
        if not active_btnl:
            return tuple(dict.fromkeys(cancelled))
        try:
            payload = v380._call(broker, "OpenOrders", {"trades": "false"}, "QUERY")
        except Exception:
            return tuple(dict.fromkeys(cancelled))
        if not isinstance(payload, Mapping) or (payload.get("error") or []):
            return tuple(dict.fromkeys(cancelled))
        result = payload.get("result") or {}
        opened = result.get("open", result) if isinstance(result, Mapping) else {}
        if not isinstance(opened, Mapping):
            return tuple(dict.fromkeys(cancelled))

        for order_id, raw in opened.items():
            if not isinstance(raw, Mapping):
                continue
            client_id = str(raw.get("cl_ord_id") or raw.get("cl_ordid") or "").strip()
            if not client_id.startswith(_PREFIXES):
                continue
            descr = raw.get("descr") if isinstance(raw.get("descr"), Mapping) else {}
            order_pair = descr.get("pair") or raw.get("pair")
            order_identity = _btnl_identity(order_pair)
            for active_symbol in active_btnl:
                if not _client_matches_active_btnl(v380, str(account), client_id, active_symbol):
                    continue
                if order_identity == active_symbol:
                    break
                try:
                    response = v380._call(broker, "CancelOrder", {"txid": str(order_id)}, "EXIT")
                except Exception:
                    break
                if isinstance(response, Mapping) and not (response.get("error") or []):
                    cancelled.append(str(order_id))
                    LOGGER.critical(
                        "KRAKEN_BTNL_NATIVE_WRONG_VENUE_CANCELLED_V394 marker=%s account=%s order_id=%s "
                        "client_id=%s order_pair=%s required_pair=%s authenticated_btnl_exposure=true "
                        "nija_tag_match=true unrelated_orders_untouched=true new_exposure=false "
                        "safety_gates_bypassed=false",
                        MARKER, account, order_id, client_id, order_pair, active_symbol,
                    )
                break
        return tuple(dict.fromkeys(cancelled))

    setattr(cleanup_orphans_v394, _CLEANUP_PATCH_ATTR, True)
    setattr(cleanup_orphans_v394, "__wrapped__", current)
    v380._cleanup_orphans = cleanup_orphans_v394
    return True


def install_import_hook() -> bool:
    normalizer_ready = _patch_v367_openorders_normalizer()
    pair_ready = _patch_v380_private_pair()
    cleanup_ready = _patch_v380_wrong_venue_cleanup()
    ready = bool(normalizer_ready and pair_ready and cleanup_ready)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    LOGGER.critical(
        "RUNTIME_KRAKEN_BTNL_NATIVE_ROUTING_V394_%s marker=%s ready=%s "
        "openorders_btnl_identity=%s private_addorder_btnl_pair=%s wrong_venue_cleanup=%s "
        "public_market_lookup_unchanged=true reduce_only_unchanged=true leverage_unchanged=true "
        "authenticated_openpositions_openorders_required=true ack_not_protection_proof=true "
        "software_four_way_unchanged=true new_exposure=false safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        str(normalizer_ready).lower(), str(pair_ready).lower(), str(cleanup_ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "_btnl_identity",
    "_patch_v367_openorders_normalizer", "_patch_v380_private_pair",
    "_patch_v380_wrong_venue_cleanup",
]
