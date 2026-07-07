"""Automatic SL/TP exit monitor and protection-stack bridge."""
from __future__ import annotations

import builtins, logging, os, threading, time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.auto_exit_sl_tp")
_PATCHED = "__nija_auto_exit_sl_tp_engine_patch__"
_STARTED = "__nija_auto_exit_sl_tp_started__"
_BRIDGES = {
    "trail_sl": "_NIJA_TRAILING_STOP_LOSS_BRIDGE_INSTALLED",
    "breakeven": "_NIJA_BREAKEVEN_STOP_LOSS_BRIDGE_INSTALLED",
    "combo": "_NIJA_COMBO_BE_TRAILING_BRIDGE_INSTALLED",
    "trail_tp": "_NIJA_TRAILING_TP_BRIDGE_INSTALLED",
}


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


def _side(v: Any) -> str:
    return str(v or "").strip().lower()


def _get(d: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d.get(k) is not None:
            return d.get(k)
    return default


def _ok(payload: Any) -> bool:
    if isinstance(payload, dict):
        s = str(payload.get("status") or payload.get("state") or "").lower()
        if s in {"filled", "closed", "done", "complete", "completed", "success", "accepted"}:
            return True
        if payload.get("success") is True:
            return True
        if payload.get("order_id") or payload.get("filled_price") or payload.get("filled_size_usd"):
            return s not in {"error", "failed", "rejected", "cancelled", "canceled"}
        return False
    return bool(payload)


def _broker_label(broker: Any) -> str:
    try:
        bt = getattr(broker, "broker_type", None)
        raw = getattr(bt, "value", None) or bt
        if raw:
            return str(raw).strip().lower()
    except Exception:
        pass
    return type(broker).__name__.replace("Broker", "").strip().lower() if broker else ""


def _price(broker: Any, symbol: str) -> float:
    if broker is None:
        return 0.0
    for m in ("get_quote", "get_market_data", "get_ticker", "fetch_ticker"):
        fn = getattr(broker, m, None)
        if not callable(fn):
            continue
        try:
            q = fn(symbol)
            if isinstance(q, dict):
                p = _f(_get(q, "price", "last", "last_price", "mark_price", default=0.0))
                if p > 0:
                    return p
                bid = _f(_get(q, "bid", "best_bid", default=0.0))
                ask = _f(_get(q, "ask", "best_ask", default=0.0))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2.0
        except TypeError:
            try:
                q = fn(product_ids=[symbol])
                books = (q or {}).get("pricebooks", [{}]) if isinstance(q, dict) else [{}]
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


def _trigger(pos: dict[str, Any], price: float) -> tuple[bool, str, float]:
    s = _side(pos.get("side")); stop = _f(pos.get("stop_loss"))
    tps = [("take_profit_1", _f(pos.get("take_profit_1"))), ("take_profit_2", _f(pos.get("take_profit_2"))), ("take_profit_3", _f(pos.get("take_profit_3")))]
    if s in {"long", "buy"}:
        if stop > 0 and price <= stop:
            return True, "stop_loss", stop
        for name, target in tps:
            if target > 0 and price >= target:
                return True, name, target
    else:
        if stop > 0 and price >= stop:
            return True, "stop_loss", stop
        for name, target in tps:
            if target > 0 and price <= target:
                return True, name, target
    return False, "", 0.0


def _exit_order(broker: Any, pos: dict[str, Any], price: float) -> dict[str, Any]:
    symbol = _sym(pos.get("symbol")); qty = _f(pos.get("quantity"))
    if qty <= 0:
        return {"status": "error", "error": "invalid_position_quantity"}
    close_side = "sell" if _side(pos.get("side")) in {"long", "buy"} else "buy"
    for name, kwargs in (
        ("place_market_order", {"symbol": symbol, "side": close_side, "size": qty}),
        ("place_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": qty}),
        ("market_order", {"symbol": symbol, "side": close_side, "quantity": qty}),
    ):
        fn = getattr(broker, name, None)
        if not callable(fn):
            continue
        try:
            out = fn(**kwargs)
            if _ok(out):
                out = out if isinstance(out, dict) else {"status": "filled", "raw": str(out)}
                out.setdefault("filled_price", price)
                return out
        except TypeError:
            try:
                out = fn(symbol, close_side, qty)
                if _ok(out):
                    out = out if isinstance(out, dict) else {"status": "filled", "raw": str(out)}
                    out.setdefault("filled_price", price)
                    return out
            except Exception:
                pass
        except Exception:
            pass
    return {"status": "error", "error": "no_supported_exit_order_method"}


def _scan_once(engine: Any) -> int:
    ledger = getattr(engine, "trade_ledger", None); broker = getattr(engine, "broker_client", None)
    if ledger is None or broker is None:
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("AUTO_EXIT_SCAN_OPEN_POSITIONS_FAILED err=%s", exc); return 0
    active = getattr(engine, "active_exit_orders", set()); closed = 0
    for pos in positions:
        symbol = _sym(pos.get("symbol")); pid = str(pos.get("position_id") or symbol)
        if not symbol or symbol in active or pid in active:
            continue
        p = _price(broker, symbol)
        if p <= 0:
            continue
        hit, reason, target = _trigger(pos, p)
        if not hit:
            continue
        try: active.add(symbol); active.add(pid)
        except Exception: pass
        logger.critical("AUTO_EXIT_TRIGGERED symbol=%s position_id=%s reason=%s target=%.8f market=%.8f side=%s", symbol, pid, reason, target, p, pos.get("side"))
        order = _exit_order(broker, pos, p)
        if not _ok(order):
            logger.error("AUTO_EXIT_ORDER_FAILED symbol=%s position_id=%s reason=%s error=%s", symbol, pid, reason, _get(order, "error", default=order))
            try: active.discard(symbol); active.discard(pid)
            except Exception: pass
            continue
        fill = _f(_get(order, "filled_price", "average_fill_price", "avg_price", "price", default=p), p)
        fee = _f(_get(order, "fee", "commission", "fees", default=0.0))
        oid = str(_get(order, "order_id", "id", "txid", "client_order_id", default="") or "")
        close_fn = getattr(engine, "close_position_with_pnl", None)
        pnl = close_fn(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason=reason, order_id=oid, broker=_broker_label(broker)) if callable(close_fn) else ledger.close_position_with_pnl(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason=reason, order_id=oid, broker=_broker_label(broker))
        if pnl and pnl.get("success"):
            closed += 1
            logger.critical("AUTO_EXIT_CLOSED symbol=%s position_id=%s net_pnl=%.8f pct=%+.4f%% reason=%s", symbol, pid, _f(pnl.get("net_profit")), _f(pnl.get("profit_pct")), reason)
        try: active.discard(symbol); active.discard(pid)
        except Exception: pass
    return closed


def _start_monitor(engine: Any) -> None:
    if not _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true") or getattr(engine, _STARTED, False):
        return
    interval = max(2.0, _f(os.environ.get("NIJA_AUTO_EXIT_POLL_SECONDS"), 5.0))
    setattr(engine, _STARTED, True)
    def loop() -> None:
        logger.warning("AUTO_EXIT_SL_TP_MONITOR_STARTED interval_s=%.2f", interval)
        while _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true"):
            try: _scan_once(engine)
            except Exception as exc: logger.warning("AUTO_EXIT_SL_TP_SCAN_FAILED err=%s", exc)
            time.sleep(interval)
    threading.Thread(target=loop, name="nija-auto-exit-sl-tp", daemon=True).start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _PATCHED, False):
        return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        @wraps(original_init)
        def init_with_auto_exit(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs); _start_monitor(self)
        cls.__init__ = init_with_auto_exit
    cls.scan_stop_loss_take_profit_once = _scan_once
    cls.start_stop_loss_take_profit_monitor = _start_monitor
    setattr(cls, _PATCHED, True)
    logger.warning("AUTO_EXIT_SL_TP_ENGINE_PATCHED")
    return True


def _install_bridge(name: str, attr: str, envs: dict[str, str], modname: str, log_prefix: str) -> None:
    if getattr(builtins, attr, False):
        return
    for k, v in envs.items():
        os.environ.setdefault(k, v)
    try:
        module = __import__(f"bot.{modname}", fromlist=["install_import_hook"])
    except Exception:
        try:
            module = __import__(modname, fromlist=["install_import_hook"])
        except Exception as exc:
            logger.warning("%s_BRIDGE_IMPORT_FAILED err=%s", log_prefix, exc); return
    try:
        module.install_import_hook()
        setattr(builtins, attr, True)
        logger.warning("%s_BRIDGE_INSTALLED", log_prefix)
    except Exception as exc:
        logger.warning("%s_BRIDGE_INSTALL_FAILED err=%s", log_prefix, exc)


def _install_all_bridges() -> None:
    _install_bridge("trail_sl", _BRIDGES["trail_sl"], {"NIJA_TRAILING_STOP_ENABLED":"true", "NIJA_TRAILING_STOP_POLL_SECONDS":"5", "NIJA_TRAILING_STOP_PCT":"0.006", "NIJA_TRAILING_STOP_ACTIVATION_PCT":"0.003"}, "trailing_stop_loss_runtime_patch", "TRAILING_STOP")
    _install_bridge("breakeven", _BRIDGES["breakeven"], {"NIJA_BREAKEVEN_STOP_ENABLED":"true", "NIJA_BREAKEVEN_STOP_POLL_SECONDS":"5", "NIJA_BREAKEVEN_PROFIT_THRESHOLD_PCT":"0.004", "NIJA_BREAKEVEN_STOP_OFFSET_PCT":"0.0002"}, "breakeven_stop_loss_runtime_patch", "BREAKEVEN_STOP")
    _install_bridge("combo", _BRIDGES["combo"], {"NIJA_COMBO_BE_TRAILING_ENABLED":"true", "NIJA_COMBO_BE_TRAILING_POLL_SECONDS":"5", "NIJA_COMBO_BREAKEVEN_THRESHOLD_PCT":"0.004", "NIJA_COMBO_BREAKEVEN_OFFSET_PCT":"0.0002", "NIJA_COMBO_TRAILING_SWITCH_PCT":"0.007", "NIJA_COMBO_TRAILING_STOP_PCT":"0.005"}, "combo_breakeven_trailing_runtime_patch", "COMBO_BE_TRAILING")
    _install_bridge("trail_tp", _BRIDGES["trail_tp"], {"NIJA_TRAILING_TP_ENABLED":"true", "NIJA_TRAILING_TP_POLL_SECONDS":"5", "NIJA_TRAILING_TP_ACTIVATION_PCT":"0.008", "NIJA_TRAILING_TP_CALLBACK_PCT":"0.003"}, "trailing_take_profit_runtime_patch", "TRAILING_TP")


def install_import_hook() -> None:
    import sys
    _install_all_bridges()
    for name in ("bot.execution_engine", "execution_engine"):
        mod = sys.modules.get(name)
        if mod is not None:
            _patch_engine(mod)
    if getattr(builtins, "_NIJA_AUTO_EXIT_SL_TP_IMPORT_HOOK", False):
        return
    original_import = builtins.__import__
    def hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        mod = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine"):
                _patch_engine(mod)
        except Exception as exc:
            logger.warning("AUTO_EXIT_SL_TP_PATCH_FAILED module=%s err=%s", name, exc)
        return mod
    builtins.__import__ = hook
    setattr(builtins, "_NIJA_AUTO_EXIT_SL_TP_IMPORT_HOOK", True)
    logger.warning("AUTO_EXIT_SL_TP_IMPORT_HOOK_INSTALLED")
