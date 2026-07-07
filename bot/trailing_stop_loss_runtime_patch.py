"""Trailing stop-loss runtime patch.

Adds a moving stop that follows favorable price movement.  It patches the
ExecutionEngine so each engine instance maintains trailing state per open
position and exposes ``scan_trailing_stop_loss_once``.  The scan can run beside
NIJA's existing stop-loss / take-profit monitor and closes through the existing
close_position_with_pnl helper after a confirmed market exit order.
"""

from __future__ import annotations

import builtins
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("nija.trailing_stop_loss")
_ENGINE_PATCHED_ATTR = "__nija_trailing_stop_loss_engine_patch__"
_MONITOR_STARTED_ATTR = "__nija_trailing_stop_loss_started__"

# Process-level singleton guard: prevents duplicate worker threads when
# multiple ExecutionEngine instances are created in the same process.
_PROCESS_WORKER_NAME = "nija-trailing-stop"
_PROCESS_STARTED = False
_PROCESS_LOCK = threading.Lock()


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return default if out != out else out
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
    qty = _f(pos.get("quantity"), 0.0)
    if qty <= 0:
        return {"status": "error", "error": "invalid_position_quantity"}
    close_side = "sell" if _side(pos.get("side")) in {"long", "buy"} else "buy"
    attempts = (
        ("place_market_order", {"symbol": symbol, "side": close_side, "size": qty}),
        ("place_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": qty}),
        ("market_order", {"symbol": symbol, "side": close_side, "quantity": qty}),
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
    entry = _f(pos.get("entry_price"), 0.0)
    side = _side(pos.get("side"))
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
    if not _truthy("NIJA_TRAILING_STOP_ENABLED", "true"):
        return 0
    ledger = getattr(engine, "trade_ledger", None)
    broker = getattr(engine, "broker_client", None)
    if ledger is None or broker is None:
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("TRAILING_STOP_SCAN_OPEN_POSITIONS_FAILED err=%s", exc)
        return 0
    closed = 0
    active = getattr(engine, "active_exit_orders", set())
    for pos in positions:
        symbol = _sym(pos.get("symbol"))
        position_id = str(pos.get("position_id") or symbol)
        if not symbol or symbol in active or position_id in active:
            continue
        price = _market_price(broker, symbol)
        if price <= 0:
            continue
        hit, row = _update_trailing_state(engine, pos, price)
        if not hit:
            continue
        try:
            active.add(symbol); active.add(position_id)
        except Exception:
            pass
        logger.critical(
            "TRAILING_STOP_TRIGGERED symbol=%s position_id=%s market=%.8f trailing_stop=%.8f side=%s",
            symbol, position_id, price, _f(row.get("stop")), pos.get("side"),
        )
        order = _place_exit_order(broker, pos, price)
        if not _success(order):
            logger.error("TRAILING_STOP_EXIT_FAILED symbol=%s position_id=%s error=%s", symbol, position_id, _get(order, "error", default=order))
            try:
                active.discard(symbol); active.discard(position_id)
            except Exception:
                pass
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
        try:
            active.discard(symbol); active.discard(position_id)
        except Exception:
            pass
    return closed


def _start_monitor(engine: Any) -> None:
    global _PROCESS_STARTED
    if not _truthy("NIJA_TRAILING_STOP_ENABLED", "true"):
        return
    # Process-level guard (prevents duplicates across multiple engine instances)
    with _PROCESS_LOCK:
        if _PROCESS_STARTED:
            logger.warning(
                "WORKER_ALREADY_RUNNING worker=%s action=skip_duplicate_start",
                _PROCESS_WORKER_NAME,
            )
            print(
                f"[NIJA-PRINT] WORKER_ALREADY_RUNNING worker={_PROCESS_WORKER_NAME}",
                flush=True,
            )
            return
        _PROCESS_STARTED = True
    # Also set the per-engine flag for compatibility with existing checks
    setattr(engine, _MONITOR_STARTED_ATTR, True)
    interval = max(2.0, _f(os.environ.get("NIJA_TRAILING_STOP_POLL_SECONDS"), 5.0))
    def loop() -> None:
        logger.warning("TRAILING_STOP_MONITOR_STARTED interval_s=%.2f pct=%.4f activation_pct=%.4f", interval, _trailing_pct(), _activation_pct())
        while _truthy("NIJA_TRAILING_STOP_ENABLED", "true"):
            try:
                _scan_once(engine)
            except Exception as exc:
                logger.warning("TRAILING_STOP_SCAN_FAILED err=%s", exc)
            time.sleep(interval)
    threading.Thread(target=loop, name=_PROCESS_WORKER_NAME, daemon=True).start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _ENGINE_PATCHED_ATTR, False):
        return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        def init_with_trailing_stop(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs)
            _start_monitor(self)
        cls.__init__ = init_with_trailing_stop
    cls.scan_trailing_stop_loss_once = _scan_once
    cls.start_trailing_stop_loss_monitor = _start_monitor
    setattr(cls, _ENGINE_PATCHED_ATTR, True)
    logger.warning("TRAILING_STOP_ENGINE_PATCHED")
    return True


def install_import_hook() -> None:
    import sys
    for name in ("bot.execution_engine", "execution_engine"):
        mod = sys.modules.get(name)
        if mod is not None:
            _patch_engine(mod)
    if getattr(builtins, "_NIJA_TRAILING_STOP_IMPORT_HOOK", False):
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
    setattr(builtins, "_NIJA_TRAILING_STOP_IMPORT_HOOK", True)
    logger.warning("TRAILING_STOP_IMPORT_HOOK_INSTALLED")
