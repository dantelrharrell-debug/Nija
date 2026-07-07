"""Breakeven stop-loss runtime patch.

When an open position reaches a configured profit threshold, this monitor moves
that position's stored stop_loss to entry price (optionally plus a tiny offset).
The existing automatic stop-loss/take-profit monitor then performs the actual
exit if price reverses through the breakeven stop.
"""

from __future__ import annotations

import builtins
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("nija.breakeven_stop_loss")
_ENGINE_PATCHED_ATTR = "__nija_breakeven_stop_loss_engine_patch__"
_MONITOR_STARTED_ATTR = "__nija_breakeven_stop_loss_started__"


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


def _threshold_pct() -> float:
    pct = _f(os.environ.get("NIJA_BREAKEVEN_PROFIT_THRESHOLD_PCT"), 0.004)
    return max(0.0005, min(pct, 0.25))


def _offset_pct() -> float:
    pct = _f(os.environ.get("NIJA_BREAKEVEN_STOP_OFFSET_PCT"), 0.0002)
    return max(0.0, min(pct, 0.05))


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


def _breakeven_stop_for_position(pos: dict[str, Any]) -> float:
    entry = _f(pos.get("entry_price"), 0.0)
    if entry <= 0:
        return 0.0
    offset = _offset_pct()
    if _side(pos.get("side")) in {"long", "buy"}:
        return entry * (1.0 + offset)
    return entry * (1.0 - offset)


def _is_threshold_reached(pos: dict[str, Any], price: float) -> bool:
    entry = _f(pos.get("entry_price"), 0.0)
    if entry <= 0 or price <= 0:
        return False
    threshold = _threshold_pct()
    if _side(pos.get("side")) in {"long", "buy"}:
        return price >= entry * (1.0 + threshold)
    return price <= entry * (1.0 - threshold)


def _should_move_stop(pos: dict[str, Any], breakeven_stop: float) -> bool:
    current = _f(pos.get("stop_loss"), 0.0)
    if breakeven_stop <= 0:
        return False
    if _side(pos.get("side")) in {"long", "buy"}:
        return current <= 0 or current < breakeven_stop
    return current <= 0 or current > breakeven_stop


def _move_stop(ledger: Any, pos: dict[str, Any], breakeven_stop: float, market_price: float) -> bool:
    position_id = str(pos.get("position_id") or "")
    symbol = _sym(pos.get("symbol"))
    if not position_id:
        return False
    try:
        with ledger._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE open_positions
                SET stop_loss = ?, notes = COALESCE(notes, '') || ?
                WHERE position_id = ? AND status = 'open'
                """,
                (
                    breakeven_stop,
                    f"\nBREAKEVEN_STOP_ARMED market={market_price:.8f} stop={breakeven_stop:.8f}",
                    position_id,
                ),
            )
            changed = cur.rowcount > 0
        if changed:
            logger.critical(
                "BREAKEVEN_STOP_MOVED symbol=%s position_id=%s entry=%.8f market=%.8f stop_loss=%.8f threshold_pct=%.4f offset_pct=%.4f",
                symbol,
                position_id,
                _f(pos.get("entry_price")),
                market_price,
                breakeven_stop,
                _threshold_pct(),
                _offset_pct(),
            )
        return changed
    except Exception as exc:
        logger.warning("BREAKEVEN_STOP_MOVE_FAILED symbol=%s position_id=%s err=%s", symbol, position_id, exc)
        return False


def _scan_once(engine: Any) -> int:
    if not _truthy("NIJA_BREAKEVEN_STOP_ENABLED", "true"):
        return 0
    ledger = getattr(engine, "trade_ledger", None)
    broker = getattr(engine, "broker_client", None)
    if ledger is None or broker is None:
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("BREAKEVEN_STOP_SCAN_OPEN_POSITIONS_FAILED err=%s", exc)
        return 0
    moved = 0
    for pos in positions:
        symbol = _sym(pos.get("symbol"))
        if not symbol:
            continue
        price = _market_price(broker, symbol)
        if price <= 0:
            continue
        if not _is_threshold_reached(pos, price):
            continue
        new_stop = _breakeven_stop_for_position(pos)
        if not _should_move_stop(pos, new_stop):
            continue
        if _move_stop(ledger, pos, new_stop, price):
            moved += 1
    return moved


def _start_monitor(engine: Any) -> None:
    if not _truthy("NIJA_BREAKEVEN_STOP_ENABLED", "true"):
        return
    if getattr(engine, _MONITOR_STARTED_ATTR, False):
        return
    interval = max(2.0, _f(os.environ.get("NIJA_BREAKEVEN_STOP_POLL_SECONDS"), 5.0))
    setattr(engine, _MONITOR_STARTED_ATTR, True)

    def loop() -> None:
        logger.warning(
            "BREAKEVEN_STOP_MONITOR_STARTED interval_s=%.2f threshold_pct=%.4f offset_pct=%.4f",
            interval,
            _threshold_pct(),
            _offset_pct(),
        )
        while _truthy("NIJA_BREAKEVEN_STOP_ENABLED", "true"):
            try:
                _scan_once(engine)
            except Exception as exc:
                logger.warning("BREAKEVEN_STOP_SCAN_FAILED err=%s", exc)
            time.sleep(interval)

    threading.Thread(target=loop, name="nija-breakeven-stop", daemon=True).start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _ENGINE_PATCHED_ATTR, False):
        return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        def init_with_breakeven_stop(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs)
            _start_monitor(self)
        cls.__init__ = init_with_breakeven_stop
    cls.scan_breakeven_stop_loss_once = _scan_once
    cls.start_breakeven_stop_loss_monitor = _start_monitor
    setattr(cls, _ENGINE_PATCHED_ATTR, True)
    logger.warning("BREAKEVEN_STOP_ENGINE_PATCHED")
    return True


def install_import_hook() -> None:
    import sys
    for name in ("bot.execution_engine", "execution_engine"):
        mod = sys.modules.get(name)
        if mod is not None:
            _patch_engine(mod)
    if getattr(builtins, "_NIJA_BREAKEVEN_STOP_IMPORT_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        mod = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine"):
                _patch_engine(mod)
        except Exception as exc:
            logger.warning("BREAKEVEN_STOP_PATCH_FAILED module=%s err=%s", name, exc)
        return mod

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_BREAKEVEN_STOP_IMPORT_HOOK", True)
    logger.warning("BREAKEVEN_STOP_IMPORT_HOOK_INSTALLED")
