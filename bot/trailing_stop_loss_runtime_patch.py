"""Trailing stop-loss runtime patch.

Adds a moving stop that follows favorable price movement.  The process keeps
one monitor thread, but every ExecutionEngine is registered and scanned so no
user or brokerage engine can be silently skipped.
"""

from __future__ import annotations

import builtins
import logging
import os
import threading
import time
import weakref
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.trailing_stop_loss")
_ENGINE_PATCHED_ATTR = "__nija_trailing_stop_loss_engine_patch_v2__"
_MONITOR_STARTED_ATTR = "__nija_trailing_stop_loss_started_v2__"
_PROCESS_WORKER_NAME = "nija-trailing-stop"
_PROCESS_STARTED = False
_PROCESS_LOCK = threading.RLock()
_ENGINES: "weakref.WeakSet[Any]" = weakref.WeakSet()
_FALLBACK_REGISTRY_ATTR = "_NIJA_TRAILING_STOP_ENGINE_REGISTRY_V2"


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _live_protection_required() -> bool:
    # Paper/dry-run modes may intentionally disable background protection for tests.
    if _truthy("DRY_RUN_MODE", "false") or _truthy("PAPER_MODE", "false"):
        return _truthy("NIJA_TRAILING_STOP_ENABLED", "true")
    if not _truthy("NIJA_TRAILING_STOP_ENABLED", "true"):
        logger.critical("TRAILING_STOP_DISABLE_OVERRIDDEN live_protection_required=true")
        os.environ["NIJA_TRAILING_STOP_ENABLED"] = "true"
    return True


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return default if out != out else out
    except Exception:
        return default


def _sym(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _quantity(pos: dict[str, Any]) -> float:
    for key in ("quantity", "qty", "size", "amount", "units", "balance"):
        value = _f(pos.get(key), 0.0)
        if value:
            return abs(value)
    return 0.0


def _side(value: Any, pos: dict[str, Any] | None = None) -> str:
    side = str(value or "").strip().lower()
    if side in {"long", "buy", "short", "sell"}:
        return side
    return "long" if _quantity(pos or {}) > 0 else side


def _get(payload: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(payload, dict):
        return default
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return default


def _success(payload: Any) -> bool:
    if isinstance(payload, dict):
        status = str(payload.get("status") or payload.get("state") or "").strip().lower()
        if status in {"filled", "closed", "done", "complete", "completed", "success", "accepted"}:
            return True
        if payload.get("success") is True:
            return True
        if payload.get("order_id") or payload.get("filled_price") or payload.get("filled_size_usd"):
            return status not in {"error", "failed", "rejected", "cancelled", "canceled"}
        return False
    return bool(payload)


def _broker_label(broker: Any) -> str:
    if broker is None:
        return ""
    try:
        btype = getattr(broker, "broker_type", None)
        raw = getattr(btype, "value", None) or btype
        if raw:
            return str(raw).strip().lower()
    except Exception:
        pass
    return type(broker).__name__.replace("Broker", "").strip().lower()


def _trailing_pct() -> float:
    pct = _f(os.environ.get("NIJA_TRAILING_STOP_PCT"), 0.006)
    return max(0.001, min(pct, 0.25))


def _activation_pct() -> float:
    pct = _f(os.environ.get("NIJA_TRAILING_STOP_ACTIVATION_PCT"), 0.003)
    return max(0.0, min(pct, 0.25))


def _market_price(broker: Any, symbol: str) -> float:
    if broker is None:
        return 0.0
    for method in ("get_quote", "get_market_data", "get_ticker", "fetch_ticker"):
        fn = getattr(broker, method, None)
        if not callable(fn):
            continue
        try:
            data = fn(symbol)
            if isinstance(data, dict):
                price = _f(_get(data, "price", "last", "last_price", "mark_price", default=0.0), 0.0)
                if price > 0:
                    return price
                bid = _f(_get(data, "bid", "best_bid", default=0.0), 0.0)
                ask = _f(_get(data, "ask", "best_ask", default=0.0), 0.0)
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2.0
        except TypeError:
            try:
                data = fn(product_ids=[symbol])
                pricebooks = (data or {}).get("pricebooks", [{}]) if isinstance(data, dict) else [{}]
                book = pricebooks[0] if pricebooks else {}
                bid = _f(((book.get("bids") or [{}])[0]).get("price"), 0.0)
                ask = _f(((book.get("asks") or [{}])[0]).get("price"), 0.0)
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2.0
            except Exception:
                continue
        except Exception:
            continue
    return 0.0


def _place_exit_order(broker: Any, pos: dict[str, Any], price: float) -> dict[str, Any]:
    symbol = _sym(pos.get("symbol"))
    qty = _quantity(pos)
    if qty <= 0:
        return {"status": "error", "error": "invalid_position_quantity"}
    close_side = "sell" if _side(pos.get("side"), pos) in {"long", "buy"} else "buy"
    attempts = (
        ("place_market_order", {"symbol": symbol, "side": close_side, "size": qty}),
        ("place_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": qty}),
        ("market_order", {"symbol": symbol, "side": close_side, "quantity": qty}),
        ("execute_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": qty, "reduce_only": True}),
    )
    errors: list[str] = []
    for method, kwargs in attempts:
        fn = getattr(broker, method, None)
        if not callable(fn):
            continue
        try:
            payload = fn(**kwargs)
            if _success(payload):
                out = payload if isinstance(payload, dict) else {"status": "filled", "raw": str(payload)}
                out.setdefault("filled_price", price)
                return out
            errors.append(f"{method}:{payload}")
        except TypeError:
            try:
                payload = fn(symbol, close_side, qty)
                if _success(payload):
                    out = payload if isinstance(payload, dict) else {"status": "filled", "raw": str(payload)}
                    out.setdefault("filled_price", price)
                    return out
                errors.append(f"{method}:{payload}")
            except Exception as exc:
                errors.append(f"{method}:{exc}")
        except Exception as exc:
            errors.append(f"{method}:{exc}")
    return {"status": "error", "error": "; ".join(errors) or "no_supported_trailing_exit_method"}


def _state(engine: Any) -> dict[str, dict[str, float]]:
    st = getattr(engine, "_nija_trailing_stop_state", None)
    if not isinstance(st, dict):
        st = {}
        setattr(engine, "_nija_trailing_stop_state", st)
    return st


def _update_trailing_state(engine: Any, pos: dict[str, Any], price: float) -> tuple[bool, dict[str, float]]:
    symbol = _sym(pos.get("symbol"))
    position_id = str(pos.get("position_id") or symbol)
    key = f"{position_id}:{symbol}"
    entry = _f(_get(pos, "entry_price", "avg_entry_price", "average_price", "avg_price", default=0.0), 0.0)
    side = _side(pos.get("side"), pos)
    pct = _trailing_pct()
    activation = _activation_pct()
    st = _state(engine)
    row = st.get(key)
    if row is None:
        row = {
            "highest": max(entry, price),
            "lowest": min(entry if entry > 0 else price, price),
            "stop": _f(pos.get("stop_loss"), 0.0),
            "activated": 0.0,
        }
        st[key] = row

    if side in {"long", "buy"}:
        row["highest"] = max(_f(row.get("highest")), price)
        if entry > 0 and row["highest"] >= entry * (1.0 + activation):
            row["activated"] = 1.0
        candidate = row["highest"] * (1.0 - pct)
        current_stop = _f(row.get("stop"), 0.0)
        if candidate > current_stop:
            row["stop"] = candidate
            logger.info("TRAILING_STOP_MOVED symbol=%s position_id=%s highest=%.8f stop=%.8f pct=%.4f", symbol, position_id, row["highest"], row["stop"], pct)
        hit = bool(row.get("activated")) and row["stop"] > 0 and price <= row["stop"]
    else:
        row["lowest"] = min(_f(row.get("lowest"), price), price)
        if entry > 0 and row["lowest"] <= entry * (1.0 - activation):
            row["activated"] = 1.0
        candidate = row["lowest"] * (1.0 + pct)
        current_stop = _f(row.get("stop"), 0.0)
        if current_stop <= 0 or candidate < current_stop:
            row["stop"] = candidate
            logger.info("TRAILING_STOP_MOVED symbol=%s position_id=%s lowest=%.8f stop=%.8f pct=%.4f", symbol, position_id, row["lowest"], row["stop"], pct)
        hit = bool(row.get("activated")) and row["stop"] > 0 and price >= row["stop"]
    return hit, row


def _scan_once(engine: Any) -> int:
    if not _live_protection_required():
        return 0
    ledger = getattr(engine, "trade_ledger", None)
    broker = getattr(engine, "broker_client", None) or getattr(engine, "broker", None)
    if ledger is None or broker is None:
        logger.error("TRAILING_STOP_ENGINE_UNPROTECTED missing_ledger_or_broker engine=%s", type(engine).__name__)
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("TRAILING_STOP_SCAN_OPEN_POSITIONS_FAILED engine=%s err=%s", type(engine).__name__, exc)
        return 0
    closed = 0
    active = getattr(engine, "active_exit_orders", None)
    if not isinstance(active, set):
        active = set()
        setattr(engine, "active_exit_orders", active)
    for raw in positions or []:
        pos = raw if isinstance(raw, dict) else dict(getattr(raw, "__dict__", {}) or {})
        symbol = _sym(pos.get("symbol"))
        position_id = str(pos.get("position_id") or symbol)
        if not symbol or symbol in active or position_id in active:
            continue
        price = _market_price(broker, symbol)
        if price <= 0:
            logger.warning("TRAILING_STOP_PRICE_UNAVAILABLE symbol=%s broker=%s", symbol, _broker_label(broker))
            continue
        hit, row = _update_trailing_state(engine, pos, price)
        if not hit:
            continue
        active.add(symbol)
        active.add(position_id)
        logger.critical(
            "TRAILING_STOP_TRIGGERED symbol=%s position_id=%s market=%.8f trailing_stop=%.8f side=%s broker=%s",
            symbol, position_id, price, _f(row.get("stop")), _side(pos.get("side"), pos), _broker_label(broker),
        )
        order = _place_exit_order(broker, pos, price)
        if not _success(order):
            logger.error("TRAILING_STOP_EXIT_FAILED symbol=%s position_id=%s error=%s", symbol, position_id, _get(order, "error", default=order))
            active.discard(symbol)
            active.discard(position_id)
            continue
        fill_price = _f(_get(order, "filled_price", "average_fill_price", "avg_price", "price", default=price), price)
        exit_fee = _f(_get(order, "fee", "commission", "fees", default=0.0), 0.0)
        order_id = str(_get(order, "order_id", "id", "txid", "client_order_id", default="") or "")
        close_fn = getattr(engine, "close_position_with_pnl", None)
        if callable(close_fn):
            pnl = close_fn(position_id=position_id, symbol=symbol, exit_price=fill_price, exit_fee=exit_fee, exit_reason="trailing_stop", order_id=order_id, broker=_broker_label(broker))
        else:
            pnl = ledger.close_position_with_pnl(position_id=position_id, symbol=symbol, exit_price=fill_price, exit_fee=exit_fee, exit_reason="trailing_stop", order_id=order_id, broker=_broker_label(broker))
        if pnl and pnl.get("success"):
            closed += 1
            logger.critical("TRAILING_STOP_CLOSED symbol=%s position_id=%s net_pnl=%.8f pct=%+.4f%%", symbol, position_id, _f(pnl.get("net_profit")), _f(pnl.get("profit_pct")))
        active.discard(symbol)
        active.discard(position_id)
    return closed


def _register_engine(engine: Any) -> None:
    with _PROCESS_LOCK:
        try:
            _ENGINES.add(engine)
        except TypeError:
            registry = getattr(builtins, _FALLBACK_REGISTRY_ATTR, None)
            if not isinstance(registry, list):
                registry = []
                setattr(builtins, _FALLBACK_REGISTRY_ATTR, registry)
            if engine not in registry:
                registry.append(engine)
        setattr(engine, _MONITOR_STARTED_ATTR, True)
    _start_monitor()


def _engine_snapshot() -> list[Any]:
    engines = list(_ENGINES)
    registry = getattr(builtins, _FALLBACK_REGISTRY_ATTR, [])
    if isinstance(registry, list):
        engines.extend(registry)
    unique: list[Any] = []
    seen: set[int] = set()
    for engine in engines:
        if engine is not None and id(engine) not in seen:
            seen.add(id(engine))
            unique.append(engine)
    return unique


def _start_monitor(engine: Any | None = None) -> None:
    global _PROCESS_STARTED
    if engine is not None:
        _register_engine(engine)
        return
    if not _live_protection_required():
        return
    with _PROCESS_LOCK:
        if _PROCESS_STARTED:
            return
        _PROCESS_STARTED = True
    interval = max(2.0, _f(os.environ.get("NIJA_TRAILING_STOP_POLL_SECONDS"), 5.0))

    def loop() -> None:
        logger.warning(
            "TRAILING_STOP_MONITOR_STARTED interval_s=%.2f pct=%.4f activation_pct=%.4f multi_engine=true",
            interval, _trailing_pct(), _activation_pct(),
        )
        while _live_protection_required():
            for registered in _engine_snapshot():
                try:
                    _scan_once(registered)
                except Exception as exc:
                    logger.exception("TRAILING_STOP_SCAN_FAILED engine=%s err=%s", type(registered).__name__, exc)
            time.sleep(interval)

    threading.Thread(target=loop, name=_PROCESS_WORKER_NAME, daemon=True).start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _ENGINE_PATCHED_ATTR, False):
        return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        @wraps(original_init)
        def init_with_trailing_stop(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs)
            _register_engine(self)
        cls.__init__ = init_with_trailing_stop
    cls.scan_trailing_stop_loss_once = _scan_once
    cls.start_trailing_stop_loss_monitor = _register_engine
    setattr(cls, _ENGINE_PATCHED_ATTR, True)
    logger.warning("TRAILING_STOP_ENGINE_PATCHED multi_engine=true qty_aliases=true live_fail_closed=true")
    return True


def install_import_hook() -> None:
    import sys
    _live_protection_required()
    for name in ("bot.execution_engine", "execution_engine"):
        mod = sys.modules.get(name)
        if mod is not None:
            _patch_engine(mod)
    _start_monitor()
    if getattr(builtins, "_NIJA_TRAILING_STOP_IMPORT_HOOK_V2", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        mod = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine"):
                _patch_engine(mod)
        except Exception as exc:
            logger.warning("TRAILING_STOP_PATCH_FAILED module=%s err=%s", name, exc)
        return mod

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_TRAILING_STOP_IMPORT_HOOK_V2", True)
    logger.warning("TRAILING_STOP_IMPORT_HOOK_INSTALLED multi_engine=true")
