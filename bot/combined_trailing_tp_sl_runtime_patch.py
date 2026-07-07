"""Combined trailing take-profit + trailing stop-loss manager.

One monitor manages both protections per position:
- trailing stop-loss updates open_positions.stop_loss to protect downside.
- trailing take-profit arms after a favorable move and closes on pullback.
The existing close_position_with_pnl helper records the realized result.
"""
from __future__ import annotations

import builtins, logging, os, threading, time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.combined_trailing_tp_sl")
_PATCHED = "__nija_combined_trailing_tp_sl_engine_patch__"
_STARTED = "__nija_combined_trailing_tp_sl_started__"


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
    if not isinstance(d, dict): return default
    for k in keys:
        if k in d and d.get(k) is not None: return d.get(k)
    return default


def _ok(p: Any) -> bool:
    if isinstance(p, dict):
        s = str(p.get("status") or p.get("state") or "").lower()
        if s in {"filled", "closed", "done", "complete", "completed", "success", "accepted"}: return True
        if p.get("success") is True: return True
        if p.get("order_id") or p.get("filled_price") or p.get("filled_size_usd"):
            return s not in {"error", "failed", "rejected", "cancelled", "canceled"}
        return False
    return bool(p)


def _broker_label(b: Any) -> str:
    try:
        bt = getattr(b, "broker_type", None); raw = getattr(bt, "value", None) or bt
        if raw: return str(raw).strip().lower()
    except Exception: pass
    return type(b).__name__.replace("Broker", "").strip().lower() if b else ""


def _sl_activation() -> float: return max(0.0, min(_f(os.environ.get("NIJA_COMBINED_TRAILING_SL_ACTIVATION_PCT"), 0.003), 0.25))
def _sl_distance() -> float: return max(0.001, min(_f(os.environ.get("NIJA_COMBINED_TRAILING_SL_DISTANCE_PCT"), 0.006), 0.25))
def _tp_activation() -> float: return max(0.0005, min(_f(os.environ.get("NIJA_COMBINED_TRAILING_TP_ACTIVATION_PCT"), 0.008), 0.50))
def _tp_callback() -> float: return max(0.0005, min(_f(os.environ.get("NIJA_COMBINED_TRAILING_TP_CALLBACK_PCT"), 0.003), 0.25))


def _price(broker: Any, symbol: str) -> float:
    if broker is None: return 0.0
    for m in ("get_quote", "get_market_data", "get_ticker", "fetch_ticker"):
        fn = getattr(broker, m, None)
        if not callable(fn): continue
        try:
            q = fn(symbol)
            if isinstance(q, dict):
                p = _f(_get(q, "price", "last", "last_price", "mark_price", default=0.0))
                if p > 0: return p
                bid = _f(_get(q, "bid", "best_bid", default=0.0)); ask = _f(_get(q, "ask", "best_ask", default=0.0))
                if bid > 0 and ask > 0: return (bid + ask) / 2.0
        except TypeError:
            try:
                q = fn(product_ids=[symbol]); books = (q or {}).get("pricebooks", [{}]) if isinstance(q, dict) else [{}]
                book = books[0] if books else {}; bid = _f(((book.get("bids") or [{}])[0]).get("price")); ask = _f(((book.get("asks") or [{}])[0]).get("price"))
                if bid > 0 and ask > 0: return (bid + ask) / 2.0
            except Exception: pass
        except Exception: pass
    return 0.0


def _state(engine: Any) -> dict[str, dict[str, Any]]:
    st = getattr(engine, "_nija_combined_trailing_tp_sl_state", None)
    if not isinstance(st, dict):
        st = {}; setattr(engine, "_nija_combined_trailing_tp_sl_state", st)
    return st


def _key(pos: dict[str, Any]) -> str:
    symbol = _sym(pos.get("symbol")); return f"{pos.get('position_id') or symbol}:{symbol}"


def _fav_hit(pos: dict[str, Any], price: float, pct: float) -> bool:
    entry = _f(pos.get("entry_price"))
    if entry <= 0 or price <= 0: return False
    return price >= entry * (1 + pct) if _side(pos.get("side")) in {"long", "buy"} else price <= entry * (1 - pct)


def _better_stop(pos: dict[str, Any], current: float, new: float) -> bool:
    if new <= 0: return False
    return (current <= 0 or new > current) if _side(pos.get("side")) in {"long", "buy"} else (current <= 0 or new < current)


def _calc_sl(pos: dict[str, Any], row: dict[str, Any], price: float) -> tuple[bool, float, float]:
    if _side(pos.get("side")) in {"long", "buy"}:
        best = max(_f(row.get("sl_best"), price), price); row["sl_best"] = best; return True, best, best * (1 - _sl_distance())
    best = min(_f(row.get("sl_best"), price), price); row["sl_best"] = best; return True, best, best * (1 + _sl_distance())


def _calc_tp(pos: dict[str, Any], row: dict[str, Any], price: float) -> tuple[bool, float, float]:
    if _side(pos.get("side")) in {"long", "buy"}:
        best = max(_f(row.get("tp_best"), price), price); row["tp_best"] = best; trigger = best * (1 - _tp_callback()); return price <= trigger, best, trigger
    best = min(_f(row.get("tp_best"), price), price); row["tp_best"] = best; trigger = best * (1 + _tp_callback()); return price >= trigger, best, trigger


def _write_stop(ledger: Any, pos: dict[str, Any], stop: float, price: float) -> bool:
    pid = str(pos.get("position_id") or "")
    if not pid: return False
    try:
        with ledger._get_connection() as conn:
            cur = conn.cursor(); cur.execute("UPDATE open_positions SET stop_loss = ?, notes = COALESCE(notes, '') || ? WHERE position_id = ? AND status = 'open'", (stop, f"\nCOMBINED_TRAILING_SL market={price:.8f} stop={stop:.8f}", pid)); changed = cur.rowcount > 0
        if changed: logger.critical("COMBINED_TRAILING_SL_MOVED symbol=%s position_id=%s market=%.8f stop_loss=%.8f", _sym(pos.get("symbol")), pid, price, stop)
        return changed
    except Exception as exc:
        logger.warning("COMBINED_TRAILING_SL_MOVE_FAILED symbol=%s position_id=%s err=%s", _sym(pos.get("symbol")), pid, exc); return False


def _exit_order(broker: Any, pos: dict[str, Any], price: float) -> dict[str, Any]:
    symbol = _sym(pos.get("symbol")); qty = _f(pos.get("quantity"))
    if qty <= 0: return {"status": "error", "error": "invalid_position_quantity"}
    close_side = "sell" if _side(pos.get("side")) in {"long", "buy"} else "buy"
    for name, kwargs in (("place_market_order", {"symbol": symbol, "side": close_side, "size": qty}), ("place_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": qty}), ("market_order", {"symbol": symbol, "side": close_side, "quantity": qty})):
        fn = getattr(broker, name, None)
        if not callable(fn): continue
        try:
            out = fn(**kwargs)
            if _ok(out):
                out = out if isinstance(out, dict) else {"status": "filled", "raw": str(out)}; out.setdefault("filled_price", price); return out
        except TypeError:
            try:
                out = fn(symbol, close_side, qty)
                if _ok(out):
                    out = out if isinstance(out, dict) else {"status": "filled", "raw": str(out)}; out.setdefault("filled_price", price); return out
            except Exception: pass
        except Exception: pass
    return {"status": "error", "error": "no_supported_combined_trailing_exit_method"}


def _close(engine: Any, ledger: Any, broker: Any, pos: dict[str, Any], price: float, reason: str) -> bool:
    symbol = _sym(pos.get("symbol")); pid = str(pos.get("position_id") or symbol)
    order = _exit_order(broker, pos, price)
    if not _ok(order):
        logger.error("COMBINED_TRAILING_EXIT_FAILED symbol=%s position_id=%s reason=%s error=%s", symbol, pid, reason, _get(order, "error", default=order)); return False
    fill = _f(_get(order, "filled_price", "average_fill_price", "avg_price", "price", default=price), price); fee = _f(_get(order, "fee", "commission", "fees", default=0.0)); oid = str(_get(order, "order_id", "id", "txid", "client_order_id", default="") or "")
    close_fn = getattr(engine, "close_position_with_pnl", None)
    pnl = close_fn(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason=reason, order_id=oid, broker=_broker_label(broker)) if callable(close_fn) else ledger.close_position_with_pnl(position_id=pid, symbol=symbol, exit_price=fill, exit_fee=fee, exit_reason=reason, order_id=oid, broker=_broker_label(broker))
    if pnl and pnl.get("success"):
        logger.critical("COMBINED_TRAILING_CLOSED symbol=%s position_id=%s reason=%s net_pnl=%.8f pct=%+.4f%%", symbol, pid, reason, _f(pnl.get("net_profit")), _f(pnl.get("profit_pct"))); return True
    return False


def _scan_once(engine: Any) -> int:
    if not _truthy("NIJA_COMBINED_TRAILING_TP_SL_ENABLED", "true"): return 0
    ledger = getattr(engine, "trade_ledger", None); broker = getattr(engine, "broker_client", None)
    if ledger is None or broker is None: return 0
    try: positions = ledger.get_open_positions()
    except Exception as exc: logger.warning("COMBINED_TRAILING_OPEN_POSITIONS_FAILED err=%s", exc); return 0
    st = _state(engine); active = getattr(engine, "active_exit_orders", set()); closed = 0; moved = 0; live = set()
    for pos in positions:
        symbol = _sym(pos.get("symbol")); pid = str(pos.get("position_id") or symbol); k = _key(pos); live.add(k)
        if not symbol or symbol in active or pid in active: continue
        p = _price(broker, symbol)
        if p <= 0: continue
        row = st.setdefault(k, {"sl_armed": 0.0, "tp_armed": 0.0, "sl_best": p, "tp_best": p})
        if _fav_hit(pos, p, _sl_activation()):
            if not row.get("sl_armed"):
                row["sl_armed"] = 1.0; row["sl_best"] = p; logger.critical("COMBINED_TRAILING_SL_ARMED symbol=%s position_id=%s market=%.8f", symbol, pid, p)
            _, best, stop = _calc_sl(pos, row, p)
            if _better_stop(pos, _f(pos.get("stop_loss")), stop) and _write_stop(ledger, pos, stop, p): moved += 1
        if not row.get("tp_armed") and _fav_hit(pos, p, _tp_activation()):
            row["tp_armed"] = 1.0; row["tp_best"] = p; logger.critical("COMBINED_TRAILING_TP_ARMED symbol=%s position_id=%s market=%.8f", symbol, pid, p)
        if row.get("tp_armed"):
            hit, best, trigger = _calc_tp(pos, row, p)
            logger.info("COMBINED_TRAILING_TP_TRACK symbol=%s position_id=%s market=%.8f best=%.8f trigger=%.8f", symbol, pid, p, best, trigger)
            if hit:
                try: active.add(symbol); active.add(pid)
                except Exception: pass
                logger.critical("COMBINED_TRAILING_TP_TRIGGERED symbol=%s position_id=%s market=%.8f best=%.8f trigger=%.8f", symbol, pid, p, best, trigger)
                if _close(engine, ledger, broker, pos, p, "combined_trailing_take_profit"): closed += 1; st.pop(k, None)
                try: active.discard(symbol); active.discard(pid)
                except Exception: pass
    for k in list(st.keys()):
        if k not in live: st.pop(k, None)
    return closed + moved


def _start_monitor(engine: Any) -> None:
    if not _truthy("NIJA_COMBINED_TRAILING_TP_SL_ENABLED", "true") or getattr(engine, _STARTED, False): return
    interval = max(2.0, _f(os.environ.get("NIJA_COMBINED_TRAILING_POLL_SECONDS"), 5.0)); setattr(engine, _STARTED, True)
    def loop() -> None:
        logger.warning("COMBINED_TRAILING_MONITOR_STARTED interval_s=%.2f sl_activation=%.4f sl_distance=%.4f tp_activation=%.4f tp_callback=%.4f", interval, _sl_activation(), _sl_distance(), _tp_activation(), _tp_callback())
        while _truthy("NIJA_COMBINED_TRAILING_TP_SL_ENABLED", "true"):
            try: _scan_once(engine)
            except Exception as exc: logger.warning("COMBINED_TRAILING_SCAN_FAILED err=%s", exc)
            time.sleep(interval)
    threading.Thread(target=loop, name="nija-combined-trailing-tp-sl", daemon=True).start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _PATCHED, False): return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        @wraps(original_init)
        def init_with_combined_trailing(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs); _start_monitor(self)
        cls.__init__ = init_with_combined_trailing
    cls.scan_combined_trailing_tp_sl_once = _scan_once; cls.start_combined_trailing_tp_sl_monitor = _start_monitor; setattr(cls, _PATCHED, True); logger.warning("COMBINED_TRAILING_ENGINE_PATCHED"); return True


def install_import_hook() -> None:
    import sys
    for name in ("bot.execution_engine", "execution_engine"):
        mod = sys.modules.get(name)
        if mod is not None: _patch_engine(mod)
    if getattr(builtins, "_NIJA_COMBINED_TRAILING_IMPORT_HOOK", False): return
    original_import = builtins.__import__
    def hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        mod = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine"): _patch_engine(mod)
        except Exception as exc: logger.warning("COMBINED_TRAILING_PATCH_FAILED module=%s err=%s", name, exc)
        return mod
    builtins.__import__ = hook; setattr(builtins, "_NIJA_COMBINED_TRAILING_IMPORT_HOOK", True); logger.warning("COMBINED_TRAILING_IMPORT_HOOK_INSTALLED")
