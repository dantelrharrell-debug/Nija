"""Trailing take-profit compatibility bridge.

The canonical owner for stop-loss, fixed take-profit, and profit-lock exits is
``auto_exit_sl_tp_runtime_patch``.  When that monitor is enabled this module
registers its compatibility methods but does not start a competing worker.
When the canonical monitor is explicitly disabled, this module provides a
multi-engine fallback worker so every platform and user account remains
protected.
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

logger = logging.getLogger("nija.trailing_take_profit")
_MARKER = "20260718-trailing-tp-canonical-owner-v2"
_PATCHED = "__nija_trailing_tp_engine_patch_v2__"
_STARTED = "__nija_trailing_tp_started_v2__"
_PROCESS_WORKER_NAME = "nija-trailing-take-profit"
_PROCESS_STARTED = False
_PROCESS_LOCK = threading.RLock()
_ENGINES: "weakref.WeakSet[Any]" = weakref.WeakSet()


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {
        "1", "true", "yes", "on", "enabled",
    }


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _sym(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _side(value: Any) -> str:
    return str(value or "").strip().lower()


def _get(payload: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(payload, dict):
        return default
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return default


def _success(payload: Any) -> bool:
    if isinstance(payload, dict):
        state = str(payload.get("status") or payload.get("state") or "").lower()
        if state in {"filled", "closed", "done", "complete", "completed", "success", "accepted"}:
            return True
        if payload.get("success") is True:
            return True
        if payload.get("order_id") or payload.get("filled_price") or payload.get("filled_size_usd"):
            return state not in {"error", "failed", "rejected", "cancelled", "canceled"}
        return False
    return bool(payload)


def _broker_label(broker: Any) -> str:
    try:
        broker_type = getattr(broker, "broker_type", None)
        raw = getattr(broker_type, "value", None) or broker_type
        if raw:
            return str(raw).lower()
    except Exception:
        pass
    return type(broker).__name__.replace("Broker", "").lower() if broker else ""


def _activation() -> float:
    return max(0.0005, min(_f(os.environ.get("NIJA_TRAILING_TP_ACTIVATION_PCT"), 0.008), 0.50))


def _callback() -> float:
    return max(0.0005, min(_f(os.environ.get("NIJA_TRAILING_TP_CALLBACK_PCT"), 0.0035), 0.25))


def _price(broker: Any, symbol: str) -> float:
    for method_name in ("get_quote", "get_market_data", "get_ticker", "fetch_ticker"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            quote = method(symbol)
            if isinstance(quote, dict):
                price = _f(_get(quote, "price", "last", "last_price", "mark_price", default=0.0))
                if price > 0:
                    return price
                bid = _f(_get(quote, "bid", "best_bid", default=0.0))
                ask = _f(_get(quote, "ask", "best_ask", default=0.0))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2.0
        except Exception:
            continue
    return 0.0


def _state(engine: Any) -> dict[str, dict[str, Any]]:
    state = getattr(engine, "_nija_trailing_tp_state", None)
    if not isinstance(state, dict):
        state = {}
        setattr(engine, "_nija_trailing_tp_state", state)
    return state


def _key(position: dict[str, Any]) -> str:
    symbol = _sym(position.get("symbol"))
    account = str(_get(position, "account_id", "user_id", "account", default="platform") or "platform")
    return f"{account}:{position.get('position_id') or symbol}:{symbol}"


def _armed(position: dict[str, Any], price: float) -> bool:
    entry = _f(_get(position, "entry_price", "avg_entry_price", "cost_basis_price", default=0.0))
    if entry <= 0:
        return False
    if _side(position.get("side")) in {"short", "sell"}:
        return price <= entry * (1 - _activation())
    return price >= entry * (1 + _activation())


def _track(position: dict[str, Any], row: dict[str, Any], price: float) -> tuple[bool, float, float]:
    if _side(position.get("side")) in {"short", "sell"}:
        best = min(_f(row.get("best"), price), price)
        row["best"] = best
        trigger = best * (1 + _callback())
        return price >= trigger, best, trigger
    best = max(_f(row.get("best"), price), price)
    row["best"] = best
    trigger = best * (1 - _callback())
    return price <= trigger, best, trigger


def _quantity(position: dict[str, Any]) -> float:
    return abs(_f(_get(position, "quantity", "qty", "size", "amount", "units", "balance", default=0.0)))


def _exit(broker: Any, position: dict[str, Any], price: float) -> dict[str, Any]:
    symbol = _sym(position.get("symbol"))
    quantity = _quantity(position)
    if quantity <= 0:
        return {"status": "error", "error": "invalid_position_quantity"}
    close_side = "buy" if _side(position.get("side")) in {"short", "sell"} else "sell"
    calls = (
        ("place_market_order", {"symbol": symbol, "side": close_side, "size": quantity}),
        ("place_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": quantity}),
        ("market_order", {"symbol": symbol, "side": close_side, "quantity": quantity}),
        ("execute_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": quantity, "reduce_only": True}),
    )
    errors: list[str] = []
    for name, kwargs in calls:
        method = getattr(broker, name, None)
        if not callable(method):
            continue
        try:
            output = method(**kwargs)
            if _success(output):
                result = output if isinstance(output, dict) else {"status": "filled", "raw": str(output)}
                result.setdefault("filled_price", price)
                return result
            errors.append(f"{name}:{_get(output, 'error', default=output)}")
        except TypeError:
            try:
                output = method(symbol, close_side, quantity)
                if _success(output):
                    result = output if isinstance(output, dict) else {"status": "filled", "raw": str(output)}
                    result.setdefault("filled_price", price)
                    return result
            except Exception as exc:
                errors.append(f"{name}:{type(exc).__name__}:{exc}")
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
    return {"status": "error", "error": "trailing_tp_exit_submission_failed", "details": errors[-4:]}


def _scan_once(engine: Any) -> int:
    if not _truthy("NIJA_TRAILING_TP_ENABLED", "true"):
        return 0
    ledger = getattr(engine, "trade_ledger", None)
    broker = getattr(engine, "broker_client", None) or getattr(engine, "broker", None)
    if ledger is None or broker is None:
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("TRAILING_TP_OPEN_POSITIONS_FAILED marker=%s err=%s", _MARKER, exc)
        return 0
    active = getattr(engine, "active_exit_orders", None)
    if not isinstance(active, set):
        active = set()
        setattr(engine, "active_exit_orders", active)
    state = _state(engine)
    live: set[str] = set()
    closed = 0
    for raw in positions or []:
        position = raw if isinstance(raw, dict) else dict(getattr(raw, "__dict__", {}) or {})
        symbol = _sym(position.get("symbol"))
        pid = str(position.get("position_id") or symbol)
        key = _key(position)
        live.add(key)
        if not symbol or symbol in active or pid in active:
            continue
        market = _price(broker, symbol)
        if market <= 0:
            continue
        row = state.setdefault(key, {"armed": False, "best": market})
        if not row.get("armed"):
            if _armed(position, market):
                row["armed"] = True
                row["best"] = market
                logger.critical("TRAILING_TP_ARMED marker=%s symbol=%s position_id=%s market=%.8f", _MARKER, symbol, pid, market)
            continue
        hit, best, trigger = _track(position, row, market)
        if not hit:
            continue
        active.add(symbol)
        active.add(pid)
        logger.critical("TRAILING_TP_TRIGGERED marker=%s symbol=%s position_id=%s market=%.8f best=%.8f trigger=%.8f", _MARKER, symbol, pid, market, best, trigger)
        order = _exit(broker, position, market)
        if not _success(order):
            logger.error("TRAILING_TP_EXIT_FAILED marker=%s symbol=%s position_id=%s error=%s", _MARKER, symbol, pid, order)
            active.discard(symbol)
            active.discard(pid)
            continue
        fill = _f(_get(order, "filled_price", "average_fill_price", "avg_price", "price", default=market), market)
        fee = _f(_get(order, "fee", "commission", "fees", default=0.0))
        order_id = str(_get(order, "order_id", "id", "txid", "client_order_id", default="") or "")
        close = getattr(engine, "close_position_with_pnl", None)
        if callable(close):
            pnl = close(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason="trailing_take_profit", order_id=order_id, broker=_broker_label(broker))
        else:
            pnl = ledger.close_position_with_pnl(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason="trailing_take_profit", order_id=order_id, broker=_broker_label(broker))
        if pnl and pnl.get("success"):
            closed += 1
            state.pop(key, None)
            logger.critical("TRAILING_TP_CLOSED marker=%s symbol=%s position_id=%s net_pnl=%.8f pct=%+.4f%%", _MARKER, symbol, pid, _f(pnl.get("net_profit")), _f(pnl.get("profit_pct")))
        active.discard(symbol)
        active.discard(pid)
    for key in list(state):
        if key not in live:
            state.pop(key, None)
    return closed


def _register_engine(engine: Any) -> None:
    with _PROCESS_LOCK:
        try:
            _ENGINES.add(engine)
        except TypeError:
            registry = getattr(builtins, "_NIJA_TRAILING_TP_ENGINE_REGISTRY", None)
            if not isinstance(registry, list):
                registry = []
                setattr(builtins, "_NIJA_TRAILING_TP_ENGINE_REGISTRY", registry)
            if engine not in registry:
                registry.append(engine)
        setattr(engine, _STARTED, True)
    _start_monitor()


def _engine_snapshot() -> list[Any]:
    engines = list(_ENGINES)
    registry = getattr(builtins, "_NIJA_TRAILING_TP_ENGINE_REGISTRY", [])
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
    if _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true"):
        os.environ["NIJA_TRAILING_TP_CANONICAL_OWNER"] = "auto_exit_sl_tp_runtime_patch"
        logger.info("TRAILING_TP_WORKER_DELEGATED marker=%s owner=auto_exit_sl_tp_runtime_patch", _MARKER)
        return
    if not _truthy("NIJA_TRAILING_TP_ENABLED", "true"):
        return
    with _PROCESS_LOCK:
        if _PROCESS_STARTED:
            return
        _PROCESS_STARTED = True
    interval = max(2.0, _f(os.environ.get("NIJA_TRAILING_TP_POLL_SECONDS"), 3.0))

    def loop() -> None:
        logger.warning("TRAILING_TP_MONITOR_STARTED marker=%s interval_s=%.2f multi_engine=true fallback_owner=true", _MARKER, interval)
        while _truthy("NIJA_TRAILING_TP_ENABLED", "true") and not _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true"):
            for engine in _engine_snapshot():
                try:
                    _scan_once(engine)
                except Exception as exc:
                    logger.exception("TRAILING_TP_SCAN_FAILED marker=%s engine=%s err=%s", _MARKER, type(engine).__name__, exc)
            time.sleep(interval)

    threading.Thread(target=loop, name=_PROCESS_WORKER_NAME, daemon=True).start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _PATCHED, False):
        return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        @wraps(original_init)
        def init_with_trailing_tp(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs)
            _register_engine(self)
        cls.__init__ = init_with_trailing_tp
    cls.scan_trailing_take_profit_once = _scan_once
    cls.start_trailing_take_profit_monitor = _register_engine
    setattr(cls, _PATCHED, True)
    logger.warning("TRAILING_TP_ENGINE_PATCHED marker=%s multi_engine=true canonical_owner_aware=true", _MARKER)
    return True


def install_import_hook() -> None:
    import sys
    for name in ("bot.execution_engine", "execution_engine"):
        module = sys.modules.get(name)
        if module is not None:
            _patch_engine(module)
    _start_monitor()
    if getattr(builtins, "_NIJA_TRAILING_TP_IMPORT_HOOK_V2", False):
        return
    original_import = builtins.__import__

    def hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine"):
                _patch_engine(module)
        except Exception as exc:
            logger.warning("TRAILING_TP_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = hook
    setattr(builtins, "_NIJA_TRAILING_TP_IMPORT_HOOK_V2", True)
    logger.warning("TRAILING_TP_IMPORT_HOOK_INSTALLED marker=%s", _MARKER)


def install() -> None:
    install_import_hook()


__all__ = ["install", "install_import_hook", "_scan_once", "_register_engine", "_engine_snapshot"]
