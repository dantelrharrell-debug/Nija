"""Automatic SL/TP exit monitor and protection-stack bridge.

The monitor is process-wide but engine-aware: every ExecutionEngine instance is
registered and scanned. This prevents the first-created user engine from
silently monopolising exit monitoring while platform positions remain
unprotected.
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

logger = logging.getLogger("nija.auto_exit_sl_tp")
_MARKER = "20260716-auto-exit-v2"
_PATCHED = "__nija_auto_exit_sl_tp_engine_patch_v2__"
_STARTED = "__nija_auto_exit_sl_tp_started_v2__"
_BRIDGES = {
    "trail_sl": "_NIJA_TRAILING_STOP_LOSS_BRIDGE_INSTALLED",
    "breakeven": "_NIJA_BREAKEVEN_STOP_LOSS_BRIDGE_INSTALLED",
    "combo": "_NIJA_COMBO_BE_TRAILING_BRIDGE_INSTALLED",
    "trail_tp": "_NIJA_TRAILING_TP_BRIDGE_INSTALLED",
    "combined": "_NIJA_COMBINED_TRAILING_TP_SL_BRIDGE_INSTALLED",
}

_PROCESS_WORKER_NAME = "nija-auto-exit-sl-tp"
_PROCESS_STARTED = False
_PROCESS_LOCK = threading.RLock()
_ENGINES: "weakref.WeakSet[Any]" = weakref.WeakSet()
_HIGH_WATER: dict[str, float] = {}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _f(v: Any, d: float = 0.0) -> float:
    try:
        x = float(v)
        return d if x != x else x
    except Exception:
        return d


def _sym(v: Any) -> str:
    return str(v or "").strip().upper().replace("/", "-").replace("_", "-")


def _side(v: Any, pos: dict[str, Any] | None = None) -> str:
    side = str(v or "").strip().lower()
    if side in {"long", "buy", "short", "sell"}:
        return side
    # Spot holdings with positive quantity are long even when legacy rows omit side.
    return "long" if _quantity(pos or {}) > 0 else side


def _get(d: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for key in keys:
        if key in d and d.get(key) is not None:
            return d.get(key)
    return default


def _quantity(pos: dict[str, Any]) -> float:
    return abs(_f(_get(pos, "quantity", "qty", "size", "amount", "units", "balance", default=0.0)))


def _entry_price(pos: dict[str, Any]) -> float:
    return _f(_get(pos, "entry_price", "avg_entry_price", "average_price", "cost_basis_price", "avg_price", default=0.0))


def _ok(payload: Any) -> bool:
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
            return str(raw).strip().lower()
    except Exception:
        pass
    return type(broker).__name__.replace("Broker", "").strip().lower() if broker else ""


def _price(broker: Any, symbol: str) -> float:
    if broker is None:
        return 0.0
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
        except TypeError:
            try:
                quote = method(product_ids=[symbol])
                books = (quote or {}).get("pricebooks", [{}]) if isinstance(quote, dict) else [{}]
                book = books[0] if books else {}
                bid = _f(((book.get("bids") or [{}])[0]).get("price"))
                ask = _f(((book.get("asks") or [{}])[0]).get("price"))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2.0
            except Exception:
                pass
        except Exception:
            pass
    return 0.0


def _position_key(pos: dict[str, Any]) -> str:
    account = str(_get(pos, "account_id", "user_id", "account", default="platform") or "platform")
    return f"{account}:{_sym(pos.get('symbol'))}:{str(pos.get('position_id') or '')}"


def _effective_stop(pos: dict[str, Any], price: float) -> tuple[float, str]:
    explicit = _f(pos.get("stop_loss"))
    if explicit > 0:
        return explicit, "stored_stop_loss"
    entry = _entry_price(pos)
    qty = _quantity(pos)
    if entry <= 0 or qty <= 0:
        return 0.0, "missing_verified_entry_or_quantity"
    pct = max(0.001, _f(os.environ.get("NIJA_HARD_STOP_LOSS_PCT"), _f(os.environ.get("NIJA_GLOBAL_STOP_LOSS_PCT"), 0.015)))
    max_loss_usd = max(0.01, _f(os.environ.get("NIJA_MAX_POSITION_LOSS_USD"), 2.0))
    pct_distance = entry * pct
    dollar_distance = max_loss_usd / qty
    distance = min(pct_distance, dollar_distance)
    long_side = _side(pos.get("side"), pos) in {"long", "buy"}
    stop = entry - distance if long_side else entry + distance
    return max(0.0, stop), "synthesized_loss_cap"


def _trigger(pos: dict[str, Any], price: float) -> tuple[bool, str, float]:
    side = _side(pos.get("side"), pos)
    stop, stop_source = _effective_stop(pos, price)
    targets = [
        ("take_profit_1", _f(pos.get("take_profit_1"))),
        ("take_profit_2", _f(pos.get("take_profit_2"))),
        ("take_profit_3", _f(pos.get("take_profit_3"))),
    ]
    key = _position_key(pos)
    entry = _entry_price(pos)
    previous_high = _HIGH_WATER.get(key, entry if entry > 0 else price)
    if side in {"long", "buy"}:
        high = max(previous_high, price)
        _HIGH_WATER[key] = high
        if stop > 0 and price <= stop:
            return True, f"stop_loss:{stop_source}", stop
        for name, target in targets:
            if target > 0 and price >= target:
                return True, name, target
        activation = max(0.0, _f(os.environ.get("NIJA_PROFIT_LOCK_ACTIVATION_PCT"), 0.008))
        callback = max(0.0005, _f(os.environ.get("NIJA_PROFIT_LOCK_CALLBACK_PCT"), 0.0035))
        if entry > 0 and high >= entry * (1 + activation) and price <= high * (1 - callback):
            return True, "profit_lock_trailing_exit", high * (1 - callback)
    else:
        low = min(previous_high, price)
        _HIGH_WATER[key] = low
        if stop > 0 and price >= stop:
            return True, f"stop_loss:{stop_source}", stop
        for name, target in targets:
            if target > 0 and price <= target:
                return True, name, target
    return False, "", 0.0


def _exit_order(broker: Any, pos: dict[str, Any], price: float) -> dict[str, Any]:
    symbol = _sym(pos.get("symbol"))
    qty = _quantity(pos)
    if qty <= 0:
        return {"status": "error", "error": "invalid_position_quantity", "quantity_keys_checked": "quantity,qty,size,amount,units,balance"}
    close_side = "sell" if _side(pos.get("side"), pos) in {"long", "buy"} else "buy"
    calls = (
        ("place_market_order", {"symbol": symbol, "side": close_side, "size": qty}),
        ("place_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": qty}),
        ("market_order", {"symbol": symbol, "side": close_side, "quantity": qty}),
        ("execute_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": qty, "reduce_only": True}),
    )
    errors: list[str] = []
    for name, kwargs in calls:
        method = getattr(broker, name, None)
        if not callable(method):
            continue
        try:
            output = method(**kwargs)
            if _ok(output):
                result = output if isinstance(output, dict) else {"status": "filled", "raw": str(output)}
                result.setdefault("filled_price", price)
                return result
            errors.append(f"{name}:{_get(output, 'error', default=output)}")
        except TypeError:
            try:
                output = method(symbol, close_side, qty)
                if _ok(output):
                    result = output if isinstance(output, dict) else {"status": "filled", "raw": str(output)}
                    result.setdefault("filled_price", price)
                    return result
                errors.append(f"{name}:positional_rejected")
            except Exception as exc:
                errors.append(f"{name}:{type(exc).__name__}:{exc}")
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
    return {"status": "error", "error": "exit_submission_failed", "details": errors[-4:]}


def _scan_once(engine: Any) -> int:
    ledger = getattr(engine, "trade_ledger", None)
    broker = getattr(engine, "broker_client", None) or getattr(engine, "broker", None)
    if ledger is None or broker is None:
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("AUTO_EXIT_SCAN_OPEN_POSITIONS_FAILED marker=%s err=%s", _MARKER, exc)
        return 0
    active = getattr(engine, "active_exit_orders", None)
    if not isinstance(active, set):
        active = set()
        setattr(engine, "active_exit_orders", active)
    closed = 0
    for raw in positions or []:
        pos = raw if isinstance(raw, dict) else dict(getattr(raw, "__dict__", {}) or {})
        symbol = _sym(pos.get("symbol"))
        pid = str(pos.get("position_id") or symbol)
        if not symbol or symbol in active or pid in active:
            continue
        market = _price(broker, symbol)
        if market <= 0:
            logger.warning("AUTO_EXIT_PRICE_UNAVAILABLE marker=%s symbol=%s broker=%s", _MARKER, symbol, _broker_label(broker))
            continue
        hit, reason, target = _trigger(pos, market)
        entry = _entry_price(pos)
        qty = _quantity(pos)
        unrealized = (market - entry) * qty if _side(pos.get("side"), pos) in {"long", "buy"} else (entry - market) * qty
        if not hit:
            continue
        active.add(symbol)
        active.add(pid)
        logger.critical(
            "AUTO_EXIT_TRIGGERED marker=%s symbol=%s position_id=%s reason=%s target=%.8f market=%.8f entry=%.8f qty=%.8f unrealized=$%+.2f side=%s",
            _MARKER, symbol, pid, reason, target, market, entry, qty, unrealized, _side(pos.get("side"), pos),
        )
        order = _exit_order(broker, pos, market)
        if not _ok(order):
            logger.error("AUTO_EXIT_ORDER_FAILED marker=%s symbol=%s position_id=%s reason=%s error=%s", _MARKER, symbol, pid, reason, order)
            active.discard(symbol)
            active.discard(pid)
            continue
        fill = _f(_get(order, "filled_price", "average_fill_price", "avg_price", "price", default=market), market)
        fee = _f(_get(order, "fee", "commission", "fees", default=0.0))
        oid = str(_get(order, "order_id", "id", "txid", "client_order_id", default="") or "")
        close_fn = getattr(engine, "close_position_with_pnl", None)
        if callable(close_fn):
            pnl = close_fn(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason=reason, order_id=oid, broker=_broker_label(broker))
        else:
            pnl = ledger.close_position_with_pnl(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason=reason, order_id=oid, broker=_broker_label(broker))
        if pnl and pnl.get("success"):
            closed += 1
            _HIGH_WATER.pop(_position_key(pos), None)
            logger.critical("AUTO_EXIT_CLOSED marker=%s symbol=%s position_id=%s net_pnl=%.8f pct=%+.4f%% reason=%s", _MARKER, symbol, pid, _f(pnl.get("net_profit")), _f(pnl.get("profit_pct")), reason)
        active.discard(symbol)
        active.discard(pid)
    return closed


def _register_engine(engine: Any) -> None:
    with _PROCESS_LOCK:
        try:
            _ENGINES.add(engine)
        except TypeError:
            # Some legacy engine classes are not weak-referenceable.
            registry = getattr(builtins, "_NIJA_AUTO_EXIT_ENGINE_REGISTRY", None)
            if not isinstance(registry, list):
                registry = []
                setattr(builtins, "_NIJA_AUTO_EXIT_ENGINE_REGISTRY", registry)
            if engine not in registry:
                registry.append(engine)
        setattr(engine, _STARTED, True)
    _start_monitor()


def _engine_snapshot() -> list[Any]:
    engines = list(_ENGINES)
    registry = getattr(builtins, "_NIJA_AUTO_EXIT_ENGINE_REGISTRY", [])
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
    if not _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true"):
        return
    with _PROCESS_LOCK:
        if _PROCESS_STARTED:
            return
        _PROCESS_STARTED = True
    interval = max(1.0, _f(os.environ.get("NIJA_AUTO_EXIT_POLL_SECONDS"), 3.0))

    def loop() -> None:
        logger.warning("AUTO_EXIT_SL_TP_MONITOR_STARTED marker=%s interval_s=%.2f multi_engine=true", _MARKER, interval)
        while _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true"):
            engines = _engine_snapshot()
            for registered in engines:
                try:
                    _scan_once(registered)
                except Exception as exc:
                    logger.exception("AUTO_EXIT_SL_TP_SCAN_FAILED marker=%s engine=%s err=%s", _MARKER, type(registered).__name__, exc)
            time.sleep(interval)

    threading.Thread(target=loop, name=_PROCESS_WORKER_NAME, daemon=True).start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _PATCHED, False):
        return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        @wraps(original_init)
        def init_with_auto_exit(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs)
            _register_engine(self)
        cls.__init__ = init_with_auto_exit
    cls.scan_stop_loss_take_profit_once = _scan_once
    cls.start_stop_loss_take_profit_monitor = _register_engine
    setattr(cls, _PATCHED, True)
    logger.warning("AUTO_EXIT_SL_TP_ENGINE_PATCHED marker=%s multi_engine=true qty_aliases=true synthesized_loss_cap=true", _MARKER)
    return True


def _install_bridge(attr: str, envs: dict[str, str], modname: str, log_prefix: str) -> None:
    if getattr(builtins, attr, False):
        return
    for key, value in envs.items():
        os.environ.setdefault(key, value)
    try:
        module = __import__(f"bot.{modname}", fromlist=["install_import_hook"])
    except Exception:
        try:
            module = __import__(modname, fromlist=["install_import_hook"])
        except Exception as exc:
            logger.warning("%s_BRIDGE_IMPORT_FAILED err=%s", log_prefix, exc)
            return
    try:
        module.install_import_hook()
        setattr(builtins, attr, True)
        logger.warning("%s_BRIDGE_INSTALLED", log_prefix)
    except Exception as exc:
        logger.warning("%s_BRIDGE_INSTALL_FAILED err=%s", log_prefix, exc)


def _install_all_bridges() -> None:
    _install_bridge(_BRIDGES["trail_sl"], {"NIJA_TRAILING_STOP_ENABLED":"true", "NIJA_TRAILING_STOP_POLL_SECONDS":"3", "NIJA_TRAILING_STOP_PCT":"0.0035", "NIJA_TRAILING_STOP_ACTIVATION_PCT":"0.008"}, "trailing_stop_loss_runtime_patch", "TRAILING_STOP")
    _install_bridge(_BRIDGES["breakeven"], {"NIJA_BREAKEVEN_STOP_ENABLED":"true", "NIJA_BREAKEVEN_STOP_POLL_SECONDS":"3", "NIJA_BREAKEVEN_PROFIT_THRESHOLD_PCT":"0.008", "NIJA_BREAKEVEN_STOP_OFFSET_PCT":"0.001"}, "breakeven_stop_loss_runtime_patch", "BREAKEVEN_STOP")
    _install_bridge(_BRIDGES["combo"], {"NIJA_COMBO_BE_TRAILING_ENABLED":"true", "NIJA_COMBO_BE_TRAILING_POLL_SECONDS":"3", "NIJA_COMBO_BREAKEVEN_THRESHOLD_PCT":"0.008", "NIJA_COMBO_BREAKEVEN_OFFSET_PCT":"0.001", "NIJA_COMBO_TRAILING_SWITCH_PCT":"0.0125", "NIJA_COMBO_TRAILING_STOP_PCT":"0.0035"}, "combo_breakeven_trailing_runtime_patch", "COMBO_BE_TRAILING")
    _install_bridge(_BRIDGES["trail_tp"], {"NIJA_TRAILING_TP_ENABLED":"true", "NIJA_TRAILING_TP_POLL_SECONDS":"3", "NIJA_TRAILING_TP_ACTIVATION_PCT":"0.008", "NIJA_TRAILING_TP_CALLBACK_PCT":"0.0035"}, "trailing_take_profit_runtime_patch", "TRAILING_TP")
    _install_bridge(_BRIDGES["combined"], {"NIJA_COMBINED_TRAILING_TP_SL_ENABLED":"true", "NIJA_COMBINED_TRAILING_POLL_SECONDS":"3", "NIJA_COMBINED_TRAILING_SL_ACTIVATION_PCT":"0.008", "NIJA_COMBINED_TRAILING_SL_DISTANCE_PCT":"0.0035", "NIJA_COMBINED_TRAILING_TP_ACTIVATION_PCT":"0.008", "NIJA_COMBINED_TRAILING_TP_CALLBACK_PCT":"0.0035"}, "combined_trailing_tp_sl_runtime_patch", "COMBINED_TRAILING")


def install_import_hook() -> None:
    import sys
    os.environ.setdefault("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true")
    os.environ.setdefault("NIJA_AUTO_EXIT_POLL_SECONDS", "3")
    os.environ.setdefault("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    os.environ.setdefault("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    os.environ.setdefault("NIJA_PROFIT_LOCK_ACTIVATION_PCT", "0.008")
    os.environ.setdefault("NIJA_PROFIT_LOCK_CALLBACK_PCT", "0.0035")
    _install_all_bridges()
    for name in ("bot.execution_engine", "execution_engine"):
        module = sys.modules.get(name)
        if module is not None:
            _patch_engine(module)
    _start_monitor()
    if getattr(builtins, "_NIJA_AUTO_EXIT_SL_TP_IMPORT_HOOK_V2", False):
        return
    original_import = builtins.__import__

    def hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine"):
                _patch_engine(module)
        except Exception as exc:
            logger.warning("AUTO_EXIT_SL_TP_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = hook
    setattr(builtins, "_NIJA_AUTO_EXIT_SL_TP_IMPORT_HOOK_V2", True)
    logger.warning("AUTO_EXIT_SL_TP_IMPORT_HOOK_INSTALLED marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
