"""Combo breakeven -> trailing stop runtime patch.

Protection sequence per position:
1. WATCH: wait for breakeven threshold.
2. BREAKEVEN: move stop_loss to entry +/- small offset.
3. TRAILING: after trailing switch threshold, move stop_loss with favorable price.
4. Existing auto-exit monitor closes the position if price reverses through stop_loss.

This patch updates the stored open_positions.stop_loss only; the existing
automatic exit/P&L stack remains the single close authority.
"""

from __future__ import annotations

import builtins
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("nija.combo_be_trailing")
_ENGINE_PATCHED_ATTR = "__nija_combo_be_trailing_engine_patch__"
_MONITOR_STARTED_ATTR = "__nija_combo_be_trailing_started__"


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


def _breakeven_pct() -> float:
    return max(0.0005, min(_f(os.environ.get("NIJA_COMBO_BREAKEVEN_THRESHOLD_PCT"), 0.004), 0.25))


def _switch_pct() -> float:
    # Must be >= breakeven threshold so state sequence is deterministic.
    return max(_breakeven_pct(), min(_f(os.environ.get("NIJA_COMBO_TRAILING_SWITCH_PCT"), 0.007), 0.50))


def _offset_pct() -> float:
    return max(0.0, min(_f(os.environ.get("NIJA_COMBO_BREAKEVEN_OFFSET_PCT"), 0.0002), 0.05))


def _trail_pct() -> float:
    return max(0.001, min(_f(os.environ.get("NIJA_COMBO_TRAILING_STOP_PCT"), 0.005), 0.25))


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


def _state(engine: Any) -> dict[str, dict[str, Any]]:
    st = getattr(engine, "_nija_combo_be_trailing_state", None)
    if not isinstance(st, dict):
        st = {}
        setattr(engine, "_nija_combo_be_trailing_state", st)
    return st


def _position_key(pos: dict[str, Any]) -> str:
    symbol = _sym(pos.get("symbol"))
    position_id = str(pos.get("position_id") or symbol)
    return f"{position_id}:{symbol}"


def _profit_threshold_hit(pos: dict[str, Any], price: float, threshold: float) -> bool:
    entry = _f(pos.get("entry_price"), 0.0)
    if entry <= 0 or price <= 0:
        return False
    if _side(pos.get("side")) in {"long", "buy"}:
        return price >= entry * (1.0 + threshold)
    return price <= entry * (1.0 - threshold)


def _breakeven_stop(pos: dict[str, Any]) -> float:
    entry = _f(pos.get("entry_price"), 0.0)
    if entry <= 0:
        return 0.0
    off = _offset_pct()
    if _side(pos.get("side")) in {"long", "buy"}:
        return entry * (1.0 + off)
    return entry * (1.0 - off)


def _trailing_stop(pos: dict[str, Any], row: dict[str, Any], price: float) -> float:
    side = _side(pos.get("side"))
    pct = _trail_pct()
    if side in {"long", "buy"}:
        high = max(_f(row.get("best_price"), price), price)
        row["best_price"] = high
        return high * (1.0 - pct)
    low = min(_f(row.get("best_price"), price), price)
    row["best_price"] = low
    return low * (1.0 + pct)


def _better_stop(pos: dict[str, Any], current_stop: float, new_stop: float) -> bool:
    if new_stop <= 0:
        return False
    if _side(pos.get("side")) in {"long", "buy"}:
        return current_stop <= 0 or new_stop > current_stop
    return current_stop <= 0 or new_stop < current_stop


def _write_stop(ledger: Any, pos: dict[str, Any], new_stop: float, mode: str, price: float) -> bool:
    position_id = str(pos.get("position_id") or "")
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
                    new_stop,
                    f"\nCOMBO_BE_TRAILING mode={mode} market={price:.8f} stop={new_stop:.8f}",
                    position_id,
                ),
            )
            changed = cur.rowcount > 0
        if changed:
            logger.critical(
                "COMBO_BE_TRAILING_STOP_MOVED symbol=%s position_id=%s mode=%s market=%.8f stop_loss=%.8f be_pct=%.4f switch_pct=%.4f trail_pct=%.4f",
                _sym(pos.get("symbol")),
                position_id,
                mode,
                price,
                new_stop,
                _breakeven_pct(),
                _switch_pct(),
                _trail_pct(),
            )
        return changed
    except Exception as exc:
        logger.warning("COMBO_BE_TRAILING_STOP_MOVE_FAILED symbol=%s position_id=%s err=%s", _sym(pos.get("symbol")), position_id, exc)
        return False


def _scan_once(engine: Any) -> int:
    if not _truthy("NIJA_COMBO_BE_TRAILING_ENABLED", "true"):
        return 0
    ledger = getattr(engine, "trade_ledger", None)
    broker = getattr(engine, "broker_client", None)
    if ledger is None or broker is None:
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("COMBO_BE_TRAILING_SCAN_OPEN_POSITIONS_FAILED err=%s", exc)
        return 0
    moved = 0
    st = _state(engine)
    live_keys: set[str] = set()
    for pos in positions:
        symbol = _sym(pos.get("symbol"))
        if not symbol:
            continue
        key = _position_key(pos)
        live_keys.add(key)
        price = _market_price(broker, symbol)
        if price <= 0:
            continue
        row = st.setdefault(key, {"mode": "watch", "best_price": price})
        current_stop = _f(pos.get("stop_loss"), 0.0)
        mode = str(row.get("mode") or "watch")

        if _profit_threshold_hit(pos, price, _breakeven_pct()) and mode == "watch":
            stop = _breakeven_stop(pos)
            if _better_stop(pos, current_stop, stop) and _write_stop(ledger, pos, stop, "breakeven", price):
                moved += 1
                current_stop = stop
            row["mode"] = "breakeven"
            row["best_price"] = price
            logger.warning("COMBO_BE_TRAILING_MODE_SWITCH symbol=%s position_id=%s mode=breakeven", symbol, str(pos.get("position_id") or ""))

        if _profit_threshold_hit(pos, price, _switch_pct()):
            if row.get("mode") != "trailing":
                row["mode"] = "trailing"
                row["best_price"] = price
                logger.warning("COMBO_BE_TRAILING_MODE_SWITCH symbol=%s position_id=%s mode=trailing", symbol, str(pos.get("position_id") or ""))
            stop = _trailing_stop(pos, row, price)
            # Never let trailing go behind breakeven once breakeven has armed.
            be_stop = _breakeven_stop(pos)
            if _side(pos.get("side")) in {"long", "buy"}:
                stop = max(stop, be_stop)
            else:
                stop = min(stop, be_stop)
            if _better_stop(pos, current_stop, stop) and _write_stop(ledger, pos, stop, "trailing", price):
                moved += 1
        elif row.get("mode") == "trailing":
            # Continue moving after switch even if current tick is below switch threshold.
            stop = _trailing_stop(pos, row, price)
            be_stop = _breakeven_stop(pos)
            if _side(pos.get("side")) in {"long", "buy"}:
                stop = max(stop, be_stop)
            else:
                stop = min(stop, be_stop)
            if _better_stop(pos, current_stop, stop) and _write_stop(ledger, pos, stop, "trailing", price):
                moved += 1
    for key in list(st.keys()):
        if key not in live_keys:
            st.pop(key, None)
    return moved


def _start_monitor(engine: Any) -> None:
    if not _truthy("NIJA_COMBO_BE_TRAILING_ENABLED", "true"):
        return
    if getattr(engine, _MONITOR_STARTED_ATTR, False):
        return
    interval = max(2.0, _f(os.environ.get("NIJA_COMBO_BE_TRAILING_POLL_SECONDS"), 5.0))
    setattr(engine, _MONITOR_STARTED_ATTR, True)

    def loop() -> None:
        logger.warning(
            "COMBO_BE_TRAILING_MONITOR_STARTED interval_s=%.2f be_pct=%.4f switch_pct=%.4f trail_pct=%.4f offset_pct=%.4f",
            interval,
            _breakeven_pct(),
            _switch_pct(),
            _trail_pct(),
            _offset_pct(),
        )
        while _truthy("NIJA_COMBO_BE_TRAILING_ENABLED", "true"):
            try:
                _scan_once(engine)
            except Exception as exc:
                logger.warning("COMBO_BE_TRAILING_SCAN_FAILED err=%s", exc)
            time.sleep(interval)

    threading.Thread(target=loop, name="nija-combo-be-trailing", daemon=True).start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _ENGINE_PATCHED_ATTR, False):
        return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        def init_with_combo_be_trailing(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs)
            _start_monitor(self)
        cls.__init__ = init_with_combo_be_trailing
    cls.scan_combo_breakeven_trailing_once = _scan_once
    cls.start_combo_breakeven_trailing_monitor = _start_monitor
    setattr(cls, _ENGINE_PATCHED_ATTR, True)
    logger.warning("COMBO_BE_TRAILING_ENGINE_PATCHED")
    return True


def install_import_hook() -> None:
    import sys
    for name in ("bot.execution_engine", "execution_engine"):
        mod = sys.modules.get(name)
        if mod is not None:
            _patch_engine(mod)
    if getattr(builtins, "_NIJA_COMBO_BE_TRAILING_IMPORT_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        mod = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine"):
                _patch_engine(mod)
        except Exception as exc:
            logger.warning("COMBO_BE_TRAILING_PATCH_FAILED module=%s err=%s", name, exc)
        return mod

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_COMBO_BE_TRAILING_IMPORT_HOOK", True)
    logger.warning("COMBO_BE_TRAILING_IMPORT_HOOK_INSTALLED")
