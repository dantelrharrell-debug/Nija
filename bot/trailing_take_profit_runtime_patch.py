"""Trailing take-profit runtime patch.

Arms after a configured favorable move, tracks the best price, and exits when
price pulls back by the callback amount. Close/P&L is delegated to the existing
position close helper.
"""
from __future__ import annotations

import builtins, logging, os, threading, time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.trailing_take_profit")
_PATCHED = "__nija_trailing_tp_engine_patch__"
_STARTED = "__nija_trailing_tp_started__"


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


def _success(p: Any) -> bool:
    if isinstance(p, dict):
        s = str(p.get("status") or p.get("state") or "").lower()
        if s in {"filled", "closed", "done", "complete", "completed", "success", "accepted"}:
            return True
        if p.get("success") is True:
            return True
        if p.get("order_id") or p.get("filled_price") or p.get("filled_size_usd"):
            return s not in {"error", "failed", "rejected", "cancelled", "canceled"}
        return False
    return bool(p)


def _broker_label(b: Any) -> str:
    try:
        bt = getattr(b, "broker_type", None)
        raw = getattr(bt, "value", None) or bt
        if raw:
            return str(raw).lower()
    except Exception:
        pass
    return type(b).__name__.replace("Broker", "").lower() if b else ""


def _activation() -> float:
    return max(0.0005, min(_f(os.environ.get("NIJA_TRAILING_TP_ACTIVATION_PCT"), 0.008), 0.50))


def _callback() -> float:
    return max(0.0005, min(_f(os.environ.get("NIJA_TRAILING_TP_CALLBACK_PCT"), 0.003), 0.25))


def _price(broker: Any, symbol: str) -> float:
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
        except Exception:
            continue
    return 0.0


def _state(engine: Any) -> dict[str, dict[str, Any]]:
    st = getattr(engine, "_nija_trailing_tp_state", None)
    if not isinstance(st, dict):
        st = {}
        setattr(engine, "_nija_trailing_tp_state", st)
    return st


def _key(pos: dict[str, Any]) -> str:
    symbol = _sym(pos.get("symbol"))
    return f"{pos.get('position_id') or symbol}:{symbol}"


def _armed(pos: dict[str, Any], price: float) -> bool:
    entry = _f(pos.get("entry_price"))
    if entry <= 0:
        return False
    if _side(pos.get("side")) in {"long", "buy"}:
        return price >= entry * (1 + _activation())
    return price <= entry * (1 - _activation())


def _track(pos: dict[str, Any], row: dict[str, Any], price: float) -> tuple[bool, float, float]:
    if _side(pos.get("side")) in {"long", "buy"}:
        best = max(_f(row.get("best"), price), price)
        row["best"] = best
        trigger = best * (1 - _callback())
        return price <= trigger, best, trigger
    best = min(_f(row.get("best"), price), price)
    row["best"] = best
    trigger = best * (1 + _callback())
    return price >= trigger, best, trigger


def _exit(broker: Any, pos: dict[str, Any], price: float) -> dict[str, Any]:
    symbol = _sym(pos.get("symbol")); qty = _f(pos.get("quantity"))
    if qty <= 0:
        return {"status": "error", "error": "invalid_position_quantity"}
    side = "sell" if _side(pos.get("side")) in {"long", "buy"} else "buy"
    for name, kwargs in (
        ("place_market_order", {"symbol": symbol, "side": side, "size": qty}),
        ("place_order", {"symbol": symbol, "side": side, "order_type": "market", "quantity": qty}),
        ("market_order", {"symbol": symbol, "side": side, "quantity": qty}),
    ):
        fn = getattr(broker, name, None)
        if not callable(fn):
            continue
        try:
            out = fn(**kwargs)
            if _success(out):
                out = out if isinstance(out, dict) else {"status": "filled", "raw": str(out)}
                out.setdefault("filled_price", price)
                return out
        except TypeError:
            try:
                out = fn(symbol, side, qty)
                if _success(out):
                    out = out if isinstance(out, dict) else {"status": "filled", "raw": str(out)}
                    out.setdefault("filled_price", price)
                    return out
            except Exception:
                pass
        except Exception:
            pass
    return {"status": "error", "error": "no_supported_trailing_tp_exit_method"}


def _scan_once(engine: Any) -> int:
    if not _truthy("NIJA_TRAILING_TP_ENABLED", "true"):
        return 0
    ledger = getattr(engine, "trade_ledger", None); broker = getattr(engine, "broker_client", None)
    if ledger is None or broker is None:
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("TRAILING_TP_OPEN_POSITIONS_FAILED err=%s", exc); return 0
    st = _state(engine); active = getattr(engine, "active_exit_orders", set()); closed = 0; live = set()
    for pos in positions:
        symbol = _sym(pos.get("symbol")); pid = str(pos.get("position_id") or symbol); k = _key(pos); live.add(k)
        if not symbol or symbol in active or pid in active:
            continue
        price = _price(broker, symbol)
        if price <= 0:
            continue
        row = st.setdefault(k, {"armed": 0.0, "best": price})
        if not row.get("armed"):
            if _armed(pos, price):
                row["armed"] = 1.0; row["best"] = price
                logger.critical("TRAILING_TP_ARMED symbol=%s position_id=%s market=%.8f activation_pct=%.4f callback_pct=%.4f", symbol, pid, price, _activation(), _callback())
            continue
        hit, best, trigger = _track(pos, row, price)
        logger.info("TRAILING_TP_TRACK symbol=%s position_id=%s market=%.8f best=%.8f trigger=%.8f", symbol, pid, price, best, trigger)
        if not hit:
            continue
        try:
            active.add(symbol); active.add(pid)
        except Exception:
            pass
        logger.critical("TRAILING_TP_TRIGGERED symbol=%s position_id=%s market=%.8f best=%.8f trigger=%.8f", symbol, pid, price, best, trigger)
        order = _exit(broker, pos, price)
        if not _success(order):
            logger.error("TRAILING_TP_EXIT_FAILED symbol=%s position_id=%s error=%s", symbol, pid, _get(order, "error", default=order))
            try: active.discard(symbol); active.discard(pid)
            except Exception: pass
            continue
        fill = _f(_get(order, "filled_price", "average_fill_price", "avg_price", "price", default=price), price)
        fee = _f(_get(order, "fee", "commission", "fees", default=0.0))
        oid = str(_get(order, "order_id", "id", "txid", "client_order_id", default="") or "")
        close_fn = getattr(engine, "close_position_with_pnl", None)
        pnl = close_fn(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason="trailing_take_profit", order_id=oid, broker=_broker_label(broker)) if callable(close_fn) else ledger.close_position_with_pnl(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason="trailing_take_profit", order_id=oid, broker=_broker_label(broker))
        if pnl and pnl.get("success"):
            closed += 1; st.pop(k, None)
            logger.critical("TRAILING_TP_CLOSED symbol=%s position_id=%s net_pnl=%.8f pct=%+.4f%%", symbol, pid, _f(pnl.get("net_profit")), _f(pnl.get("profit_pct")))
        try: active.discard(symbol); active.discard(pid)
        except Exception: pass
    for k in list(st.keys()):
        if k not in live:
            st.pop(k, None)
    return closed


def _start_monitor(engine: Any) -> None:
    if not _truthy("NIJA_TRAILING_TP_ENABLED", "true") or getattr(engine, _STARTED, False):
        return
    interval = max(2.0, _f(os.environ.get("NIJA_TRAILING_TP_POLL_SECONDS"), 5.0))
    setattr(engine, _STARTED, True)
    def loop() -> None:
        logger.warning("TRAILING_TP_MONITOR_STARTED interval_s=%.2f activation_pct=%.4f callback_pct=%.4f", interval, _activation(), _callback())
        while _truthy("NIJA_TRAILING_TP_ENABLED", "true"):
            try: _scan_once(engine)
            except Exception as exc: logger.warning("TRAILING_TP_SCAN_FAILED err=%s", exc)
            time.sleep(interval)
    threading.Thread(target=loop, name="nija-trailing-take-profit", daemon=True).start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _PATCHED, False):
        return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        @wraps(original_init)
        def init_with_trailing_tp(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs); _start_monitor(self)
        cls.__init__ = init_with_trailing_tp
    cls.scan_trailing_take_profit_once = _scan_once
    cls.start_trailing_take_profit_monitor = _start_monitor
    setattr(cls, _PATCHED, True)
    logger.warning("TRAILING_TP_ENGINE_PATCHED")
    return True


def install_import_hook() -> None:
    import sys
    for name in ("bot.execution_engine", "execution_engine"):
        mod = sys.modules.get(name)
        if mod is not None:
            _patch_engine(mod)
    if getattr(builtins, "_NIJA_TRAILING_TP_IMPORT_HOOK", False):
        return
    original_import = builtins.__import__
    def hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        mod = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine"):
                _patch_engine(mod)
        except Exception as exc:
            logger.warning("TRAILING_TP_PATCH_FAILED module=%s err=%s", name, exc)
        return mod
    builtins.__import__ = hook
    setattr(builtins, "_NIJA_TRAILING_TP_IMPORT_HOOK", True)
    logger.warning("TRAILING_TP_IMPORT_HOOK_INSTALLED")
