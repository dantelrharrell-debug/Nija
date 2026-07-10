"""Shared primitives for NIJA's final execution contract."""
from __future__ import annotations

import os
import threading
import time
from contextvars import ContextVar
from dataclasses import is_dataclass, replace
from typing import Any, Optional

MARKER = "20260710a"
TRUE = {"1", "true", "yes", "on", "enabled", "y"}
SYNTHETIC_IDS = {"", "none", "null", "pipeline", "synthetic", "unknown", "n/a"}
PINNED_AUTHORITY: ContextVar[Any | None] = ContextVar("nija_pinned_authority", default=None)
LAST_ACK: ContextVar[dict[str, Any] | None] = ContextVar("nija_last_verified_ack", default=None)
_ACK_LOCK = threading.Lock()
_ACKS: dict[str, dict[str, Any]] = {}


def truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in TRUE


def number(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if value == value else default
    except Exception:
        return default


def broker_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower().split(":", 1)[0]
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    for name in ("kraken", "coinbase", "okx", "alpaca", "binance"):
        if name in compact:
            return name
    return text


def broker_from_object(obj: Any) -> str:
    if obj is None:
        return ""
    for attr in ("broker_type", "broker_name", "name", "NAME", "exchange", "venue"):
        try:
            name = broker_name(getattr(obj, attr, None))
            if name:
                return name
        except Exception:
            pass
    return broker_name(type(obj).__name__.replace("Broker", ""))


def normalize_symbol(value: Any) -> str:
    value = str(value or "").strip().upper().replace("/", "-").replace("_", "-")
    return value[:-1] if value.endswith("-USDTT") else value


def metadata(request: Any) -> dict[str, Any]:
    try:
        return dict(getattr(request, "metadata", {}) or {})
    except Exception:
        return {}


def replace_request(request: Any, **updates: Any) -> Any:
    if is_dataclass(request):
        try:
            return replace(request, **updates)
        except Exception:
            pass
    for name, value in updates.items():
        try:
            setattr(request, name, value)
        except Exception:
            pass
    return request


def extract_order_id(value: Any, depth: int = 0) -> str:
    if value is None or depth > 3:
        return ""
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return "" if text.lower() in SYNTHETIC_IDS else text
    if isinstance(value, dict):
        for key in ("order_id", "orderId", "ordId", "txid", "transaction_id", "client_order_id", "id"):
            found = extract_order_id(value.get(key), depth + 1)
            if found:
                return found
        for key in ("order", "result", "response", "data", "raw", "payload"):
            found = extract_order_id(value.get(key), depth + 1)
            if found:
                return found
        return ""
    for attr in ("order_id", "orderId", "ordId", "txid", "transaction_id", "client_order_id", "id"):
        try:
            found = extract_order_id(getattr(value, attr, None), depth + 1)
            if found:
                return found
        except Exception:
            pass
    for attr in ("order", "result", "response", "data", "raw", "payload"):
        try:
            found = extract_order_id(getattr(value, attr, None), depth + 1)
            if found:
                return found
        except Exception:
            pass
    return ""


def request_key(request: Any) -> str:
    meta = metadata(request)
    for candidate in (
        getattr(request, "request_id", None), getattr(request, "intent_id", None),
        meta.get("request_id"), meta.get("intent_id"), meta.get("cycle_id"),
    ):
        if str(candidate or "").strip():
            return str(candidate).strip()
    broker = broker_name(
        getattr(request, "preferred_broker", None) or meta.get("execution_broker")
        or meta.get("dispatch_broker") or meta.get("broker_name")
    )
    account = str(getattr(request, "account_id", None) or meta.get("account_id") or "default").lower()
    return "%s:%s:%s:%s:%.8f" % (
        account, broker, normalize_symbol(getattr(request, "symbol", "")),
        str(getattr(request, "side", "")).lower(), number(getattr(request, "size_usd", 0.0)),
    )


def store_ack(request: Any, result: Any) -> None:
    order_id = extract_order_id(result)
    if not order_id:
        return
    record = {
        "order_id": order_id,
        "broker": broker_name(getattr(result, "broker", "")),
        "fill_price": number(getattr(result, "fill_price", 0.0)),
        "filled_size_usd": number(getattr(result, "filled_size_usd", 0.0)),
        "ts": time.monotonic(),
    }
    with _ACK_LOCK:
        _ACKS[request_key(request)] = record
        if len(_ACKS) > 2000:
            cutoff = time.monotonic() - 900.0
            for key in [k for k, v in _ACKS.items() if number(v.get("ts")) < cutoff]:
                _ACKS.pop(key, None)


def pop_ack(request: Any) -> dict[str, Any]:
    with _ACK_LOCK:
        return dict(_ACKS.pop(request_key(request), {}) or {})


def _cash_mapping(payload: Any) -> Optional[float]:
    if not isinstance(payload, dict):
        return None
    for key in ("available_usd", "usd_available", "available_cash_usd", "trading_balance_usd", "cash_usd", "buying_power_usd", "available", "free", "cash"):
        if key in payload:
            value = number(payload.get(key), -1.0)
            if value >= 0:
                return value
    total, found = 0.0, False
    for quote in ("USD", "USDC"):
        item = payload.get(quote, payload.get(quote.lower()))
        if item is None:
            continue
        if isinstance(item, dict):
            for key in ("available", "free", "cash", "balance", "amount"):
                if key in item:
                    total += number(item.get(key)); found = True; break
        else:
            total += number(item); found = True
    if found:
        return total
    rows = payload.get("accounts") or payload.get("balances") or payload.get("data")
    if isinstance(rows, list):
        total, found = 0.0, False
        for row in rows:
            if not isinstance(row, dict) or str(row.get("currency") or row.get("asset") or "").upper() not in {"USD", "USDC"}:
                continue
            for key in ("available_balance", "available", "free", "cash", "balance", "amount"):
                raw = row.get(key)
                if isinstance(raw, dict):
                    raw = raw.get("value") or raw.get("amount")
                value = number(raw, -1.0)
                if value >= 0:
                    total += value; found = True; break
        if found:
            return total
    return None


def venue_cash(client: Any) -> Optional[float]:
    if client is None:
        return None
    for attr in ("_advanced_trade_available_cash_usd", "_venue_available_cash_usd", "_spot_available_cash_usd", "_available_cash_usd", "_last_known_cash_usd", "_last_known_available_cash_usd"):
        try:
            value = number(getattr(client, attr), -1.0)
            if value >= 0:
                return value
        except Exception:
            pass
    for attr in ("_balance_cache", "_last_balance_snapshot", "_last_account_inventory"):
        value = _cash_mapping(getattr(client, attr, None))
        if value is not None:
            return value
    for method in ("get_spot_trading_cash", "get_available_cash_usd", "get_available_usd", "get_usd_available", "get_cash_balance", "get_available_balance", "get_account_balance", "get_balance", "fetch_balance"):
        fn = getattr(client, method, None)
        if not callable(fn):
            continue
        try:
            payload = fn()
        except (TypeError, Exception):
            continue
        if isinstance(payload, (int, float, str)):
            value = number(payload, -1.0)
            if value >= 0:
                return value
        value = _cash_mapping(payload)
        if value is not None:
            return value
    return None


def minimum_notional(broker: str) -> float:
    keys = {
        "kraken": ("KRAKEN_MIN_NOTIONAL_USD", "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD", "MIN_TRADE_USD"),
        "coinbase": ("COINBASE_MIN_ORDER_USD", "NIJA_COINBASE_MIN_ORDER_USD", "MIN_TRADE_USD"),
        "okx": ("OKX_MIN_ORDER_USD", "NIJA_OKX_MIN_ORDER_USD", "MIN_TRADE_USD"),
        "alpaca": ("ALPACA_MIN_ORDER_USD", "MIN_TRADE_USD"),
    }
    for key in keys.get(broker_name(broker), ("MIN_TRADE_USD",)):
        if key in os.environ and number(os.environ.get(key)) > 0:
            return number(os.environ.get(key))
    return 1.0 if broker_name(broker) in {"coinbase", "alpaca"} else 10.0


def freeze_request(request: Any) -> tuple[Any, str, Optional[str]]:
    meta = metadata(request)
    client = meta.get("broker_client")
    selected = broker_name(
        getattr(request, "preferred_broker", None) or meta.get("execution_broker")
        or meta.get("dispatch_broker") or meta.get("balance_broker")
        or meta.get("broker_name") or broker_from_object(client)
    )
    object_broker = broker_from_object(client)
    if selected and object_broker and selected != object_broker:
        return request, selected, f"execution_route_object_mismatch:selected={selected}:broker_client={object_broker}"
    if not selected:
        return request, "", "execution_route_missing_selected_broker"
    requested = number(getattr(request, "size_usd", 0.0))
    if requested <= 0:
        return request, selected, "canonical_order_notional_nonpositive"
    cash, floor, canonical = venue_cash(client), minimum_notional(selected), requested
    if canonical < floor:
        if cash is None or cash < floor * 1.02:
            return request, selected, f"broker_min_notional_unfunded:broker={selected}:requested={requested:.2f}:minimum={floor:.2f}:venue_cash={cash if cash is not None else 'unknown'}"
        canonical = floor
    if cash is not None and canonical > cash / 1.02:
        return request, selected, f"venue_cash_insufficient:broker={selected}:requested={canonical:.2f}:max_affordable={cash / 1.02:.2f}:venue_cash={cash:.2f}"
    meta.update({
        "execution_broker": selected, "dispatch_broker": selected,
        "balance_broker": selected, "symbol_broker": selected,
        "broker_name": selected, "route_frozen": True,
        "canonical_order_notional_usd": canonical,
        "execution_contract_marker": MARKER,
    })
    if cash is not None:
        meta["venue_cash_usd"] = cash
    updates = {
        "symbol": normalize_symbol(getattr(request, "symbol", "")),
        "preferred_broker": selected, "size_usd": canonical, "metadata": meta,
    }
    if hasattr(request, "notional_usd"):
        updates["notional_usd"] = canonical
    if hasattr(request, "available_balance_usd") and cash is not None:
        updates["available_balance_usd"] = cash
    return replace_request(request, **updates), selected, None
