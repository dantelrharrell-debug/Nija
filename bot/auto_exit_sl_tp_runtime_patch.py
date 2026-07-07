"""Automatic stop-loss and take-profit exit monitor.

Polls open_positions, reads current market prices from the active broker, and
submits a close when a stored stop_loss or take_profit_1/2/3 level is hit. After
an exit fill is confirmed, it calls the position close P&L runtime helper.

Also installs trailing, breakeven, and combo breakeven->trailing stop-loss
runtime patches without rewriting the large package startup file.
"""

from __future__ import annotations

import builtins
import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Optional

logger = logging.getLogger("nija.auto_exit_sl_tp")
_ENGINE_PATCHED_ATTR = "__nija_auto_exit_sl_tp_engine_patch__"
_MONITOR_STARTED_ATTR = "__nija_auto_exit_sl_tp_started__"
_TRAILING_INSTALLED_ATTR = "_NIJA_TRAILING_STOP_LOSS_BRIDGE_INSTALLED"
_BREAKEVEN_INSTALLED_ATTR = "_NIJA_BREAKEVEN_STOP_LOSS_BRIDGE_INSTALLED"
_COMBO_INSTALLED_ATTR = "_NIJA_COMBO_BE_TRAILING_BRIDGE_INSTALLED"


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


def _payload_get(payload: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(payload, dict):
        return default
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return default


def _order_success(payload: Any) -> bool:
    if isinstance(payload, dict):
        status = str(payload.get("status") or payload.get("state") or "").lower()
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


def _get_market_price(broker: Any, symbol: str) -> float:
    if broker is None:
        return 0.0
    for method in ("get_quote", "get_market_data", "get_ticker", "fetch_ticker"):
        fn = getattr(broker, method, None)
        if not callable(fn):
            continue
        try:
            data = fn(symbol)
            if isinstance(data, dict):
                price = _f(_payload_get(data, "price", "last", "last_price", "mark_price", default=0.0), 0.0)
                if price > 0:
                    return price
                bid = _f(_payload_get(data, "bid", "best_bid", default=0.0), 0.0)
                ask = _f(_payload_get(data, "ask", "best_ask", default=0.0), 0.0)
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


def _trigger_for_position(pos: dict[str, Any], price: float) -> tuple[bool, str, float]:
    side = _side(pos.get("side"))
    stop = _f(pos.get("stop_loss"), 0.0)
    tps = [
        ("take_profit_1", _f(pos.get("take_profit_1"), 0.0)),
        ("take_profit_2", _f(pos.get("take_profit_2"), 0.0)),
        ("take_profit_3", _f(pos.get("take_profit_3"), 0.0)),
    ]
    if side in {"long", "buy"}:
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


def _place_exit_order(broker: Any, pos: dict[str, Any], price: float, reason: str) -> dict[str, Any]:
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
            if _order_success(payload):
                out = payload if isinstance(payload, dict) else {"status": "filled", "raw": str(payload)}
                out.setdefault("filled_price", price)
                return out
            errors.append(f"{method}:{payload}")
        except TypeError:
            try:
                payload = fn(symbol, close_side, qty)
                if _order_success(payload):
                    out = payload if isinstance(payload, dict) else {"status": "filled", "raw": str(payload)}
                    out.setdefault("filled_price", price)
                    return out
                errors.append(f"{method}:{payload}")
            except Exception as exc:
                errors.append(f"{method}:{exc}")
        except Exception as exc:
            errors.append(f"{method}:{exc}")
    return {"status": "error", "error": "; ".join(errors) or "no_supported_exit_order_method"}


def _scan_once(engine: Any) -> int:
    ledger = getattr(engine, "trade_ledger", None)
    broker = getattr(engine, "broker_client", None)
    if ledger is None or broker is None:
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("AUTO_EXIT_SCAN_OPEN_POSITIONS_FAILED err=%s", exc)
        return 0
    closed = 0
    active = getattr(engine, "active_exit_orders", set())
    for pos in positions:
        symbol = _sym(pos.get("symbol"))
        position_id = str(pos.get("position_id") or symbol)
        if not symbol or position_id in active or symbol in active:
            continue
        price = _get_market_price(broker, symbol)
        if price <= 0:
            continue
        hit, reason, target = _trigger_for_position(pos, price)
        if not hit:
            continue
        try:
            active.add(position_id)
            active.add(symbol)
        except Exception:
            pass
        logger.critical(
            "AUTO_EXIT_TRIGGERED symbol=%s position_id=%s reason=%s target=%.8f market=%.8f side=%s",
            symbol, position_id, reason, target, price, pos.get("side"),
        )
        order = _place_exit_order(broker, pos, price, reason)
        if not _order_success(order):
            logger.error("AUTO_EXIT_ORDER_FAILED symbol=%s position_id=%s reason=%s error=%s", symbol, position_id, reason, _payload_get(order, "error", default=order))
            try:
                active.discard(position_id); active.discard(symbol)
            except Exception:
                pass
            continue
        fill_price = _f(_payload_get(order, "filled_price", "average_fill_price", "avg_price", "price", default=price), price)
        exit_fee = _f(_payload_get(order, "fee", "commission", "fees", default=0.0), 0.0)
        order_id = str(_payload_get(order, "order_id", "id", "txid", "client_order_id", default="") or "")
        close_fn = getattr(engine, "close_position_with_pnl", None)
        if callable(close_fn):
            pnl = close_fn(position_id=position_id, symbol=symbol, exit_price=fill_price, exit_fee=exit_fee, exit_reason=reason, order_id=order_id, broker=_broker_label(broker))
        else:
            pnl = ledger.close_position_with_pnl(position_id=position_id, symbol=symbol, exit_price=fill_price, exit_fee=exit_fee, exit_reason=reason, order_id=order_id, broker=_broker_label(broker))
        if pnl and pnl.get("success"):
            closed += 1
            logger.critical("AUTO_EXIT_CLOSED symbol=%s position_id=%s net_pnl=%.8f pct=%+.4f%% reason=%s", symbol, position_id, _f(pnl.get("net_profit")), _f(pnl.get("profit_pct")), reason)
        try:
            active.discard(position_id); active.discard(symbol)
        except Exception:
            pass
    return closed


def _start_monitor(engine: Any) -> None:
    if not _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true"):
        return
    if getattr(engine, _MONITOR_STARTED_ATTR, False):
        return
    interval = max(2.0, _f(os.environ.get("NIJA_AUTO_EXIT_POLL_SECONDS"), 5.0))
    setattr(engine, _MONITOR_STARTED_ATTR, True)

    def loop() -> None:
        logger.warning("AUTO_EXIT_SL_TP_MONITOR_STARTED interval_s=%.2f", interval)
        while _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true"):
            try:
                _scan_once(engine)
            except Exception as exc:
                logger.warning("AUTO_EXIT_SL_TP_SCAN_FAILED err=%s", exc)
            time.sleep(interval)

    thread = threading.Thread(target=loop, name="nija-auto-exit-sl-tp", daemon=True)
    thread.start()


def _patch_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _ENGINE_PATCHED_ATTR, False):
        return False
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        @wraps(original_init)
        def init_with_auto_exit(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs)
            _start_monitor(self)
        cls.__init__ = init_with_auto_exit
    cls.scan_stop_loss_take_profit_once = _scan_once
    cls.start_stop_loss_take_profit_monitor = _start_monitor
    setattr(cls, _ENGINE_PATCHED_ATTR, True)
    logger.warning("AUTO_EXIT_SL_TP_ENGINE_PATCHED")
    return True


def _install_trailing_stop_bridge() -> None:
    if getattr(builtins, _TRAILING_INSTALLED_ATTR, False):
        return
    os.environ.setdefault("NIJA_TRAILING_STOP_ENABLED", "true")
    os.environ.setdefault("NIJA_TRAILING_STOP_POLL_SECONDS", "5")
    os.environ.setdefault("NIJA_TRAILING_STOP_PCT", "0.006")
    os.environ.setdefault("NIJA_TRAILING_STOP_ACTIVATION_PCT", "0.003")
    try:
        from bot.trailing_stop_loss_runtime_patch import install_import_hook as _install
    except Exception:
        try:
            from trailing_stop_loss_runtime_patch import install_import_hook as _install  # type: ignore
        except Exception as exc:
            logger.warning("TRAILING_STOP_BRIDGE_IMPORT_FAILED err=%s", exc)
            return
    try:
        _install()
        setattr(builtins, _TRAILING_INSTALLED_ATTR, True)
        logger.warning("TRAILING_STOP_BRIDGE_INSTALLED")
    except Exception as exc:
        logger.warning("TRAILING_STOP_BRIDGE_INSTALL_FAILED err=%s", exc)


def _install_breakeven_stop_bridge() -> None:
    if getattr(builtins, _BREAKEVEN_INSTALLED_ATTR, False):
        return
    os.environ.setdefault("NIJA_BREAKEVEN_STOP_ENABLED", "true")
    os.environ.setdefault("NIJA_BREAKEVEN_STOP_POLL_SECONDS", "5")
    os.environ.setdefault("NIJA_BREAKEVEN_PROFIT_THRESHOLD_PCT", "0.004")
    os.environ.setdefault("NIJA_BREAKEVEN_STOP_OFFSET_PCT", "0.0002")
    try:
        from bot.breakeven_stop_loss_runtime_patch import install_import_hook as _install
    except Exception:
        try:
            from breakeven_stop_loss_runtime_patch import install_import_hook as _install  # type: ignore
        except Exception as exc:
            logger.warning("BREAKEVEN_STOP_BRIDGE_IMPORT_FAILED err=%s", exc)
            return
    try:
        _install()
        setattr(builtins, _BREAKEVEN_INSTALLED_ATTR, True)
        logger.warning("BREAKEVEN_STOP_BRIDGE_INSTALLED")
    except Exception as exc:
        logger.warning("BREAKEVEN_STOP_BRIDGE_INSTALL_FAILED err=%s", exc)


def _install_combo_be_trailing_bridge() -> None:
    if getattr(builtins, _COMBO_INSTALLED_ATTR, False):
        return
    os.environ.setdefault("NIJA_COMBO_BE_TRAILING_ENABLED", "true")
    os.environ.setdefault("NIJA_COMBO_BE_TRAILING_POLL_SECONDS", "5")
    os.environ.setdefault("NIJA_COMBO_BREAKEVEN_THRESHOLD_PCT", "0.004")
    os.environ.setdefault("NIJA_COMBO_BREAKEVEN_OFFSET_PCT", "0.0002")
    os.environ.setdefault("NIJA_COMBO_TRAILING_SWITCH_PCT", "0.007")
    os.environ.setdefault("NIJA_COMBO_TRAILING_STOP_PCT", "0.005")
    try:
        from bot.combo_breakeven_trailing_runtime_patch import install_import_hook as _install
    except Exception:
        try:
            from combo_breakeven_trailing_runtime_patch import install_import_hook as _install  # type: ignore
        except Exception as exc:
            logger.warning("COMBO_BE_TRAILING_BRIDGE_IMPORT_FAILED err=%s", exc)
            return
    try:
        _install()
        setattr(builtins, _COMBO_INSTALLED_ATTR, True)
        logger.warning("COMBO_BE_TRAILING_BRIDGE_INSTALLED")
    except Exception as exc:
        logger.warning("COMBO_BE_TRAILING_BRIDGE_INSTALL_FAILED err=%s", exc)


def install_import_hook() -> None:
    import sys
    _install_trailing_stop_bridge()
    _install_breakeven_stop_bridge()
    _install_combo_be_trailing_bridge()
    for name in ("bot.execution_engine", "execution_engine"):
        mod = sys.modules.get(name)
        if mod is not None:
            _patch_engine(mod)
    if getattr(builtins, "_NIJA_AUTO_EXIT_SL_TP_IMPORT_HOOK", False):
        return
    original_import = builtins.__import__
    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        mod = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine"):
                _patch_engine(mod)
        except Exception as exc:
            logger.warning("AUTO_EXIT_SL_TP_PATCH_FAILED module=%s err=%s", name, exc)
        return mod
    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_AUTO_EXIT_SL_TP_IMPORT_HOOK", True)
    logger.warning("AUTO_EXIT_SL_TP_IMPORT_HOOK_INSTALLED")
